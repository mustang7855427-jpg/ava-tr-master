import importlib
import configparser
import json
import threading
import subprocess
import socket
import logging
import os
import secrets
import time
import redis
import exceptions
from utils.server_logging import configure_server_logging
import common
from client import Client
from inventory import Inventory
from parser import Parser
from modules.location import refresh_avatar

modules = ["client_error", "house", "outside", "user_rating",  "mail", "avatar",
           "location_game", "relations", "social_request", "user_rating",
           "competition", "furniture", "billing", "component", "support",
           "passport", "player", "statistics", "shop", "mobile", "confirm",
           "craft", "profession", "inventory", "event"]


def get_git_revision_short_hash():
    try:
        return subprocess.check_output(["git", "rev-parse",
                                        "--short", "HEAD"]).strip().decode()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "Unknown"


class Server():
    def __init__(self, host="127.0.0.1", port=8123,
                 advertised_host="127.0.0.1"):
        self.online = []
        self.inv = {}
        self.advertised_host = advertised_host
        redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
        self.redis = redis.Redis.from_url(
            redis_url, decode_responses=True, protocol=2)
        self.admin_pubsub = self.redis.pubsub(
            ignore_subscribe_messages=True)
        self.parser = Parser()
        self.conflicts = self.parser.parse_conflicts()
        self.achievements = self.parser.parse_achievements()
        self.trophies = self.parser.parse_trophies()
        self.game_items = self.parser.parse_game_items()
        self.appearance = self.parser.parse_appearance()
        self.modules = {}
        for item in modules:
            module = importlib.import_module(f"modules.{item}")
            class_ = getattr(module, module.class_name)
            self.modules[class_.prefix] = class_(self)
        self.revision = get_git_revision_short_hash()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))

    def listen(self):
        try:
            self.redis.ping()
        except redis.RedisError as error:
            raise RuntimeError(
                "Redis nie odpowiada. Uruchom lokalną usługę Redis i spróbuj ponownie."
            ) from error
        self.redis.delete("game:online")
        self.admin_pubsub.subscribe("admin:commands")
        self.sock.listen(5)
        logging.info("Serwer gotowy do przyjmowania połączeń")
        thread = threading.Thread(target=self._background)
        thread.daemon = True
        thread.start()
        while True:
            client, address = self.sock.accept()
            thread = threading.Thread(target=Client(self).handle,
                                      args=(client, address))
            thread.daemon = True
            thread.start()

    def process_data(self, data, client):
        if not client.uid:
            if data["type"] != 1:
                logging.warning(
                    "Klient gry wysłał nieoczekiwany pierwszy pakiet (typ %s)",
                    data["type"])
                client.connection.shutdown(2)
                return
            if not isinstance(data["msg"], list) or len(data["msg"]) < 3:
                logging.warning(
                    "Klient gry wysłał niekompletny pakiet logowania")
                client.connection.shutdown(2)
                return
            self.auth(data["msg"], client)
            return
        if data["type"] == 2:
            client.connection.shutdown(2)
            return
        elif data["type"] == 34:
            prefix = data["msg"][1].split(".")[0]
            if prefix not in self.modules:
                logging.warning(f"Nie znaleziono polecenia {data['msg'][1]}")
                return
            self.modules[prefix].on_message(data["msg"], client)

    def auth(self, msg, client):
        uid = self.redis.get(f"auth:{msg[2]}")
        if not uid:
            logging.warning(
                "Odrzucono logowanie klienta gry: token nie pasuje do konta")
            client.connection.shutdown(2)
            return
        banned = self.redis.get(f"uid:{uid}:banned")
        ban_expiry = self.redis.get(f"uid:{uid}:ban_expiry")
        if banned and ban_expiry:
            try:
                expired = int(ban_expiry) > 0 and int(ban_expiry) <= int(time.time())
            except ValueError:
                expired = False
                logging.exception("Nieprawidłowy termin bana UID %s", uid)
            if expired:
                self.redis.delete(
                    f"uid:{uid}:banned", f"uid:{uid}:ban_time",
                    f"uid:{uid}:ban_expiry")
                banned = None
        if banned:
            ban_time = int(self.redis.get(f"uid:{uid}:ban_time") or
                           int(time.time() * 1000))
            client.send([10, "Konto zostało zablokowane",
                         {"duration": 999999, "banTime": ban_time,
                          "notes": "Konto zostało zablokowane.",
                          "reviewerId": banned,
                          "reasonId": 0, "unbanType": "none", "leftTime": 0,
                          "id": None, "reviewState": 1, "userId": uid,
                          "moderatorId": banned}], type_=2)
            client.connection.shutdown(2)
            return
        for tmp in self.online:
            if tmp.uid == uid:
                try:
                    tmp.connection.shutdown(2)
                except OSError:
                    pass
                break
        client.uid = uid
        client.connection_id = secrets.token_urlsafe(18)
        self.redis.set(f"game:connection:{uid}", client.connection_id)
        self.redis.sadd("game:online", uid)
        self.online.append(client)
        self.redis.set(f"uid:{uid}:lvt", int(time.time()))
        if uid not in self.inv:
            self.inv[uid] = Inventory(self, uid)
        else:
            self.inv[uid].expire = None
        client.send([client.uid, True, False, False], type_=1)
        client.checksummed = True
        logging.info("Klient gry został uwierzytelniony")

    def get_user_data(self, uid):
        pipe = self.redis.pipeline()
        pipe.get(f"uid:{uid}:slvr").get(f"uid:{uid}:enrg")
        pipe.get(f"uid:{uid}:gld").get(f"uid:{uid}:exp").get(f"uid:{uid}:emd")
        pipe.get(f"uid:{uid}:lvt").get(f"uid:{uid}:trid").get(f"uid:{uid}:crt")
        pipe.get(f"uid:{uid}:hrt").get(f"uid:{uid}:role")
        result = pipe.execute()
        if not result[0]:
            return None
        if result[7]:
            crt = int(result[7])
        else:
            crt = self.modules["a"].update_crt(uid)
        if result[8]:
            hrt = int(result[8])
        else:
            hrt = self.modules["frn"].update_hrt(uid)
        if result[9]:
            role = int(result[9])
        else:
            role = 0
        return {"uid": uid, "slvr": int(result[0]), "enrg": int(result[1]),
                "gld": int(result[2]), "exp": int(result[3]),
                "emd": int(result[4]), "lvt": int(result[5]), "crt": crt,
                "hrt": hrt, "trid": result[6], "role": role}

    def get_appearance(self, uid):
        apprnc = self.redis.lrange(f"uid:{uid}:appearance", 0, -1)
        if not apprnc:
            return False
        return {"n": apprnc[0], "nct": int(apprnc[1]), "g": int(apprnc[2]),
                "sc": int(apprnc[3]), "ht": int(apprnc[4]),
                "hc": int(apprnc[5]), "brt": int(apprnc[6]),
                "brc": int(apprnc[7]), "et": int(apprnc[8]),
                "ec": int(apprnc[9]), "fft": int(apprnc[10]),
                "fat": int(apprnc[11]), "fac": int(apprnc[12]),
                "ss": int(apprnc[13]), "ssc": int(apprnc[14]),
                "mt": int(apprnc[15]), "mc": int(apprnc[16]),
                "sh": int(apprnc[17]), "shc": int(apprnc[18]),
                "rg": int(apprnc[19]), "rc": int(apprnc[20]),
                "pt": int(apprnc[21]), "pc": int(apprnc[22]),
                "bt": int(apprnc[23]), "bc": int(apprnc[24])}

    def get_clothes(self, uid, type_):
        clothes = []
        for item in self.redis.smembers(f"uid:{uid}:wearing"):
            if "_" in item:
                id_, clid = item.split("_")
                clothes.append({"id": id_, "clid": clid})
            else:
                clothes.append({"id": item, "clid": None})
        if type_ == 1:
            clths = {"cc": "casual", "ccltns": {"casual": {"cct": [],
                                                           "cn": "",
                                                           "ctp": "casual"}}}
            for item in clothes:
                if item["clid"]:
                    clths["ccltns"]["casual"]["cct"].append(f"{item['id']}:"
                                                            f"{item['clid']}")
                else:
                    clths["ccltns"]["casual"]["cct"].append(item["id"])
        elif type_ == 2:
            clths = {"clths": []}
            for item in clothes:
                clths["clths"].append({"tpid": item["id"],
                                       "clid": item["clid"]})
        elif type_ == 3:
            clths = {"cct": []}
            for item in clothes:
                if item["clid"]:
                    clths["cct"].append(f"{item['id']}:{item['clid']}")
                else:
                    clths["cct"].append(item["id"])
        return clths

    def get_room_items(self, uid, room):
        if "_" in room:
            raise exceptions.WrongRoom()
        items = []
        for name in self.redis.smembers(f"rooms:{uid}:{room}:items"):
            item = self.redis.lrange(f"rooms:{uid}:{room}:items:{name}", 0, -1)
            name, lid = name.split("_")
            if len(item) == 5:
                items.append({"tpid": name, "x": float(item[0]),
                              "y": float(item[1]), "z": float(item[2]),
                              "d": int(item[3]), "lid": int(lid),
                              "rid": item[4]})
            else:
                items.append({"tpid": name, "x": float(item[0]),
                              "y": float(item[1]), "z": float(item[2]),
                              "d": int(item[3]), "lid": int(lid)})
        return items

    def _background(self):
        next_status_log = 0
        while True:
            try:
                message = self.admin_pubsub.get_message(timeout=1)
            except redis.RedisError:
                logging.exception(
                    "Nie udało się odczytać polecenia panelu admina")
                time.sleep(1)
                continue
            if message:
                try:
                    command = json.loads(message["data"])
                    action = command.get("action")
                    text = command.get("text", "")
                    if action == "broadcast":
                        for client in self.online.copy():
                            client.send(["cp.ms.rsm", {"txt": text}])
                    elif action == "notify":
                        uid = str(command.get("uid", ""))
                        for client in self.online.copy():
                            if client.uid == uid:
                                client.send(["cp.ms.rsm", {"txt": text}])
                                break
                    elif action == "refresh_avatar":
                        uid = str(command.get("uid", ""))
                        for client in self.online.copy():
                            if client.uid == uid:
                                refresh_avatar(client, self)
                                break
                except (TypeError, ValueError, KeyError):
                    logging.exception("Nieprawidłowe polecenie panelu admina")

            now = int(time.time())
            for client in self.online.copy():
                try:
                    banned = self.redis.get(f"uid:{client.uid}:banned")
                    if not banned:
                        continue
                    ban_expiry = self.redis.get(
                        f"uid:{client.uid}:ban_expiry")
                    if ban_expiry and int(ban_expiry) > 0 \
                            and int(ban_expiry) <= now:
                        self.redis.delete(
                            f"uid:{client.uid}:banned",
                            f"uid:{client.uid}:ban_time",
                            f"uid:{client.uid}:ban_expiry")
                        continue
                    ban_time = int(self.redis.get(
                        f"uid:{client.uid}:ban_time") or now * 1000)
                    client.send([10, "Konto zostało zablokowane",
                                 {"duration": 999999, "banTime": ban_time,
                                  "notes": "Konto zostało zablokowane.",
                                  "reviewerId": banned, "reasonId": 0,
                                  "unbanType": "none", "leftTime": 0,
                                  "id": None, "reviewState": 1,
                                  "userId": client.uid,
                                  "moderatorId": banned}], type_=2)
                    client.connection.shutdown(2)
                except (OSError, ValueError):
                    logging.exception(
                        "Nie udało się zastosować bana dla UID %s",
                        client.uid)
                except redis.RedisError:
                    logging.exception(
                        "Nie udało się sprawdzić bana dla UID %s",
                        client.uid)

            if time.monotonic() >= next_status_log:
                logging.info("Liczba graczy online: %d", len(self.online))
                next_status_log = time.monotonic() + 60
            for uid in self.inv.copy():
                inv = self.inv[uid]
                if inv.expire and time.time() - inv.expire > 0:
                    del self.inv[uid]


if __name__ == "__main__":
    configure_server_logging("game.log")
    config = configparser.ConfigParser()
    config.read("web.ini")
    webserver = config["webserver"]
    render_deployment = os.environ.get("RENDER_DEPLOYMENT") == "true"
    game_bind_host = os.environ.get(
        "GAME_BIND_HOST", webserver.get("game_bind_host", "127.0.0.1"))
    if not common.is_loopback_address(game_bind_host) and not (
            render_deployment and game_bind_host == "0.0.0.0"):
        raise RuntimeError(
            "Serwer gry może nasłuchiwać poza localhost wyłącznie jako "
            "prywatna usługa Render.")
    advertised_host = os.environ.get(
        "GAME_SERVER_HOST", webserver.get("server_ip", "127.0.0.1"))
    if not render_deployment and not common.is_loopback_address(
            advertised_host):
        raise RuntimeError(
            "Publiczny adres serwera gry jest dozwolony wyłącznie "
            "w prywatnym wdrożeniu Render.")
    server = Server(
        host=game_bind_host,
        advertised_host=advertised_host)
    server.listen()
