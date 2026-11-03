from modules.base_module import Module
import const

class_name = "Billing"


class Billing(Module):
    prefix = "b"

    def __init__(self, server):
        self.server = server
        self.commands = {"chkprchs": self.check_purchase,
                         "bs": self.buy_silver}

    def check_purchase(self, msg, client):
        if not const.FREE_GOLD:
            return
        amount = int(msg[2]["prid"].split("pack")[1])*100
        user_data = self.server.get_user_data(client.uid)
        gold = user_data["gld"] + amount
        self.server.redis.set(f"uid:{client.uid}:gld", gold)
        res = {"gld": gold, "slvr": user_data["slvr"],
               "enrg": user_data["enrg"], "emd": user_data["emd"]}
        client.send(["ntf.res", {"res": res}])
        client.send(["b.ingld", {"ingld": amount}])

    def buy_silver(self, msg, client):
        user_data = self.server.get_user_data(client.uid)
        gold = int(msg[2]["gld"])
        if gold <= 0:
            return
        if not const.FREE_ITEMS and user_data["gld"] < gold:
            return
        new_gold = user_data["gld"]
        if not const.FREE_ITEMS:
            new_gold -= gold
            self.server.redis.set(f"uid:{client.uid}:gld", new_gold)
        self.server.redis.set(f"uid:{client.uid}:slvr",
                              user_data["slvr"] + gold * 100)
        res = {"gld": new_gold,
               "slvr": user_data["slvr"] + gold * 100,
               "enrg": user_data["enrg"], "emd": user_data["emd"]}
        client.send(["ntf.res", {"res": res}])
        client.send(["b.inslv", {"inslv": gold * 100}])
