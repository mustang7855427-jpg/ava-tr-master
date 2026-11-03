import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "files" / "data"
VERSIONS_FILE = ROOT / "files" / "versions.json"
CONFIG_KEY = "data/config_fb_pl.zip"


def _zero(element, names):
    changed = False
    for name in names:
        if name in element.attrib and element.attrib[name] != "0":
            element.attrib[name] = "0"
            changed = True
    return changed


def _disable_vip_flag(element):
    changed = False
    for name in ("vipOnly", "isVip", "vip"):
        value = element.attrib.get(name)
        if value is None:
            continue
        if value.lower() in ("true", "false"):
            new_value = "false"
        elif value in ("0", "1"):
            new_value = "0"
        else:
            continue
        if value != new_value:
            element.attrib[name] = new_value
            changed = True
    if ("minVIPCount" in element.attrib and
            element.attrib["minVIPCount"] != "0"):
        element.attrib["minVIPCount"] = "0"
        changed = True
    return changed


def _prepare_xml(name, contents):
    is_inventory = name.startswith("inventory/")
    is_appearance = name == "avatarAppearance/appearance.xml"
    is_tutorial_houses = name == "map/tutorial/npcHouse.xml"
    is_module = name.startswith("modules/")
    is_game_config = name == "location/gamesConfig.xml"
    if not (is_inventory or is_appearance or is_tutorial_houses or
            is_module or is_game_config or name == "location/public.xml"):
        return contents, False

    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    root = ET.fromstring(contents, parser=parser)
    changed = False
    inventory_prices = {"gold", "silver", "ruby", "saleGold", "saleSilver",
                        "saleRuby"}
    appearance_prices = {"gold", "silver", "ruby", "brush"}
    module_price_fields = {
        "gold", "silver", "ruby", "energy", "coinPrice",
        "clanLocationLockPriceInCoins",
    }

    for element in root.iter():
        if is_inventory:
            changed |= _zero(element, inventory_prices)
            changed |= _disable_vip_flag(element)
        elif is_appearance:
            changed |= _zero(element, appearance_prices)
            changed |= _disable_vip_flag(element)
        elif is_tutorial_houses:
            changed |= _zero(element, {"gold"})

        if is_module:
            changed |= _disable_vip_flag(element)
            if isinstance(element.tag, str) and element.tag.lower() == "price":
                changed |= _zero(element, module_price_fields)
            if (name == "modules/clan.xml" and isinstance(element.tag, str)
                    and element.tag.lower() == "chest"):
                changed |= _zero(element, module_price_fields)
            if "clanLocationLockPriceInCoins" in element.attrib:
                changed |= _zero(element, {"clanLocationLockPriceInCoins"})
            for attribute in element.attrib:
                lowered = attribute.lower()
                if lowered.endswith("price") or lowered.endswith("cost"):
                    if element.attrib[attribute] != "0":
                        element.attrib[attribute] = "0"
                        changed = True

        if is_game_config:
            changed |= _zero(element, {"energyPrice"})

        if name == "location/public.xml":
            changed |= _disable_vip_flag(element)

    if not changed:
        return contents, False
    return ET.tostring(
        root,
        encoding="utf-8",
        xml_declaration=contents.lstrip().startswith(b"<?xml"),
    ), True


def main():
    versions = json.loads(VERSIONS_FILE.read_text(encoding="utf-8"))
    if CONFIG_KEY not in versions:
        raise KeyError(f"Missing resource version: {CONFIG_KEY}")

    source_hash = versions[CONFIG_KEY]
    source_path = DATA_DIR / f"config_fb_pl_{source_hash}.zip"
    if not source_path.is_file():
        raise FileNotFoundError(
            f"Nie znaleziono polskiej paczki konfiguracji: {source_path}")

    temporary_path = None
    changed_files = 0
    try:
        with tempfile.NamedTemporaryFile(
                dir=DATA_DIR, suffix=".zip", delete=False) as temporary:
            temporary_path = Path(temporary.name)

        with zipfile.ZipFile(source_path, "r") as source:
            with zipfile.ZipFile(temporary_path, "w") as prepared:
                for info in source.infolist():
                    contents = source.read(info.filename)
                    if info.filename.endswith(".xml"):
                        contents, changed = _prepare_xml(info.filename,
                                                         contents)
                        changed_files += int(changed)
                    prepared.writestr(info, contents)

        digest = hashlib.md5(temporary_path.read_bytes()).hexdigest()
        destination = DATA_DIR / f"config_fb_pl_{digest}.zip"
        if destination == source_path:
            temporary_path.unlink()
        elif destination.exists():
            temporary_path.unlink()
        else:
            os.replace(temporary_path, destination)
        temporary_path = None

        versions[CONFIG_KEY] = digest
        VERSIONS_FILE.write_text(json.dumps(versions), encoding="utf-8")
        print(f"Przygotowano polską paczkę bez opłat: {destination.name}")
        print(f"Zmienione pliki XML: {changed_files}")
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


if __name__ == "__main__":
    main()
