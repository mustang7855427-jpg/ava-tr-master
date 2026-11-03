import logging


class Module():
    def __init__(self):
        self.commands = {}

    def on_message(self, msg, client):
        command = msg[1].split(".")[1]
        if command not in self.commands:
            logging.warning(f"Nie znaleziono polecenia {msg[1]}")
            return
        self.commands[command](msg, client)
