import time
from modules.base_module import Module
import utils.bot_common

class_name = "Component"


class Component(Module):
    prefix = "cp"

    def __init__(self, server):
        self.server = server
        self.commands = {"cht": self.chat, "m": self.moderation,
                         "ms": self.message}
        self.privileges = self.server.parser.parse_privileges()

    def chat(self, msg, client):
        subcommand = msg[1].split(".")[2]
        if subcommand == "sm":  # send message
            msg.pop(0)
            mute_key = f"uid:{client.uid}:mute_until"
            mute_until = self.server.redis.get(mute_key)
            if mute_until is not None:
                mute_until = float(mute_until)
                if mute_until == 0 or mute_until > time.time():
                    if mute_until == 0:
                        remaining = "bezterminowo"
                    else:
                        remaining = f"{int(mute_until-time.time())} s"
                    client.send(["cp.ms.rsm", {"txt": "Wyciszenie potrwa "
                                                      f"jeszcze {remaining}."}])
                    return
                else:
                    self.server.redis.delete(mute_key)
            if msg[1]["msg"]["cid"]:
                for uid in msg[1]["msg"]["cid"].split("_"):
                    for tmp in self.server.online.copy():
                        if tmp.uid != uid:
                            continue
                        tmp.send(msg)
                        break
            else:
                if "msg" in msg[1]["msg"] and \
                   msg[1]["msg"]["msg"].startswith("!"):
                    return self.system_command(msg[1]["msg"]["msg"], client)
                for tmp in self.server.online.copy():
                    if tmp.room == msg[1]["rid"]:
                        tmp.send(msg)

    def moderation(self, msg, client):
        subcommand = msg[1].split(".")[2]
        if subcommand == "ar":  # access request
            user_data = self.server.get_user_data(client.uid)
            if user_data["role"] >= self.privileges[msg[2]["pvlg"]]:
                success = True
            else:
                success = False
            client.send(["cp.m.ar", {"pvlg": msg[2]["pvlg"],
                                     "sccss": success}])
        elif subcommand == "bu":
            uid = msg[2]["uid"]
            return self.ban_user(uid, client)

    def ban_user(self, uid, client):
        user_data = self.server.get_user_data(client.uid)
        if user_data["role"] < self.privileges["AVATAR_BAN"]:
            return
        uid = str(uid)
        if not uid.isdecimal() or uid == str(client.uid):
            return self.no_permission(client)
        uid_user_data = self.server.get_user_data(uid)
        if uid_user_data is None:
            client.send(["cp.ms.rsm", {"txt": "Nie znaleziono gracza."}])
            return
        if uid_user_data["role"] > 2:
            return
        redis = self.server.redis
        banned = redis.get(f"uid:{uid}:banned")
        if banned:
            client.send(["cp.ms.rsm", {
                "txt": f"Konto o UID {uid} jest już zablokowane przez "
                       f"administratora {banned}."}])
            return
        redis.delete(f"uid:{uid}:ban_expiry")
        redis.set(f"uid:{uid}:banned", client.uid)
        ban_time = int(time.time()*1000)
        redis.set(f"uid:{uid}:ban_time", ban_time)
        for tmp in self.server.online.copy():
            if tmp.uid != uid:
                continue
            tmp.send([10, "Konto zostało zablokowane",
                      {"duration": 999999, "banTime": ban_time,
                       "notes": "", "reviewerId": client.uid, "reasonId": 0,
                       "unbanType": "none", "leftTime": 0, "id": None,
                       "reviewState": 1, "userId": uid,
                       "moderatorId": client.uid}], type_=2)
            tmp.connection.shutdown(2)
            break
        client.send(["cp.ms.rsm", {"txt": f"UID {uid} został zablokowany."}])

    def unban_user(self, uid, client):
        user_data = self.server.get_user_data(client.uid)
        if user_data["role"] < self.privileges["AVATAR_BAN"]:
            return
        uid = str(uid)
        if not uid.isdecimal() or uid == str(client.uid):
            return self.no_permission(client)
        redis = self.server.redis
        banned = redis.get(f"uid:{uid}:banned")
        if not banned:
            client.send(["cp.ms.rsm", {
                "txt": f"UID {uid} nie ma aktywnej blokady."}])
            return
        redis.delete(f"uid:{uid}:banned")
        redis.delete(f"uid:{uid}:ban_time")
        redis.delete(f"uid:{uid}:ban_expiry")
        client.send(["cp.ms.rsm", {
            "txt": f"Blokada UID {uid} nałożona przez "
                   f"administratora {banned} została zdjęta."}])

    def message(self, msg, client):
        subcommand = msg[1].split(".")[2]
        if subcommand == "smm":  # send moderator message
            user_data = self.server.get_user_data(client.uid)
            if user_data["role"] < self.privileges["MESSAGE_TO_USER"]:
                return
            uid = msg[2]["rcpnts"]
            message = msg[2]["txt"]
            sccss = False
            for tmp in self.server.online.copy():
                if tmp.uid == uid:
                    tmp.send(["cp.ms.rmm", {"sndr": client.uid,
                                            "txt": message}])
                    sccss = True
                    break
            client.send(["cp.ms.smm", {"sccss": sccss}])

    def system_command(self, msg, client):
        command = msg[1:]
        if " " in command:
            command = command.split(" ")[0]
        if command == "ssm":
            return self.send_system_message(msg, client)
        elif command == "mute":
            return self.mute_player(msg, client)
        elif command == "ban":
            if len(msg.split()) != 2:
                return self.no_permission(client)
            uid = msg.split()[1]
            return self.ban_user(uid, client)
        elif command == "unban":
            if len(msg.split()) != 2:
                return self.no_permission(client)
            uid = msg.split()[1]
            return self.unban_user(uid, client)
        elif command == "unmute":
            if len(msg.split()) != 2:
                return self.no_permission(client)
            return self.unmute_player(msg.split()[1], client)
        elif command == "players":
            user_data = self.server.get_user_data(client.uid)
            if user_data["role"] < self.privileges["SEND_SYSTEM_MESSAGE"]:
                return self.no_permission(client)
            count = len(self.server.online)
            client.send(["cp.ms.rsm", {
                "txt": f"Gracze online: {count}"}])
            return
        elif command == "reset":
            if len(msg.split()) != 2:
                return self.no_permission(client)
            uid = msg.split()[1]
            return self.reset_user(uid, client)

    def send_system_message(self, msg, client):
        user_data = self.server.get_user_data(client.uid)
        if user_data["role"] < self.privileges["SEND_SYSTEM_MESSAGE"]:
            return self.no_permission(client)
        parts = msg.split(" ", 1)
        if len(parts) != 2 or not parts[1].strip():
            return self.no_permission(client)
        message = parts[1].strip()
        for tmp in self.server.online.copy():
            tmp.send(["cp.ms.rsm", {"txt": message}])

    def mute_player(self, msg, client):
        user_data = self.server.get_user_data(client.uid)
        if user_data["role"] < self.privileges["CHAT_BAN"]:
            return self.no_permission(client)
        parts = msg.split()
        if len(parts) != 3 or not parts[1].isdecimal() \
                or not parts[2].isdecimal():
            return self.no_permission(client)
        uid = parts[1]
        minutes = int(parts[2])
        if uid == str(client.uid):
            return self.no_permission(client)
        apprnc = self.server.get_appearance(uid)
        if not apprnc:
            client.send(["cp.ms.rsm", {"txt": "Nie znaleziono gracza."}])
            return
        target_data = self.server.get_user_data(uid)
        if target_data is None or target_data["role"] > 2:
            return self.no_permission(client)
        mute_until = 0 if minutes == 0 else int(time.time())+minutes*60
        self.server.redis.set(f"uid:{uid}:mute_until", mute_until)
        for tmp in self.server.online.copy():
            if tmp.uid != uid:
                continue
            tmp.send(["cp.m.bccu", {"bcu": {"notes": "", "reviewerId": "0",
                                            "mid": "0", "id": None,
                                            "reviewState": 1, "userId": uid,
                                            "mbt": int(time.time()*1000),
                                            "mbd": minutes,
                                            "categoryId": 14}}])
            break
        duration = "bezterminowo" if minutes == 0 else f"na {minutes} min."
        client.send(["cp.ms.rsm", {
            "txt": f"Gracz {apprnc['n']} został wyciszony {duration}"}])

    def unmute_player(self, uid, client):
        user_data = self.server.get_user_data(client.uid)
        if user_data["role"] < self.privileges["CHAT_BAN"]:
            return self.no_permission(client)
        if not uid.isdecimal() or uid == str(client.uid):
            return self.no_permission(client)
        mute_key = f"uid:{uid}:mute_until"
        if not self.server.redis.exists(mute_key):
            client.send(["cp.ms.rsm", {
                "txt": f"UID {uid} nie jest wyciszony."}])
            return
        self.server.redis.delete(mute_key)
        client.send(["cp.ms.rsm", {
            "txt": f"Wyciszenie UID {uid} zostało zdjęte."}])

    def reset_user(self, uid, client):
        user_data = self.server.get_user_data(client.uid)
        if user_data["role"] < 5:
            return self.no_permission(client)
        apprnc = self.server.get_appearance(uid)
        if not apprnc:
            client.send(["cp.ms.rsm", {"txt": "Konto jest już zresetowane."}])
            return
        for tmp in self.server.online.copy():
            if tmp.uid != uid:
                continue
            tmp.connection.shutdown(2)
            break
        utils.bot_common.reset_account(self.server.redis, uid)
        client.send(["cp.ms.rsm", {
            "txt": f"Konto {uid} zostało zresetowane."}])

    def no_permission(self, client):
        client.send(["cp.ms.rsm", {"txt": "Nie masz uprawnień do wykonania "
                                          "tego polecenia."}])
