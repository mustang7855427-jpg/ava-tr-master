import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "demo-assets"
CONFIG_FILES = {
    "avatarAppearance/appearance.xml": (
        "<appearance><boy/><girl/></appearance>"
    ),
    "inventory/bathroom.xml": "<config/>",
    "inventory/boyClothes.xml": "<config/>",
    "inventory/decor.xml": "<config/>",
    "inventory/extend/clothesRules.xml": "<config/>",
    "inventory/extend/clothesSets.xml": "<config/>",
    "inventory/furniture.xml": "<config/>",
    "inventory/game.xml": "<config/>",
    "inventory/girlClothes.xml": "<config/>",
    "inventory/kitchen.xml": "<config/>",
    "inventory/present.xml": "<config/>",
    "inventory/roomLayout.xml": "<config/>",
    "modules/achievements.xml": "<config/>",
    "modules/acl.xml": "<config/>",
    "modules/craft.xml": "<config/>",
    "modules/relations.xml": "<relations><statuses/><progresses/></relations>",
    "modules/trophies.xml": "<config/>",
}
PLACEHOLDER_SWF = (
    b"FWS\x09\x13\x00\x00\x00\x08\x00\x00\x00\x00\x0c\x00\x01\x00\x00\x00"
)


def _write_config_archive(path):
    with ZipFile(path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(CONFIG_FILES.items()):
            entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, content.encode("utf-8"))
    return hashlib.md5(path.read_bytes()).hexdigest()


def generate():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    swf_hash = hashlib.md5(PLACEHOLDER_SWF).hexdigest()
    versions = {
        f"swf/{name}.swf": swf_hash
        for name in (
            "Ui", "UiInit", "UiLang_pl", "AvatarIcons", "AvatarAnimation"
        )
    }

    data_dir = OUTPUT / "data"
    data_dir.mkdir(exist_ok=True)
    for language in ("fb_pl", "fb_tr"):
        config_path = data_dir / f"config_{language}.zip"
        config_hash = _write_config_archive(config_path)
        config_path.replace(data_dir / f"config_{language}_{config_hash}.zip")
        versions[f"data/config_{language}.zip"] = config_hash

    swf_dir = OUTPUT / "swf"
    swf_dir.mkdir(exist_ok=True)
    for name in (
        "Ui", "UiInit", "UiLang_pl", "AvatarIcons", "AvatarAnimation"
    ):
        (swf_dir / f"{name}_{swf_hash}.swf").write_bytes(PLACEHOLDER_SWF)

    (OUTPUT / "pnz-city-container.swf").write_bytes(PLACEHOLDER_SWF)
    (OUTPUT / "pnz-city.swf").write_bytes(PLACEHOLDER_SWF)
    (OUTPUT / "favicon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
        '<rect width="16" height="16" rx="3" fill="#435a78"/>'
        '<text x="3" y="12" fill="white" font-size="11">T</text></svg>\n',
        encoding="utf-8",
    )
    (OUTPUT / "versions.json").write_text(
        json.dumps(versions, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    generate()
