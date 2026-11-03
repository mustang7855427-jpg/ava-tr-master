import os
import json
import time
import shutil
import asyncio
import zipfile
import hashlib
import configparser
import aiohttp
from lxml import etree
from urllib.parse import urlsplit

assets_url = os.environ.get("GAME_ASSETS_URL", "").strip().rstrip("/")
try:
    parsed_assets_url = urlsplit(assets_url)
except ValueError as error:
    raise SystemExit(
        "Zmienna GAME_ASSETS_URL zawiera nieprawidłowy adres."
    ) from error
if (parsed_assets_url.scheme != "https" or not parsed_assets_url.hostname
        or parsed_assets_url.username or parsed_assets_url.password
        or parsed_assets_url.query or parsed_assets_url.fragment):
    raise SystemExit(
        "Ustaw zmienną GAME_ASSETS_URL na adres HTTPS własnego magazynu "
        "pełnych zasobów gry."
    )
download_url = assets_url + "/"
versions = {}
with open("update.json", "r") as f:
    config = json.load(f)


async def main():
    async with aiohttp.ClientSession() as session:
        async with session.get(download_url+"versions.json") as resp:
            data = await resp.json()
            print("Pobrano manifest wersji zasobów.")
    tasks = []
    loop = asyncio.get_event_loop()
    async with aiohttp.ClientSession() as session:
        for item in data:
            if data[item] in item or "island" in item.lower():
                continue
            if item in config["ignore"]:
                continue
            tasks.append(loop.create_task(download_file(item, data[item],
                                                        session)))
        await asyncio.wait(tasks)
    print("Przetwarzanie konfiguracji...")
    if "data/config_fb_tr.zip" not in versions:
        print("Nie znaleziono archiwum konfiguracji fb_tr.")
    else:
        await process_config(versions["data/config_fb_tr.zip"])
    async with aiohttp.ClientSession() as session:
        for filename in ["pnz-city.swf", "pnz-city-container.swf"]:
            async with session.get(f"{download_url}app/{filename}") as resp:
                if resp.status != 200:
                    print(f"Nie udało się pobrać pliku: {filename}")
                    return
                content = await resp.read()
            with open(f"files/{filename}", "wb") as f:
                f.write(content)
            print(f"Pobrano plik: {filename}")
        for filename in config["misc"]:
            tmp = filename.split("/")
            tmp.pop()
            folder = "/".join(tmp)
            async with session.get(f"{download_url}{filename}") as resp:
                if resp.status != 200:
                    print(f"Nie udało się pobrać pliku: {filename}")
                    return
                content = await resp.read()
            os.makedirs(f"files/{folder}", exist_ok=True)
            with open(f"files/{filename}", "wb") as f:
                f.write(content)
            print(f"Pobrano plik: {filename}")
    webconfig = configparser.ConfigParser()
    webconfig.read("web.ini")
    webconfig["webserver"]["update_time"] = str(int(time.time()))
    with open("web.ini", "w") as f:
        webconfig.write(f)


async def process_config(version):
    directory = "config_fb_tr"
    if os.path.exists(directory):
        shutil.rmtree(directory)
    os.makedirs(directory)
    file = f"files/data/config_fb_tr_{version}.zip"
    with zipfile.ZipFile(file, 'r') as zip_ref:
        zip_ref.extractall(directory)
    _prepare_polish_config(directory)
    parser = etree.XMLParser(remove_comments=True)
    for filename in ["boyClothes", "girlClothes"]:
        doc = etree.parse(f"{directory}/inventory/{filename}.xml",
                          parser=parser)
        root = doc.getroot()
        for el in root.xpath("//item[@canBuy='0']"):
            del el.attrib["canBuy"]
        for el in root.xpath("//item[@wedding='1']"):
            del el.attrib["wedding"]
        for el in root.xpath("//item[@holiday]"):
            del el.attrib["holiday"]
        for el in root.xpath("//item[@clanOnly='1']"):
            del el.attrib["clanOnly"]
        string = etree.tostring(root, pretty_print=True,
                                xml_declaration=True).decode()
        with open(f"{directory}/inventory/{filename}.xml", "w") as f:
            f.write(string)
    doc = etree.parse(f"{directory}/avatarAppearance/appearance.xml",
                      parser=parser)
    root = doc.getroot()
    for el in root.xpath("//item[@clanOnly='1']"):
        del el.attrib["clanOnly"]
    string = etree.tostring(root, pretty_print=True,
                            xml_declaration=True).decode()
    with open(f"{directory}/avatarAppearance/appearance.xml", "w") as f:
        f.write(string)
    doc = etree.parse(f"{directory}/inventory/stickerPack.xml",
                      parser=parser)
    root = doc.getroot()
    for el in root.xpath("//item"):
        el.attrib["vipOnly"] = "1"
    string = etree.tostring(root, pretty_print=True,
                            xml_declaration=True).decode()
    with open(f"{directory}/inventory/stickerPack.xml", "w") as f:
        f.write(string)
    for filename in ["furniture", "kitchen", "bathroom", "decor",
                     "roomLayout"]:
        doc = etree.parse(f"{directory}/inventory/{filename}.xml",
                          parser=parser)
        root = doc.getroot()
        for el in root.findall(".//item[@canBuy='0']"):
            del el.attrib["canBuy"]
        string = etree.tostring(root, pretty_print=True,
                                xml_declaration=True).decode()
        with open(f"{directory}/inventory/{filename}.xml", "w") as f:
            f.write(string)
        tasks = []
        loop = asyncio.get_event_loop()
        async with aiohttp.ClientSession() as session:
            for el in root.findall(".//item"):
                name = el.attrib["name"]
                folder = filename
                if folder == "roomLayout":
                    if name == "RoomBase":
                        continue
                    folder = "house"
                elif folder == "decor":
                    parent = el.getparent()
                    if parent.attrib["id"] == "achievementsDecor":
                        continue
                url = f"{download_url}swf/furniture/{folder}/{name}.swf"
                tasks.append(loop.create_task(download_furniture(url,
                                                                 session)))
            await asyncio.wait(tasks)
    z = zipfile.ZipFile("files/data/config_fb_tr.zip", mode="w")
    for root, dirs, files in os.walk(directory):
        for file in files:
            z.write(os.path.join(root, file),
                    arcname=os.path.join(root,
                                         file).split("config_fb_tr/")[1])
    z.close()
    with open("files/data/config_fb_tr.zip", mode="rb") as f:
        hash_ = hashlib.md5(f.read()).hexdigest()
    os.rename("files/data/config_fb_tr.zip",
              f"files/data/config_fb_tr_{hash_}.zip")
    versions["data/config_fb_tr.zip"] = hash_
    with open("files/versions.json", "w") as f:
        f.write(json.dumps(versions))


def _prepare_polish_config(directory):
    translation_dir = os.path.join(directory, "translation")
    quest_path = os.path.join(translation_dir, "quest_tr.xml")
    quest_tree = etree.parse(quest_path)
    quest_root = quest_tree.getroot()
    for message in quest_root.xpath(
            ".//message[starts-with(@key, 'schoolQuest')]"):
        message.getparent().remove(message)

    hint = quest_root.xpath(".//message[@key='quest132Comment']")
    if not hint:
        raise RuntimeError(
            "Brak tekstu wskazówki do przetłumaczenia w konfiguracji gry."
        )
    hint[0].text = etree.CDATA(
        '<span class="bold">Wskazówka:</span> Skrzynkę pocztową '
        'znajdziesz w sklepie meblowym w kategorii „Technika”.'
    )
    quest_tree.write(
        quest_path, encoding="UTF-8", xml_declaration=True, pretty_print=True)

    clothes_path = os.path.join(translation_dir, "clothes_tr.xml")
    clothes_tree = etree.parse(clothes_path)
    emoticon = clothes_tree.xpath(".//message[@key='tblSmlAmLabel']")
    if emoticon:
        emoticon[0].text = "Emotikon o_O"
        clothes_tree.write(
            clothes_path, encoding="UTF-8", xml_declaration=True,
            pretty_print=True)

    event_path = os.path.join(directory, "modules", "events",
                              "seasonEvent.xml")
    event_tree = etree.parse(event_path)
    products = event_tree.xpath(".//product[@id='seasonEventKey']")
    if not products:
        raise RuntimeError(
            "Nie znaleziono produktu wydarzenia w konfiguracji gry."
        )
    for product in products:
        product.set("title", "Klucz do wydarzenia Złota Jesień")
        product.attrib.pop("photo", None)
    event_tree.write(
        event_path, encoding="UTF-8", xml_declaration=True,
        pretty_print=True)

    decor_path = os.path.join(directory, "inventory", "decor.xml")
    decor_tree = etree.parse(decor_path)
    for category in decor_tree.xpath(".//category[@id='amusiment']"):
        category.set("logCategory2", "amusement")
    decor_tree.write(
        decor_path, encoding="UTF-8", xml_declaration=True,
        pretty_print=True)

    for filename in os.listdir(translation_dir):
        if (filename.startswith("avacity_")
                and filename.endswith(".xml")
                and filename != "avacity_pl.xml"):
            os.remove(os.path.join(translation_dir, filename))
    shutil.copyfile(
        "files/avacity_pl.xml",
        os.path.join(translation_dir, "avacity_pl.xml"),
    )


async def download_file(filename, version, session):
    if "music" in filename:
        final = filename
    else:
        final = filename.split(".")[0]+f"_{version}."+filename.split(".")[1]
    if os.path.exists("files/"+final):
        if "music" not in filename:
            versions[filename] = version
        return
    async with session.get(download_url+final) as resp:
        if resp.status != 200:
            print(f"Nie udało się pobrać pliku: {final}")
            return
        content = await resp.read()
    tmp = filename.split("/")
    tmp.pop()
    folder = "/".join(tmp)
    os.makedirs("files/"+folder, exist_ok=True)
    with open("files/"+final, "wb") as f:
        f.write(content)
    if "music" not in filename:
        versions[filename] = version
    print(f"Pobrano plik: {final}")


async def download_furniture(url, session):
    folder = url.split("/")[-2]
    final = f"swf/furniture/{folder}/{url.split('/')[-1]}"
    if os.path.exists("files/"+final):
        return
    async with session.get(url) as resp:
        if resp.status != 200:
            print(
                "Nie udało się pobrać pliku: "
                f"{url.split('/')[-2]}/{url.split('/')[-1]}"
            )
            return
        content = await resp.read()
    os.makedirs(f"files/swf/furniture/{folder}", exist_ok=True)
    with open("files/"+final, "wb") as f:
        f.write(content)
    print(f"Pobrano plik: {url.split('/')[-2]}/{url.split('/')[-1]}")

asyncio.run(main())
