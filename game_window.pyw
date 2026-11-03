import configparser
import ipaddress
import socket
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from urllib.parse import urlsplit

import common


ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "web.ini"


def _local_web_address():
    config = configparser.ConfigParser()
    try:
        loaded_files = config.read(CONFIG_FILE, encoding="utf-8")
    except configparser.Error as error:
        raise ValueError("Plik web.ini ma nieprawidłowy format.") from error
    if not loaded_files:
        raise FileNotFoundError(f"Nie znaleziono konfiguracji: {CONFIG_FILE}")

    try:
        section = config["webserver"]
    except KeyError as error:
        raise ValueError(
            "W pliku web.ini brakuje sekcji [webserver]."
        ) from error
    try:
        address = urlsplit(section.get("web_address", ""))
        address.hostname
        address.port
    except ValueError as error:
        raise ValueError(
            "Adres serwera w pliku web.ini jest nieprawidłowy."
        ) from error
    if address.scheme not in ("http", "https") or not address.hostname:
        raise ValueError("web_address musi być lokalnym adresem HTTP lub HTTPS.")
    if address.hostname != "localhost":
        try:
            host_ip = ipaddress.ip_address(address.hostname)
        except ValueError as error:
            raise ValueError("Aplikacja otwiera wyłącznie lokalny serwer.") from error
        if not host_ip.is_loopback:
            raise ValueError("Aplikacja otwiera wyłącznie lokalny serwer.")
    return address


def _show_error(title, text):
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(title, text, parent=root)
    root.destroy()


def main():
    try:
        address = _local_web_address()
        port = address.port or (443 if address.scheme == "https" else 80)
        with socket.create_connection((address.hostname, port), timeout=3):
            pass
    except (OSError, ValueError) as error:
        description = (
            common.format_os_error(error)
            if isinstance(error, OSError) else str(error)
        )
        _show_error("Serwer AvA-TR jest niedostępny", description)
        return

    try:
        import webview
    except ImportError:
        _show_error(
            "Brak składnika aplikacji",
            "Nie zainstalowano pywebview. Uruchom ponownie "
            "Uruchom_serwer.bat, aby zainstalować wymagane pakiety.",
        )
        return

    try:
        webview.create_window(
            "AvA-TR — gra",
            address.geturl(),
            width=1280,
            height=800,
            min_size=(960, 600),
        )
        webview.start(gui="edgechromium")
    except (ImportError, OSError, RuntimeError) as error:
        if isinstance(error, OSError):
            detail = common.format_os_error(error)
        elif isinstance(error, ImportError):
            detail = "Brakuje wymaganej biblioteki lub składnika aplikacji."
        else:
            detail = "Składnik WebView2 nie uruchomił się poprawnie."
        _show_error(
            "Nie można otworzyć okna gry",
            "Nie udało się uruchomić Microsoft Edge WebView2. "
            "Sprawdź, czy środowisko WebView2 Runtime jest zainstalowane.\n\n"
            f"{detail}",
        )


if __name__ == "__main__":
    main()
