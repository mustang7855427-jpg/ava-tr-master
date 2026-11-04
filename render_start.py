import asyncio
import io
import json
import logging
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlsplit

import aiohttp
import redis
import common


ROOT = Path(__file__).resolve().parent
MAX_CONFIG_DOWNLOAD_SIZE = 16 * 1024 * 1024
MAX_CONFIG_UNPACKED_SIZE = 32 * 1024 * 1024
CONFIG_VERSION_RE = re.compile(r"^[0-9a-f]{32}$")
stop_requested = False


def _wait_for_redis(timeout=120):
    redis_url = os.environ.get("REDIS_URL", "").strip()
    if not redis_url:
        raise RuntimeError("REDIS_URL is required for a Render deployment.")

    client = redis.Redis.from_url(
        redis_url,
        decode_responses=True,
        protocol=2,
        socket_connect_timeout=3,
        socket_timeout=3,
    )
    deadline = time.monotonic() + timeout
    last_error = None
    attempts = 0
    try:
        while time.monotonic() < deadline:
            try:
                client.ping()
                if attempts:
                    logging.info("Redis/Valkey is ready.")
                return
            except redis.RedisError as error:
                last_error = error
                attempts += 1
                if attempts == 1 or attempts % 10 == 0:
                    logging.warning(
                        "Redis/Valkey is not ready yet (attempt %s); retrying.",
                        attempts,
                    )
                time.sleep(min(2, max(0, deadline - time.monotonic())))
        raise TimeoutError(
            f"Redis/Valkey did not become ready within {timeout} seconds."
        ) from last_error
    finally:
        client.close()


def _request_stop(signum, frame):
    global stop_requested
    stop_requested = True


def _wait_for_game_server(child):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        exit_code = child.poll()
        if exit_code is not None:
            raise RuntimeError(
                f"Game server exited during startup with status {exit_code}."
            )
        try:
            with socket.create_connection(("127.0.0.1", 8123), timeout=1):
                return
        except OSError:
            time.sleep(1)
    raise TimeoutError("Game server did not start listening within 90 seconds.")


def _public_base_url():
    public_url = (
        os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
        or os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    )
    try:
        common.parse_https_origin(public_url)
    except ValueError as error:
        raise RuntimeError(
            "Set PUBLIC_BASE_URL to the HTTPS custom domain or ensure "
            "Render provides RENDER_EXTERNAL_URL with a valid optional port."
        ) from error
    return public_url


def _game_assets_url():
    assets_url = os.environ.get("GAME_ASSETS_URL", "").strip().rstrip("/")
    parsed = urlsplit(assets_url)
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.query or parsed.fragment
            or parsed.username or parsed.password):
        raise RuntimeError(
            "Set GAME_ASSETS_URL to the HTTPS root of the external game "
            "assets, without credentials, query, or fragment."
        )
    return assets_url


async def _read_limited(response, limit, description):
    content = bytearray()
    async for chunk in response.content.iter_chunked(64 * 1024):
        content.extend(chunk)
        if len(content) > limit:
            raise RuntimeError(f"{description} exceeds the {limit}-byte limit.")
    return bytes(content)


def _config_archive_url(assets_url, manifest_content):
    try:
        versions = json.loads(manifest_content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("The external versions.json is not valid JSON.") from error
    version = (
        versions.get("data/config_fb_tr.zip")
        if isinstance(versions, dict) else None
    )
    if not isinstance(version, str) or not CONFIG_VERSION_RE.fullmatch(version):
        raise RuntimeError(
            "The external versions.json has no valid data/config_fb_tr.zip entry."
        )
    return urljoin(f"{assets_url}/", f"data/config_fb_tr_{version}.zip")


def _extract_game_config(archive_content, destination):
    required_files = {
        "inventory/boyClothes.xml",
        "inventory/girlClothes.xml",
        "inventory/extend/clothesSets.xml",
        "inventory/extend/clothesRules.xml",
        "modules/acl.xml",
        "inventory/game.xml",
        "modules/achievements.xml",
        "modules/trophies.xml",
        "modules/craft.xml",
        "avatarAppearance/appearance.xml",
        "modules/relations.xml",
    }
    destination = Path(destination)
    staging = Path(tempfile.mkdtemp(
        prefix=".config_fb_tr-", dir=destination.parent
    ))
    extracted_files = set()
    unpacked_size = 0
    try:
        with zipfile.ZipFile(io.BytesIO(archive_content)) as archive:
            for entry in archive.infolist():
                name = entry.filename.replace("\\", "/")
                parts = name.rstrip("/").split("/")
                if (not name or name.startswith("/")
                        or any(part in {"", ".", ".."} or ":" in part
                               for part in parts)):
                    raise RuntimeError(
                        "The external game config archive has an unsafe path."
                    )
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise RuntimeError(
                        "The external game config archive contains a symlink."
                    )
                target = staging.joinpath(*PurePosixPath(name).parts)
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                unpacked_size += entry.file_size
                if unpacked_size > MAX_CONFIG_UNPACKED_SIZE:
                    raise RuntimeError("The external game config archive is too large.")
                target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with archive.open(entry) as source, target.open("wb") as output:
                    while True:
                        chunk = source.read(64 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > entry.file_size:
                            raise RuntimeError(
                                "The external game config archive has "
                                "invalid file sizes."
                            )
                        output.write(chunk)
                if written != entry.file_size:
                    raise RuntimeError(
                        "The external game config archive has "
                        "invalid file sizes."
                    )
                extracted_files.add(name)
        missing_files = required_files - extracted_files
        if missing_files:
            missing = ", ".join(sorted(missing_files))
            raise RuntimeError(
                f"The external game config archive is missing required files: {missing}"
            )
        if destination.exists():
            raise RuntimeError(
                f"Refusing to overwrite existing game config directory: {destination}"
            )
        staging.replace(destination)
    except (OSError, zipfile.BadZipFile) as error:
        raise RuntimeError(
            "Could not install the external game config archive."
        ) from error
    finally:
        if staging.exists():
            shutil.rmtree(staging)


async def _prepare_game_config():
    destination = ROOT / "config_fb_tr"
    if destination.is_dir():
        return

    assets_url = _game_assets_url()
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(
            urljoin(f"{assets_url}/", "versions.json"),
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"Could not fetch external versions.json (HTTP {response.status})."
                )
            manifest = await _read_limited(
                response, 1024 * 1024, "External versions.json"
            )
        archive_url = _config_archive_url(assets_url, manifest)
        async with session.get(archive_url, allow_redirects=False) as response:
            if response.status != 200:
                raise RuntimeError(
                    "Could not fetch external game config archive "
                    f"(HTTP {response.status})."
                )
            archive_content = await _read_limited(
                response, MAX_CONFIG_DOWNLOAD_SIZE, "External game config archive"
            )

    _extract_game_config(archive_content, destination)


def _prepare_demo_game_config():
    destination = ROOT / "config_fb_tr"
    if destination.is_dir():
        return

    assets_root = ROOT / "demo-assets"
    manifest_path = assets_root / "versions.json"
    try:
        manifest_content = manifest_path.read_bytes()
    except OSError as error:
        raise RuntimeError(
            "The synthetic demo asset manifest is not available."
        ) from error

    archive_url = _config_archive_url(
        "https://demo-assets.invalid", manifest_content
    )
    archive_name = urlsplit(archive_url).path.rsplit("/", 1)[-1]
    archive_path = assets_root / "data" / archive_name
    try:
        archive_content = archive_path.read_bytes()
    except OSError as error:
        raise RuntimeError(
            "The synthetic demo game config archive is not available."
        ) from error
    if len(archive_content) > MAX_CONFIG_DOWNLOAD_SIZE:
        raise RuntimeError("The synthetic demo game config archive is too large.")

    _extract_game_config(archive_content, destination)


def main():
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    if (os.environ.get("RENDER") != "true"
            and os.environ.get("RENDER_DEPLOYMENT") != "true"):
        raise RuntimeError("render_start.py is only for Render deployments.")
    demo_mode = os.environ.get("DEMO_MODE", "").strip().lower() == "true"
    if demo_mode:
        logging.warning(
            "Starting in public demo mode with synthetic assets; "
            "this is not a playable Avataria client."
        )
        _prepare_demo_game_config()
    else:
        if os.environ.get("OWNER_UID", "").strip() != "5":
            raise RuntimeError(
                "Production Render deployments require OWNER_UID=5."
            )
        _game_assets_url()
        asyncio.run(_prepare_game_config())
    child_environment = os.environ.copy()
    child_environment["RENDER_DEPLOYMENT"] = "true"
    child_environment.setdefault("WEB_BIND_HOST", "0.0.0.0")
    child_environment["PUBLIC_BASE_URL"] = _public_base_url()
    _wait_for_redis()
    children = []
    try:
        children.append(subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "server.py")],
            cwd=ROOT,
            env=child_environment,
        ))
        _wait_for_game_server(children[0])
        children.append(subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "web.py")],
            cwd=ROOT,
            env=child_environment,
        ))

        while not stop_requested:
            for child in children:
                exit_code = child.poll()
                if exit_code is not None:
                    raise RuntimeError(
                        f"Render service process exited with status {exit_code}."
                    )
            time.sleep(1)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()
