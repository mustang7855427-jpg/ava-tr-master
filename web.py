import asyncio
import base64
import configparser
import hashlib
import hmac
import ipaddress
import hashlib
import json
import mimetypes
import math
import os
import re
import secrets
import ssl
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

mimetypes.add_type("application/wasm", ".wasm", strict=True)

import aiohttp
import redis
from aiohttp import WSMsgType, web
import aiohttp_session
import aiohttp_jinja2
import jinja2
from authlib.oidc.core import CodeIDToken
from cryptography import fernet
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jws import JWSRegistry
import utils.bot_common
from utils.payment_webhook import payment_webhook
from utils.server_logging import configure_server_logging
import common

ROOT = Path(__file__).resolve().parent
FILES_DIR = ROOT / "files"
DEMO_ASSETS_DIR = ROOT / "demo-assets"
RUFFLE_DIR = FILES_DIR / "ruffle"
RUFFLE_WASM_RE = re.compile(r'e\.exports=a\.p\+"([^"]+\.wasm)"')
GAME_SERVER_PORT = 8123
DEMO_MODE = os.environ.get("DEMO_MODE") == "true"
GAME_ASSETS_URL = os.environ.get("GAME_ASSETS_URL", "").strip().rstrip("/")
if GAME_ASSETS_URL:
    assets_url = urlsplit(GAME_ASSETS_URL)
    if (assets_url.scheme != "https" or not assets_url.hostname
            or assets_url.query or assets_url.fragment
            or assets_url.username or assets_url.password):
        raise RuntimeError(
            "GAME_ASSETS_URL must be an HTTPS URL without credentials, "
            "query, or fragment."
        )
GAME_ASSETS_BASE_URL = (
    f"{GAME_ASSETS_URL}/" if GAME_ASSETS_URL
    else "/demo-assets/" if DEMO_MODE
    else "/files/"
)
RUFFLE_BASE_URL = os.environ.get("RUFFLE_BASE_URL", "").strip()
if RUFFLE_BASE_URL:
    ruffle_url = urlsplit(RUFFLE_BASE_URL)
    if (ruffle_url.scheme != "https" or not ruffle_url.hostname
            or ruffle_url.query or ruffle_url.fragment
            or ruffle_url.username or ruffle_url.password):
        raise RuntimeError(
            "RUFFLE_BASE_URL must be an HTTPS URL without credentials, "
            "query, or fragment."
        )
RUFFLE_BASE_URL = (
    f"{RUFFLE_BASE_URL.rstrip('/')}/"
    if RUFFLE_BASE_URL else f"{GAME_ASSETS_BASE_URL}ruffle/"
)

routes = web.RouteTableDef()
if FILES_DIR.is_dir():
    routes.static("/files", str(FILES_DIR))
if DEMO_ASSETS_DIR.is_dir():
    routes.static("/demo-assets", str(DEMO_ASSETS_DIR))
TRUSTED_PROXY_CIDRS = os.environ.get("TRUSTED_PROXY_CIDRS", "").strip()
try:
    TRUSTED_PROXY_NETWORKS = tuple(
        ipaddress.ip_network(cidr.strip(), strict=False)
        for cidr in TRUSTED_PROXY_CIDRS.split(",")
        if cidr.strip()
    )
except ValueError as error:
    raise RuntimeError(
        "TRUSTED_PROXY_CIDRS must be a comma-separated list of valid IP networks."
    ) from error
if any(network.prefixlen == 0 for network in TRUSTED_PROXY_NETWORKS):
    raise RuntimeError(
        "TRUSTED_PROXY_CIDRS cannot include a network covering every IP address."
    )
xml = """<?xml version="1.0" ?>
<cross-domain-policy>
    <allow-access-from domain="*" />
</cross-domain-policy>"""
config = configparser.ConfigParser()
config.read(ROOT / "web.ini")
RENDER_DEPLOYMENT = os.environ.get("RENDER_DEPLOYMENT") == "true"
GAME_SERVER_HOST = os.environ.get(
    "GAME_SERVER_HOST", config["webserver"].get("server_ip", "127.0.0.1"))
if config["webserver"]["allow_reg"].lower() == "true":
    registation = True
else:
    registation = False


@routes.get("/favicon.svg")
async def favicon(request):
    return web.Response(
        text=(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            '<rect width="64" height="64" rx="18" fill="#155eef"/>'
            '<path d="M17 43V21h7l8 11 8-11h7v22h-8V33l-7 9-7-9v10z" '
            'fill="#fff"/></svg>'
        ),
        content_type="image/svg+xml",
    )

registration_attempts = {}
registration_limit = 3
registration_window = 3600
login_failure_limit = 10
login_failure_window = 900
ROLE_NAMES = {
    0: "Gracz",
    1: "Stażysta moderatora",
    2: "Moderator",
    3: "Starszy moderator",
    4: "Kurator",
    5: "Administrator",
}
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
PUBLIC_BASE_URL = (
    os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    or (
        os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
        if RENDER_DEPLOYMENT else ""
    )
    or config["webserver"].get("public_base_url", "").strip().rstrip("/")
)
GOOGLE_OAUTH_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)
GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_ENDPOINT = "https://www.googleapis.com/oauth2/v3/certs"

if bool(GOOGLE_CLIENT_ID) != bool(GOOGLE_CLIENT_SECRET):
    raise RuntimeError(
        "Set both GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to enable Google login."
    )

if PUBLIC_BASE_URL:
    public_url = urlsplit(PUBLIC_BASE_URL)
    if (public_url.scheme != "https" or not public_url.hostname
            or public_url.path or public_url.query or public_url.fragment
            or public_url.username or public_url.password):
        raise RuntimeError(
            "PUBLIC_BASE_URL must be an HTTPS origin without a path."
        )


def _application_base_url():
    return (PUBLIC_BASE_URL
            or config["webserver"]["web_address"].rstrip("/"))


def _client_ip_address(request):
    remote = request.remote
    if not remote:
        return None
    try:
        address = ipaddress.ip_address(remote)
    except ValueError:
        return None

    trusted_networks = request.app["trusted_proxy_networks"]
    if not any(address in network for network in trusted_networks):
        if request.app.get("require_trusted_proxy", False):
            return None
        return address

    forwarded_for = request.headers.get("X-Forwarded-For", "")
    forwarded_addresses = []
    try:
        forwarded_addresses = [
            ipaddress.ip_address(value.strip())
            for value in forwarded_for.split(",")
        ]
    except ValueError:
        return None
    if not forwarded_addresses:
        return None

    while (forwarded_addresses
           and any(address in network for network in trusted_networks)):
        address = forwarded_addresses.pop()
    if any(address in network for network in trusted_networks):
        return None
    return address


def _client_ip_hash(request):
    address = _client_ip_address(request)
    if address is None:
        return None
    return hmac.new(
        request.app["ip_ban_secret"],
        address.packed,
        hashlib.sha256,
    ).hexdigest()


def _clear_expired_ip_ban(redis_client, ip_hash):
    uids_key = f"ipban:{ip_hash}:uids"
    for uid in redis_client.smembers(uids_key):
        uid_key = f"uid:{uid}:ip_ban_hash"
        if redis_client.get(uid_key) == ip_hash:
            redis_client.delete(uid_key)
    redis_client.delete(
        f"ipban:{ip_hash}:expiry",
        f"ipban:{ip_hash}:by",
        uids_key,
    )


def _redis_client():
    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    return redis.Redis.from_url(
        redis_url, decode_responses=True, protocol=2)


def _google_callback_uri():
    redirect_uri = GOOGLE_REDIRECT_URI or (
        _application_base_url() + "/auth/google/callback"
    )
    parsed = urlsplit(redirect_uri)
    if not parsed.hostname:
        raise RuntimeError("Invalid GOOGLE_OAUTH_REDIRECT_URI.")
    if (parsed.scheme != "https"
            and not common.is_loopback_address(parsed.hostname)):
        raise RuntimeError(
            "Google login requires an HTTPS callback outside localhost."
        )
    if (parsed.path != "/auth/google/callback" or parsed.query
            or parsed.fragment or parsed.username or parsed.password):
        raise RuntimeError("Invalid GOOGLE_OAUTH_REDIRECT_URI.")
    return redirect_uri


if GOOGLE_OAUTH_ENABLED:
    _google_callback_uri()


def _ruffle_assets_available():
    if DEMO_MODE:
        return True
    if GAME_ASSETS_URL:
        return True

    ruffle_script = RUFFLE_DIR / "ruffle.js"
    if not ruffle_script.is_file():
        return False

    ruffle_source = ruffle_script.read_text(encoding="utf-8")
    wasm_files = RUFFLE_WASM_RE.findall(ruffle_source)
    core_scripts = tuple(RUFFLE_DIR.glob("core.ruffle.*.js"))
    return (
        bool(wasm_files)
        and bool(core_scripts)
        and all((RUFFLE_DIR / name).is_file() for name in wasm_files)
    )


def get_level(exp):
    exp = int(exp)
    if exp < 0:
        return 0
    completed_level = (math.isqrt(1 + 8 * (exp // 50)) - 1) // 2
    return completed_level + 1


@routes.get("/")
async def index(request):
    session = await aiohttp_session.get_session(request)
    redis_client = request.app["redis"]
    uid = session.get("uid")
    token = session.get("token")
    logged_in = bool(
        uid and token and redis_client.get(f"auth:{token}") == uid
    )
    context = {
        "ruffle_available": _ruffle_assets_available(),
        "is_admin": _admin_session_is_valid(request, session),
        "google_login_enabled": GOOGLE_OAUTH_ENABLED,
        "public_base_url": request.app["public_base_url"],
        "asset_base_url": GAME_ASSETS_BASE_URL,
        "ruffle_base_url": RUFFLE_BASE_URL,
        "demo_mode": DEMO_MODE,
        "logged_in": logged_in,
        "ip_bans_enabled": request.app["ip_bans_enabled"],
        "badge_status": request.query.get("badge", ""),
    }
    if logged_in:
        role_text = redis_client.get(f"uid:{uid}:role") or "0"
        try:
            role = int(role_text)
        except ValueError:
            request.app.logger.warning(
                "Pominięto nieprawidłową rangę konta UID %s", uid)
            role = 0
        badge_visible = (
            redis_client.get(f"uid:{uid}:show_role_badge") != "0"
        )
        context.update({
            "token": token,
            "uid": uid,
            "player_name": (
                redis_client.lindex(f"uid:{uid}:appearance", 0)
                or f"Gracz {uid}"
            ),
            "role_badge": (
                "[A]" if role >= 5 else "[AM]" if role > 0 else ""
            ),
            "badge_visible": badge_visible,
            "owner_claim_available": _owner_claim_is_available(
                request, uid, token),
            "settings_csrf_token": session.setdefault(
                "settings_csrf", secrets.token_urlsafe(32)
            ),
        })
        context["update_time"] = config["webserver"]["update_time"]
        context["game_socket_host"] = GAME_SERVER_HOST
    return aiohttp_jinja2.render_template("index.html", request,
                                          context=context)


@routes.get("/regulamin")
async def server_rules(request):
    base_url = request.app["public_base_url"]
    hostname = urlsplit(base_url).hostname or ""
    return aiohttp_jinja2.render_template(
        "rules.html",
        request,
        context={
            "public_base_url": base_url,
            "local_server": common.is_loopback_address(hostname),
            "demo_mode": DEMO_MODE,
        },
    )


@routes.post("/settings/role-badge")
async def update_role_badge_setting(request):
    session = await aiohttp_session.get_session(request)
    uid = session.get("uid")
    token = session.get("token")
    redis_client = request.app["redis"]
    if (not uid or not token
            or redis_client.get(f"auth:{token}") != uid):
        raise web.HTTPUnauthorized(text="Zaloguj się, aby zmienić ustawienia.")

    origin = request.headers.get("Origin")
    if origin and origin != request.app["public_base_url"]:
        raise web.HTTPForbidden(text="Nieprawidłowe źródło żądania.")

    data = await request.post()
    if not secrets.compare_digest(
            str(data.get("csrf_token", "")),
            str(session.get("settings_csrf", ""))):
        raise web.HTTPForbidden(
            text="Sesja ustawień wygasła. Odśwież stronę.")
    badge_values = data.getall("show_role_badge", [])
    if any(value not in {"0", "1"} for value in badge_values):
        raise web.HTTPBadRequest(text="Nieprawidłowa wartość ustawienia.")

    visible = "1" in badge_values
    redis_client.set(
        f"uid:{uid}:show_role_badge", "1" if visible else "0")
    subscriber_count = redis_client.publish(
        "admin:commands",
        json.dumps({"action": "refresh_avatar", "uid": uid}),
    )
    if subscriber_count:
        status = "updated"
    else:
        status = "saved_pending_refresh"
        request.app.logger.warning(
            "Ustawienie plakietki UID %s zapisano, ale serwer gry "
            "nie odebrał polecenia odświeżenia", uid)
    raise web.HTTPFound(f"/?badge={status}")


@routes.post("/login")
async def login(request):
    data = await request.post()
    account_id = str(data.get("login", "")).strip()
    password = str(data.get("password", ""))
    remote = str(_client_ip_address(request) or request.remote or "unknown")
    failure_digest = hmac.new(
        request.app["ip_ban_secret"],
        b"web-login-failures\0" + remote.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    failure_key = f"web:login-failures:{failure_digest}"
    redis_client = request.app["redis"]

    try:
        failures = int(redis_client.get(failure_key) or 0)
        if failures >= login_failure_limit:
            retry_after = redis_client.ttl(failure_key)
            if retry_after == -1:
                redis_client.expire(failure_key, login_failure_window)
                retry_after = login_failure_window
            raise web.HTTPTooManyRequests(
                text="Zbyt wiele nieudanych prób logowania. Spróbuj później.",
                headers={"Retry-After": str(max(1, retry_after))},
            )

        uid = None
        if (account_id.isdecimal() and len(account_id) <= 20
                and password and len(password) <= 256):
            uid = redis_client.get(f"auth:{password}")
        authenticated = uid is not None and uid == account_id

        if authenticated:
            redis_client.delete(failure_key)
        else:
            failures = redis_client.eval(
                "local failures = redis.call('INCR', KEYS[1]); "
                "if failures == 1 then "
                "redis.call('EXPIRE', KEYS[1], ARGV[1]); end; "
                "return failures",
                1,
                failure_key,
                login_failure_window,
            )
            if failures == login_failure_limit:
                request.app.logger.warning(
                    "Osiągnięto limit nieudanych logowań "
                    "(znacznik źródła %s)", failure_digest[:12])
    except redis.RedisError as error:
        request.app.logger.exception(
            "Nie można bezpiecznie zweryfikować próby logowania.")
        raise web.HTTPServiceUnavailable(
            text="Logowanie jest chwilowo niedostępne. Spróbuj ponownie."
        ) from error

    if authenticated:
        session = await aiohttp_session.new_session(request)
        session["uid"] = uid
        session["token"] = password
    raise web.HTTPFound("/")


@routes.get("/auth/google")
async def google_login(request):
    return await _start_google_oauth(request, "login")


@routes.get("/auth/google/link")
async def google_link(request):
    return await _start_google_oauth(request, "link")


async def _start_google_oauth(request, action):
    if not GOOGLE_OAUTH_ENABLED:
        raise web.HTTPServiceUnavailable(
            text="Logowanie Google nie jest skonfigurowane."
        )

    session = await aiohttp_session.get_session(request)
    if action == "link":
        uid = session.get("uid")
        game_token = session.get("token")
        if (not uid or not game_token
                or request.app["redis"].get(f"auth:{game_token}") != uid):
            raise web.HTTPUnauthorized(
                text="Zaloguj się na konto gry przed łączeniem z Google."
            )
        session["google_oauth_link_uid"] = uid
    else:
        session.pop("google_oauth_link_uid", None)
    session["google_oauth_action"] = action

    callback_uri = _google_callback_uri()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    session["google_oauth_state"] = state
    session["google_oauth_nonce"] = nonce
    session["google_oauth_verifier"] = code_verifier

    authorization_url = GOOGLE_AUTHORIZATION_ENDPOINT + "?" + urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": callback_uri,
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })
    raise web.HTTPFound(authorization_url)


def _verify_google_id_token(encoded_token, jwks, nonce, access_token=None):
    decoded = jwt.decode(
        encoded_token,
        KeySet.import_key_set(jwks),
        registry=JWSRegistry(
            algorithms=["RS256"],
            strict_check_header=True,
        ),
    )
    claims = CodeIDToken(
        decoded.claims,
        decoded.header,
        options={
            "iss": {"values": [GOOGLE_ISSUER, "accounts.google.com"]},
            "aud": {"values": [GOOGLE_CLIENT_ID]},
        },
        params={
            "nonce": nonce,
            "client_id": GOOGLE_CLIENT_ID,
            "access_token": access_token,
        },
    )
    claims.validate(leeway=60)
    if (not isinstance(claims.get("sub"), str)
            or not claims["sub"]
            or claims.get("email_verified") is not True
            or not isinstance(claims.get("email"), str)
            or not claims["email"]):
        raise ValueError("Google account is missing verified identity claims.")
    return claims


async def _exchange_google_code(code, code_verifier, callback_uri):
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as client:
        async with client.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "code": code,
                    "code_verifier": code_verifier,
                    "grant_type": "authorization_code",
                    "redirect_uri": callback_uri,
                },
                allow_redirects=False) as response:
            if response.status != 200:
                raise web.HTTPBadGateway(
                    text="Google nie zaakceptował logowania. Spróbuj ponownie."
                )
            token_data = await response.json()

        if (not isinstance(token_data, dict)
                or not isinstance(token_data.get("id_token"), str)):
            raise web.HTTPBadGateway(
                text="Google nie zwrócił prawidłowego tokenu logowania."
            )

        async with client.get(
                GOOGLE_JWKS_ENDPOINT,
                allow_redirects=False) as response:
            if response.status != 200:
                raise web.HTTPBadGateway(
                    text="Nie można zweryfikować odpowiedzi Google."
                )
            jwks = await response.json()
    return token_data, jwks


async def _google_game_account(
        redis_client, subject, allow_create, link_uid=None, link_token=None):
    subject_digest = hashlib.sha256(
        (GOOGLE_ISSUER + "\0" + subject).encode("utf-8")
    ).hexdigest()
    account_key = f"auth:google:{subject_digest}"
    token_key = f"{account_key}:token"
    lock_key = f"auth:google-lock:{subject_digest}"
    lock_value = secrets.token_urlsafe(32)

    for _ in range(40):
        uid = redis_client.get(account_key)
        if uid and not redis_client.exists(f"uid:{uid}:exp"):
            redis_client.delete(account_key, token_key)
            uid = None
        if uid and link_uid and uid != link_uid:
            raise web.HTTPConflict(
                text="To konto Google jest już połączone z innym kontem gry."
            )
        if uid:
            game_token = redis_client.get(token_key)
            if game_token and redis_client.get(f"auth:{game_token}") == uid:
                return uid, game_token
        if redis_client.set(lock_key, lock_value, nx=True, ex=15):
            break
        await asyncio.sleep(0.05)
    else:
        raise web.HTTPServiceUnavailable(
            text="Nie można teraz utworzyć konta Google. Spróbuj ponownie."
        )

    try:
        uid = redis_client.get(account_key)
        if uid and not redis_client.exists(f"uid:{uid}:exp"):
            redis_client.delete(account_key, token_key)
            uid = None
        if uid and link_uid and uid != link_uid:
            raise web.HTTPConflict(
                text="To konto Google jest już połączone z innym kontem gry."
            )
        if uid:
            game_token = redis_client.get(token_key)
            if game_token and redis_client.get(f"auth:{game_token}") == uid:
                return uid, game_token
            if link_uid and link_token \
                    and redis_client.get(f"auth:{link_token}") == uid:
                redis_client.set(token_key, link_token)
                return uid, link_token
            if link_uid:
                raise web.HTTPConflict(
                    text="Nie można połączyć kont Google z nieprawidłową sesją."
                )
            for _ in range(5):
                game_token = utils.bot_common.random_string()
                if redis_client.set(
                        f"auth:{game_token}", uid, nx=True):
                    redis_client.set(token_key, game_token)
                    return uid, game_token
            raise web.HTTPServiceUnavailable(
                text="Nie można teraz utworzyć sesji Google. Spróbuj ponownie."
            )

        if link_uid:
            if (not link_token
                    or not redis_client.exists(f"uid:{link_uid}:exp")
                    or redis_client.get(f"auth:{link_token}") != link_uid):
                raise web.HTTPUnauthorized(
                    text="Sesja konta gry wygasła. Zaloguj się ponownie."
                )
            redis_client.set(account_key, link_uid)
            redis_client.set(token_key, link_token)
            return link_uid, link_token

        if not allow_create:
            raise web.HTTPForbidden(text="Rejestracja nowych kont jest wyłączona.")
        uid, game_token = utils.bot_common.new_account(redis_client)
        redis_client.set(account_key, uid)
        redis_client.set(token_key, game_token)
        return uid, game_token
    finally:
        redis_client.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end",
            1,
            lock_key,
            lock_value,
        )


@routes.get("/auth/google/callback")
async def google_callback(request):
    if not GOOGLE_OAUTH_ENABLED:
        raise web.HTTPServiceUnavailable(
            text="Logowanie Google nie jest skonfigurowane."
        )

    session = await aiohttp_session.get_session(request)
    expected_state = session.get("google_oauth_state", "")
    received_state = request.query.get("state", "")
    if (not expected_state or not received_state
            or not secrets.compare_digest(expected_state, received_state)):
        raise web.HTTPForbidden(
            text="Sesja logowania Google wygasła. Spróbuj ponownie."
        )

    oauth_action = session.pop("google_oauth_action", "login")
    link_uid = session.pop("google_oauth_link_uid", None)
    link_token = session.get("token") if oauth_action == "link" else None
    nonce = session.pop("google_oauth_nonce", "")
    code_verifier = session.pop("google_oauth_verifier", "")
    session.pop("google_oauth_state", None)
    if oauth_action not in {"login", "link"}:
        raise web.HTTPBadRequest(text="Nieprawidłowa operacja logowania Google.")
    if request.query.get("error"):
        raise web.HTTPBadRequest(text="Logowanie Google zostało anulowane.")
    code = request.query.get("code", "")
    if not nonce or not code_verifier or not code:
        raise web.HTTPBadRequest(text="Nieprawidłowa odpowiedź logowania Google.")

    try:
        token_data, jwks = await _exchange_google_code(
            code, code_verifier, _google_callback_uri()
        )
        identity = _verify_google_id_token(
            token_data["id_token"],
            jwks,
            nonce,
            token_data.get("access_token"),
        )
    except (aiohttp.ClientError, asyncio.TimeoutError):
        request.app.logger.warning("Połączenie z usługą logowania Google nie powiodło się.")
        raise web.HTTPBadGateway(
            text="Usługa logowania Google jest chwilowo niedostępna."
        )
    except (JoseError, KeyError, TypeError, ValueError):
        request.app.logger.warning("Odrzucono nieprawidłową odpowiedź logowania Google.")
        raise web.HTTPForbidden(text="Nie udało się zweryfikować konta Google.")

    redis_client = request.app["redis"]
    if oauth_action == "link":
        if (not link_uid or session.get("uid") != link_uid
                or not link_token
                or redis_client.get(f"auth:{link_token}") != link_uid):
            raise web.HTTPUnauthorized(
                text="Sesja konta gry wygasła. Zaloguj się ponownie."
            )
        await _google_game_account(
            redis_client, identity["sub"], False, link_uid, link_token
        )
    else:
        uid, game_token = await _google_game_account(
            redis_client, identity["sub"], registation
        )
        session.clear()
        session["uid"] = uid
        session["token"] = game_token
    raise web.HTTPFound("/")


@routes.get("/logout")
async def logout(request):
    session = await aiohttp_session.get_session(request)
    session.clear()
    raise web.HTTPFound("/")


@routes.post("/register")
async def register(request):
    if not registation:
        return web.Response(text="Rejestracja jest wyłączona.")
    remote = request.remote or "unknown"
    now = time.monotonic()
    attempts = registration_attempts.get(remote, [])
    attempts = [attempt for attempt in attempts
                if now - attempt < registration_window]
    if len(attempts) >= registration_limit:
        registration_attempts[remote] = attempts
        return web.Response(
            text="Limit rejestracji z tego adresu został osiągnięty.",
            status=429)
    if (remote not in registration_attempts and
            len(registration_attempts) >= 4096):
        registration_attempts.pop(next(iter(registration_attempts)))
    uid, password = utils.bot_common.new_account(app["redis"])
    attempts.append(now)
    registration_attempts[remote] = attempts
    session = await aiohttp_session.new_session(request)
    session["uid"] = uid
    session["token"] = password
    raise web.HTTPFound("/")


@routes.get("/prelogin")
async def prelogin(request):
    if "sid" not in request.query:
        raise web.HTTPClientError()
    try:
        uid = int(request.query["sid"])
    except ValueError:
        raise web.HTTPClientError()
    exp = int(app["redis"].get(f"uid:{uid}:exp"))
    return web.json_response({"user": {"bannerNetworkId": None, "reg": 0,
                                       "paymentGroup": "",
                                       "preloginModuleIds": "", "id": uid,
                                       "avatariaLevel": get_level(exp)}})


@routes.post("/social")
async def social(request):
    data = await request.post()
    if not data["method"]:
        raise web.HTTPClientError()
    if data["method"] == "getTestUsers":
        return web.json_response({"uids": [str(data["user_id"])]})
    elif data["method"] in ["getFriends", "getAppFriends"]:
        return web.json_response([])
    elif data["method"] == "getProfiles":
        return web.json_response([{"id": data["uids"]}])


@routes.get("/appconfig.xml")
async def appconfig(request):
    session = await aiohttp_session.get_session(request)
    if "token" not in session:
        raise web.HTTPUnauthorized()
    context = {"token": session["token"], "uid": session["uid"],
               "ip": config["webserver"]["server_ip"],
               "address": request.app["public_base_url"],
               "asset_base_url": GAME_ASSETS_BASE_URL}
    return aiohttp_jinja2.render_template("appconfig.xml", request,
                                          context=context)


@routes.get("/crossdomain.xml")
async def crossdomain(request):
    request.app.logger.debug("Serving Flash cross-domain policy")
    return web.Response(text=xml)


@routes.route("*", "/big_brother")
@routes.route("*", "/loadingStats")
@routes.route("*", "/client_log")
async def disabled_client_telemetry(request):
    return web.Response(status=204)


@routes.route("*", "/localCallback")
async def disabled_payment_callback(request):
    raise web.HTTPGone(text="Płatności są wyłączone na tym serwerze.")


routes.post("/webhooks/payments")(payment_webhook)


@routes.get("/healthz")
async def health_check(request):
    try:
        request.app["redis"].ping()
    except redis.RedisError as error:
        request.app.logger.exception("Kontrola zdrowia Redis nie powiodła się.")
        raise web.HTTPServiceUnavailable(
            text="Usługa chwilowo niedostępna.") from error
    return web.json_response({"status": "ok"})


async def _tcp_to_websocket(reader, websocket):
    while data := await reader.read(65536):
        await websocket.send_bytes(data)
    await websocket.close()


async def _websocket_to_tcp(websocket, writer, client_state):
    async for message in websocket:
        if message.type == WSMsgType.BINARY:
            writer.write(message.data)
            await writer.drain()
            client_state["bytes_to_game"] += len(message.data)
        elif message.type == WSMsgType.ERROR:
            error = websocket.exception()
            if error is not None:
                raise error
            return
        elif message.type == WSMsgType.TEXT:
            await websocket.close(
                code=1003, message=b"Binary game data required")
            return


@routes.get("/game-socket")
async def game_socket(request):
    origin = request.headers.get("Origin")
    expected_origin = request.app["public_base_url"]
    expected_host = urlsplit(expected_origin).netloc
    session = await aiohttp_session.get_session(request)
    uid = session.get("uid")
    token = session.get("token")
    if (origin != expected_origin or request.host != expected_host
            or not uid or not token
            or request.app["redis"].get(f"auth:{token}") != uid
            or (not RENDER_DEPLOYMENT
                and not common.is_loopback_address(request.remote or ""))):
        raise web.HTTPForbidden(text="Lokalne połączenie gry jest wymagane.")

    ip_hash = None
    if request.app["ip_bans_enabled"]:
        ip_hash = _client_ip_hash(request)
        if ip_hash is None:
            request.app.logger.error(
                "Nie można ustalić adresu klienta połączenia gry; "
                "sprawdź TRUSTED_PROXY_CIDRS")
            raise web.HTTPServiceUnavailable(
                text="Nie można bezpiecznie ustalić adresu połączenia.")
        expiry_key = f"ipban:{ip_hash}:expiry"
        expiry_text = request.app["redis"].get(expiry_key)
        if expiry_text is not None:
            try:
                expiry = int(expiry_text)
            except ValueError:
                request.app.logger.exception(
                    "Nieprawidłowy termin bana IP")
                raise web.HTTPServiceUnavailable(
                    text="Nie można sprawdzić blokady adresu IP.")
            if expiry == 0 or expiry > int(time.time()):
                raise web.HTTPForbidden(
                    text="Ten adres IP jest zablokowany.")
            _clear_expired_ip_ban(request.app["redis"], ip_hash)
        request.app["redis"].set(
            f"uid:{uid}:last_ip_hash", ip_hash, ex=90 * 24 * 60 * 60)

    websocket = web.WebSocketResponse(heartbeat=30)
    await websocket.prepare(request)
    try:
        reader, writer = await asyncio.open_connection(
            GAME_SERVER_HOST, GAME_SERVER_PORT)
    except OSError as error:
        request.app.logger.warning(
            "Nie można połączyć mostu Ruffle z lokalnym serwerem gry: %s",
            error)
        await websocket.close(
            code=1011, message=b"Local game server is unavailable")
        return websocket

    game_socket_state = request.app["game_socket_state"]
    client_state = game_socket_state["clients"].setdefault(uid, {
        "active": 0,
        "connections": 0,
        "bytes_to_game": 0,
    })
    client_state["ip_hash"] = ip_hash
    client_state["websocket"] = websocket
    client_state["connections"] += 1
    client_state["active"] += 1
    tasks = {
        asyncio.create_task(_tcp_to_websocket(reader, websocket)),
        asyncio.create_task(
            _websocket_to_tcp(websocket, writer, client_state)),
    }
    try:
        done, _ = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except OSError as error:
        request.app.logger.debug("Połączenie gry zostało zamknięte: %s", error)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        client_state["active"] -= 1
        if client_state["active"] == 0:
            del game_socket_state["clients"][uid]
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        if not websocket.closed:
            await websocket.close()
    return websocket


@routes.get("/game-status")
async def game_status(request):
    session = await aiohttp_session.get_session(request)
    uid = session.get("uid")
    token = session.get("token")
    redis_client = request.app["redis"]
    if (not uid or not token
            or redis_client.get(f"auth:{token}") != uid):
        raise web.HTTPUnauthorized()
    client_state = request.app["game_socket_state"]["clients"].get(uid, {})
    authenticated = bool(redis_client.sismember("game:online", uid))
    return web.json_response({
        "connected": client_state.get("active", 0) > 0,
        "connections": client_state.get("connections", 0),
        "bytesToGame": client_state.get("bytes_to_game", 0),
        "authenticated": authenticated,
        "gameConnectionId": (
            redis_client.get(f"game:connection:{uid}")
            if authenticated else None
        ),
    })


def _admin_session_is_valid(request, session):
    if (not RENDER_DEPLOYMENT
            and not common.is_loopback_address(request.remote or "")):
        return False

    uid = session.get("uid")
    token = session.get("token")
    if not uid or not token:
        return False

    redis_client = request.app["redis"]
    if (redis_client.get(f"auth:{token}") != uid
            or redis_client.get("admin:owner_uid") != uid):
        return False

    role = redis_client.get(f"uid:{uid}:role")
    try:
        return int(role or 0) >= 5
    except ValueError:
        request.app.logger.warning(
            "Odmowa dostępu do panelu: nieprawidłowa ranga konta UID %s",
            uid)
        return False


def _owner_claim_is_available(request, uid, token):
    if (RENDER_DEPLOYMENT
            or not common.is_loopback_address(request.remote or "")):
        return False
    redis_client = request.app["redis"]
    if (redis_client.get("admin:owner_uid")
            or redis_client.get(f"auth:{token}") != uid):
        return False
    role = redis_client.get(f"uid:{uid}:role")
    try:
        return int(role or 0) >= 5
    except ValueError:
        request.app.logger.warning(
            "Odmowa przypisania właściciela: nieprawidłowa ranga UID %s",
            uid)
        return False


@routes.get("/admin/claim")
async def admin_claim(request):
    session = await aiohttp_session.get_session(request)
    uid = session.get("uid")
    token = session.get("token")
    if not uid or not token \
            or not _owner_claim_is_available(request, uid, token):
        raise web.HTTPForbidden(
            text="Właściciela można ustawić tylko lokalnie dla "
                 "zatwierdzonego konta administratora.")
    origin = request.headers.get("Origin")
    if origin and origin != request.app["public_base_url"]:
        raise web.HTTPForbidden(text="Nieprawidłowe źródło żądania.")
    csrf_token = session.get("owner_claim_csrf")
    if not csrf_token:
        csrf_token = secrets.token_urlsafe(32)
        session["owner_claim_csrf"] = csrf_token
    return aiohttp_jinja2.render_template(
        "claim_owner.html",
        request,
        context={"csrf_token": csrf_token, "uid": uid},
    )


@routes.post("/admin/claim")
async def claim_admin_owner(request):
    session = await aiohttp_session.get_session(request)
    uid = session.get("uid")
    token = session.get("token")
    if not uid or not token \
            or not _owner_claim_is_available(request, uid, token):
        raise web.HTTPForbidden(
            text="Właściciela można ustawić tylko lokalnie dla "
                 "zatwierdzonego konta administratora.")
    origin = request.headers.get("Origin")
    if origin and origin != request.app["public_base_url"]:
        raise web.HTTPForbidden(text="Nieprawidłowe źródło żądania.")
    data = await request.post()
    csrf_token = session.get("owner_claim_csrf", "")
    if not secrets.compare_digest(
            str(data.get("csrf_token", "")), str(csrf_token)):
        raise web.HTTPForbidden(
            text="Sesja potwierdzenia wygasła. Odśwież stronę.")
    if data.get("confirmation") != "USTAW WŁAŚCICIELA":
        raise web.HTTPBadRequest(
            text="Wpisz dokładnie: USTAW WŁAŚCICIELA.")
    if not request.app["redis"].set("admin:owner_uid", uid, nx=True):
        raise web.HTTPConflict(
            text="Właściciel serwera został już wcześniej ustawiony.")
    request.app.logger.info(
        "Lokalnie przypisano konto UID %s jako właściciela serwera", uid)
    raise web.HTTPFound("/admin")


def _load_session_secret(redis_client):
    try:
        redis_client.ping()
    except redis.RedisError as error:
        raise RuntimeError(
            "Redis nie odpowiada. Uruchom lokalną usługę Redis i spróbuj ponownie."
        ) from error

    fernet_key = redis_client.get("web:session_fernet_key")
    if not fernet_key:
        generated_key = fernet.Fernet.generate_key().decode("ascii")
        redis_client.set("web:session_fernet_key", generated_key, nx=True)
        fernet_key = redis_client.get("web:session_fernet_key")
    return base64.urlsafe_b64decode(fernet_key)


def _moderator_list(redis_client, owner_uid, logger):
    moderators = []
    for role_key in redis_client.scan_iter(match="uid:*:role"):
        _, uid, _ = role_key.split(":", 2)
        if uid == owner_uid or not uid.isdecimal():
            continue
        if not redis_client.exists(f"uid:{uid}:exp"):
            continue
        role_value = redis_client.get(role_key)
        try:
            role = int(role_value or 0)
        except ValueError:
            logger.warning(
                "Pominięto nieprawidłową rangę konta UID %s", uid)
            continue
        if role <= 0:
            continue
        name = redis_client.lindex(f"uid:{uid}:appearance", 0) or f"UID {uid}"
        moderators.append({
            "uid": uid,
            "name": name,
            "role": role,
            "role_name": ROLE_NAMES.get(role, "Nieznana ranga"),
        })
    return sorted(moderators, key=lambda moderator: int(moderator["uid"]))


@routes.get("/admin")
async def admin(request):
    session = await aiohttp_session.get_session(request)
    if not _admin_session_is_valid(request, session):
        raise web.HTTPForbidden(
            text="Panel administracyjny jest dostępny tylko dla właściciela.")

    redis_client = request.app["redis"]
    csrf_token = session.get("admin_csrf")
    if not csrf_token:
        csrf_token = secrets.token_urlsafe(32)
        session["admin_csrf"] = csrf_token

    players = []
    now = int(time.time())
    for uid in sorted(redis_client.smembers("game:online"),
                      key=lambda value: int(value) if value.isdecimal() else -1):
        name = redis_client.lindex(f"uid:{uid}:appearance", 0) or f"UID {uid}"
        exp = int(redis_client.get(f"uid:{uid}:exp") or 0)
        mute_until = redis_client.get(f"uid:{uid}:mute_until")
        ban_until = redis_client.get(f"uid:{uid}:ban_expiry")
        banned = bool(redis_client.get(f"uid:{uid}:banned"))
        ip_ban_hash = redis_client.get(f"uid:{uid}:ip_ban_hash")
        ip_ban_expiry = (
            redis_client.get(f"ipban:{ip_ban_hash}:expiry")
            if ip_ban_hash else None
        )
        ip_banned = ip_ban_expiry is not None
        muted = mute_until is not None
        try:
            if banned and ban_until is not None \
                    and int(ban_until) > 0 and int(ban_until) <= now:
                banned = False
            if (ip_banned and int(ip_ban_expiry) > 0
                    and int(ip_ban_expiry) <= now):
                _clear_expired_ip_ban(redis_client, ip_ban_hash)
                ip_banned = False
            if muted and int(mute_until) > 0 and int(mute_until) <= now:
                redis_client.delete(f"uid:{uid}:mute_until")
                muted = False
        except ValueError:
            request.app.logger.exception(
                "Nieprawidłowy termin kary dla UID %s", uid)
        players.append({
            "uid": uid,
            "name": name,
            "level": get_level(exp),
            "banned": banned,
            "ban_until": ban_until,
            "ip_banned": ip_banned,
            "muted": muted,
            "mute_until": mute_until,
        })

    return aiohttp_jinja2.render_template(
        "admin.html", request, context={
            "uid": session["uid"],
            "csrf_token": csrf_token,
            "players": players,
            "moderators": _moderator_list(
                redis_client, session["uid"], request.app.logger),
            "status": request.query.get("status", ""),
            "ip_bans_enabled": request.app["ip_bans_enabled"],
        })


@routes.post("/admin/action")
async def admin_action(request):
    session = await aiohttp_session.get_session(request)
    if not _admin_session_is_valid(request, session):
        raise web.HTTPForbidden(text="Brak dostępu do panelu administracyjnego.")

    origin = request.headers.get("Origin")
    if (origin and origin != request.app["public_base_url"]):
        raise web.HTTPForbidden(text="Nieprawidłowe źródło żądania.")

    data = await request.post()
    csrf_token = session.get("admin_csrf", "")
    if not secrets.compare_digest(str(data.get("csrf_token", "")),
                                  str(csrf_token)):
        raise web.HTTPForbidden(text="Sesja formularza wygasła. Odśwież panel.")

    redis_client = request.app["redis"]
    action = str(data.get("action", ""))
    uid = str(data.get("uid", "")).strip()
    if action != "broadcast" and (not uid.isdecimal()
                                  or not redis_client.exists(f"uid:{uid}:slvr")):
        raise web.HTTPBadRequest(text="Podaj UID istniejącego konta.")
    if action in {
            "ban", "unban", "ban_ip", "unban_ip",
            "mute", "unmute", "warn"} \
            and uid == session["uid"]:
        raise web.HTTPBadRequest(text="Nie można nałożyć kary na własne konto.")
    if action == "set_role":
        owner_uid = redis_client.get("admin:owner_uid")
        if uid == session["uid"] or uid == owner_uid:
            raise web.HTTPForbidden(
                text="Nie można zmieniać rangi właściciela.")
        role_text = str(data.get("role", ""))
        if role_text not in {"0", "1", "2", "3", "4"}:
            raise web.HTTPBadRequest(
                text="Wybierz prawidłową rangę od 0 do 4.")
        current_role_text = redis_client.get(f"uid:{uid}:role") or "0"
        try:
            current_role = int(current_role_text)
        except ValueError:
            request.app.logger.warning(
                "Nie można zmienić nieprawidłowej rangi konta UID %s", uid)
            raise web.HTTPConflict(
                text="Konto ma nieprawidłową rangę. Sprawdź log serwera.")
        if current_role < 0 or current_role > 5:
            raise web.HTTPConflict(
                text="Konto ma rangę poza obsługiwanym zakresem.")
        role = int(role_text)
        redis_client.set(f"uid:{uid}:role", role)
        if not redis_client.publish(
                "admin:commands",
                json.dumps({"action": "refresh_avatar", "uid": uid})):
            request.app.logger.warning(
                "Zmieniono rangę UID %s, ale serwer gry nie odebrał "
                "polecenia odświeżenia awatara", uid)
        request.app.logger.info(
            "Właściciel UID %s zmienił rangę UID %s z %s na %s",
            session["uid"], uid, current_role, role)
        raise web.HTTPFound("/admin?status=updated")

    def publish(payload):
        return redis_client.publish("admin:commands", json.dumps(payload))

    if action in {"ban_ip", "unban_ip"}:
        if not request.app["ip_bans_enabled"]:
            raise web.HTTPServiceUnavailable(
                text="Blokady IP wymagają poprawnie skonfigurowanej "
                     "listy zaufanych proxy.")
        if action == "ban_ip":
            ip_hash = redis_client.get(f"uid:{uid}:last_ip_hash")
            if not ip_hash:
                raise web.HTTPBadRequest(
                    text="Gracz musi najpierw połączyć się z serwerem gry.")
            if (ip_hash
                    == redis_client.get(
                        f"uid:{session['uid']}:last_ip_hash")):
                raise web.HTTPForbidden(
                    text="Nie można zablokować adresu IP właściciela.")
            minutes_text = str(data.get("minutes", "0"))
            if not minutes_text.isdecimal() or len(minutes_text) > 10:
                raise web.HTTPBadRequest(text="Czas bana IP nie może być ujemny.")
            minutes = int(minutes_text)
            now = int(time.time())
            expiry = 0 if minutes == 0 else now + minutes * 60
            if expiry > 2**63 - 1:
                raise web.HTTPBadRequest(
                    text="Podany czas bana IP jest zbyt długi.")
            expiry_key = f"ipban:{ip_hash}:expiry"
            existing_expiry_text = redis_client.get(expiry_key)
            if existing_expiry_text is not None:
                try:
                    existing_expiry = int(existing_expiry_text)
                except ValueError:
                    request.app.logger.exception(
                        "Nieprawidłowy termin istniejącego bana IP")
                    raise web.HTTPConflict(
                        text="Nie można zmienić nieprawidłowej blokady IP.")
                if existing_expiry == 0 or expiry == 0:
                    expiry = 0
                else:
                    expiry = max(expiry, existing_expiry)
            previous_ip_hash = redis_client.get(
                f"uid:{uid}:ip_ban_hash")
            if previous_ip_hash and previous_ip_hash != ip_hash:
                previous_uids_key = f"ipban:{previous_ip_hash}:uids"
                redis_client.srem(previous_uids_key, uid)
                if redis_client.scard(previous_uids_key) == 0:
                    redis_client.delete(
                        f"ipban:{previous_ip_hash}:expiry",
                        f"ipban:{previous_ip_hash}:by",
                        previous_uids_key,
                    )
            pipe = redis_client.pipeline()
            pipe.set(expiry_key, expiry)
            pipe.set(f"ipban:{ip_hash}:by", session["uid"])
            pipe.sadd(f"ipban:{ip_hash}:uids", uid)
            pipe.set(f"uid:{uid}:ip_ban_hash", ip_hash)
            pipe.execute()
            for state in list(
                    request.app["game_socket_state"]["clients"].values()):
                websocket = state.get("websocket")
                if (state.get("ip_hash") == ip_hash
                        and websocket is not None and not websocket.closed):
                    await websocket.close(
                        code=1008, message=b"IP banned by administrator")
            request.app.logger.info(
                "Właściciel UID %s zablokował adres IP używany przez UID %s; "
                "czas w minutach: %s", session["uid"], uid, minutes)
        else:
            ip_hash = redis_client.get(f"uid:{uid}:ip_ban_hash")
            if not ip_hash:
                raise web.HTTPBadRequest(
                    text="UID nie ma przypisanej blokady IP.")
            uids_key = f"ipban:{ip_hash}:uids"
            redis_client.srem(uids_key, uid)
            redis_client.delete(f"uid:{uid}:ip_ban_hash")
            if redis_client.scard(uids_key) == 0:
                redis_client.delete(
                    f"ipban:{ip_hash}:expiry",
                    f"ipban:{ip_hash}:by",
                    uids_key,
                )
            request.app.logger.info(
                "Właściciel UID %s zdjął blokadę IP UID %s",
                session["uid"], uid)
    elif action == "ban":
        minutes_text = str(data.get("minutes", "0"))
        if not minutes_text.isdecimal() or len(minutes_text) > 10:
            raise web.HTTPBadRequest(text="Czas bana nie może być ujemny.")
        minutes = int(minutes_text)
        now = int(time.time())
        expiry = 0 if minutes == 0 else now + minutes * 60
        if expiry > 2**63 - 1:
            raise web.HTTPBadRequest(text="Podany czas bana jest zbyt długi.")
        pipe = redis_client.pipeline()
        pipe.set(f"uid:{uid}:banned", session["uid"])
        pipe.set(f"uid:{uid}:ban_time", int(time.time() * 1000))
        pipe.set(f"uid:{uid}:ban_expiry", expiry)
        pipe.execute()
        request.app.logger.info(
            "Właściciel UID %s zbanował UID %s; czas w minutach: %s",
            session["uid"], uid, minutes)
    elif action == "unban":
        redis_client.delete(
            f"uid:{uid}:banned", f"uid:{uid}:ban_time",
            f"uid:{uid}:ban_expiry")
    elif action == "mute":
        minutes_text = str(data.get("minutes", "0"))
        if not minutes_text.isdecimal() or len(minutes_text) > 10:
            raise web.HTTPBadRequest(
                text="Czas wyciszenia nie może być ujemny.")
        minutes = int(minutes_text)
        until = 0 if minutes == 0 else int(time.time()) + minutes * 60
        if until > 2**63 - 1:
            raise web.HTTPBadRequest(
                text="Podany czas wyciszenia jest zbyt długi.")
        redis_client.set(f"uid:{uid}:mute_until", until)
    elif action == "unmute":
        redis_client.delete(f"uid:{uid}:mute_until")
    elif action == "warn":
        message = str(data.get("message", "")).strip()
        if not message or len(message) > 500:
            raise web.HTTPBadRequest(
                text="Ostrzeżenie musi mieć od 1 do 500 znaków.")
        if uid not in redis_client.smembers("game:online"):
            raise web.HTTPBadRequest(
                text="Ostrzeżenie można wysłać tylko graczowi online.")
        if not publish({"action": "notify", "uid": uid,
                        "text": f"Ostrzeżenie od administracji: {message}"}):
            raise web.HTTPServiceUnavailable(
                text="Serwer gry nie odbiera poleceń panelu.")
        request.app.logger.info(
            "Właściciel UID %s wysłał ostrzeżenie do UID %s",
            session["uid"], uid)
    elif action == "set_level":
        level_text = str(data.get("level", ""))
        if not level_text.isdecimal() or len(level_text) > 10 \
                or int(level_text) < 1:
            raise web.HTTPBadRequest(text="Poziom musi być liczbą co najmniej 1.")
        level = int(level_text)
        exp = 50 * (level - 1) * level // 2
        if exp > 2**63 - 1:
            raise web.HTTPBadRequest(
                text="Poziom przekracza zakres doświadczenia obsługiwany przez serwer.")
        redis_client.set(f"uid:{uid}:exp", exp)
        publish({"action": "notify", "uid": uid,
                 "text": f"Administracja ustawiła poziom {level}. "
                         "Zaloguj się ponownie, aby odświeżyć dane."})
        request.app.logger.info(
            "Właściciel UID %s ustawił UID %s poziom %s",
            session["uid"], uid, level)
    elif action == "broadcast":
        message = str(data.get("message", "")).strip()
        if not message or len(message) > 500:
            raise web.HTTPBadRequest(
                text="Ogłoszenie musi mieć od 1 do 500 znaków.")
        if not publish({"action": "broadcast", "text": message}):
            raise web.HTTPServiceUnavailable(
                text="Serwer gry nie odbiera poleceń panelu.")
    else:
        raise web.HTTPBadRequest(text="Nieznana akcja panelu.")

    raise web.HTTPFound("/admin?status=updated")


async def main():
    global app
    if (RENDER_DEPLOYMENT and not DEMO_MODE
            and not GAME_ASSETS_URL and not FILES_DIR.is_dir()):
        raise RuntimeError(
            "Set GAME_ASSETS_URL to an HTTPS directory containing the "
            "authorized game assets before deploying without files/."
        )
    if not common.is_loopback_address(GAME_SERVER_HOST) and not (
            RENDER_DEPLOYMENT and GAME_SERVER_HOST):
        raise RuntimeError(
            "Most gry może łączyć się z prywatną nazwą hosta wyłącznie "
            "w prywatnym wdrożeniu Render.")
    app = web.Application()
    app.add_routes(routes)
    app["public_base_url"] = _application_base_url()
    app["game_socket_state"] = {
        "clients": {},
    }
    app["redis"] = _redis_client()
    secret_key = _load_session_secret(app["redis"])
    app["ip_ban_secret"] = secret_key
    app["trusted_proxy_networks"] = TRUSTED_PROXY_NETWORKS
    app["ip_bans_enabled"] = (
        not RENDER_DEPLOYMENT or bool(TRUSTED_PROXY_NETWORKS)
    )
    app["require_trusted_proxy"] = (
        RENDER_DEPLOYMENT and bool(TRUSTED_PROXY_NETWORKS)
    )
    if RENDER_DEPLOYMENT and not app["ip_bans_enabled"]:
        app.logger.warning(
            "Blokady IP są wyłączone: skonfiguruj TRUSTED_PROXY_CIDRS "
            "z sieciami proxy platformy.")
    owner_uid = os.environ.get("OWNER_UID", "").strip()
    if owner_uid:
        if (not owner_uid.isdecimal()
                or not app["redis"].exists(f"uid:{owner_uid}:exp")
                or not app["redis"].exists(f"uid:{owner_uid}:slvr")):
            raise RuntimeError(
                "OWNER_UID musi wskazywać istniejące konto gry w Redis. "
                "Zaimportuj dane konta przed ustawieniem Ownera.")
        app["redis"].set("admin:owner_uid", owner_uid)
        app["redis"].set(f"uid:{owner_uid}:role", 5)
    webserver = config["webserver"]
    bind_host = os.environ.get(
        "WEB_BIND_HOST", webserver.get("web_bind_host", "127.0.0.1"))
    if not common.is_loopback_address(bind_host) and not (
            RENDER_DEPLOYMENT and bind_host == "0.0.0.0"):
        raise RuntimeError(
            "Serwer WWW może nasłuchiwać poza localhost wyłącznie "
            "w środowisku Render.")
    cert_path = os.environ.get(
        "WEB_TLS_CERT", webserver.get("tls_cert", "")).strip()
    key_path = os.environ.get(
        "WEB_TLS_KEY", webserver.get("tls_key", "")).strip()
    if bool(cert_path) != bool(key_path):
        raise ValueError("Ustaw jednocześnie tls_cert i tls_key w web.ini.")
    ssl_context = None
    if cert_path:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(cert_path, key_path)
        if not app["public_base_url"].startswith("https://"):
            raise ValueError(
                "Przy TLS PUBLIC_BASE_URL musi zaczynać się od https://.")
    elif (not common.is_loopback_address(bind_host)
          and not (RENDER_DEPLOYMENT
                   and app["public_base_url"].startswith("https://"))):
        raise RuntimeError(
            "Publiczne nasłuchiwanie WWW wymaga TLS albo zaufanego "
            "terminowania TLS przez Render.")
    elif (app["public_base_url"].startswith("https://")
          and not RENDER_DEPLOYMENT):
        raise ValueError("Adres HTTPS wymaga skonfigurowania TLS.")
    aiohttp_session.setup(
        app, EncryptedCookieStorage(secret_key,
                                    secure=(
                                        ssl_context is not None
                                        or app["public_base_url"].startswith(
                                            "https://")
                                    ),
                                    max_age=12 * 60 * 60,
                                    httponly=True,
                                    samesite="Lax"))
    aiohttp_jinja2.setup(
        app, loader=jinja2.FileSystemLoader(str(ROOT / "templates")))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", webserver["web_port"]))
    site = web.TCPSite(runner, bind_host, port, ssl_context=ssl_context)
    try:
        await site.start()
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    configure_server_logging("web.log")
    asyncio.run(main())
