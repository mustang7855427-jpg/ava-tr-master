import configparser
import ipaddress
import os
import socket
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import urlsplit

import common
import psutil


ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "web.ini"
LOG_DIR = ROOT / "logs"
WEB_SCRIPT = ROOT / "web.py"
GAME_SCRIPT = ROOT / "server.py"


def _python_executable():
    app_python = ROOT / ".venv-app" / "Scripts" / "python.exe"
    if app_python.is_file():
        return app_python

    virtualenv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if virtualenv_python.is_file():
        return virtualenv_python

    current_python = Path(sys.executable)
    if current_python.name.lower() == "pythonw.exe":
        console_python = current_python.with_name("python.exe")
        if console_python.is_file():
            return console_python
    if current_python.is_file():
        return current_python
    raise FileNotFoundError(
        "Nie znaleziono Pythona. Zainstaluj zależności w .venv "
        "albo uruchom aplikację z Pythona."
    )


def _is_loopback(host):
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _load_local_config():
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
    for key in ("web_bind_host", "game_bind_host"):
        host = section.get(key, "127.0.0.1")
        if not _is_loopback(host):
            raise ValueError(
                f"{key}={host} nie jest adresem lokalnym. "
                "Menedżer uruchamia tylko konfigurację lokalną."
            )

    try:
        address = urlsplit(section.get("web_address", ""))
        address.hostname
    except ValueError as error:
        raise ValueError(
            "Adres web_address w pliku web.ini jest nieprawidłowy."
        ) from error
    if address.scheme not in ("http", "https") or not _is_loopback(
            address.hostname or ""):
        raise ValueError(
            "web_address musi wskazywać lokalny adres HTTP lub HTTPS."
        )
    return section, address.geturl()


def _redis_is_ready():
    try:
        with socket.create_connection(("127.0.0.1", 6379), timeout=1) as conn:
            conn.sendall(b"*1\r\n$4\r\nPING\r\n")
            with conn.makefile("rb") as response:
                return response.readline().startswith(b"+PONG")
    except OSError:
        return False


def _wait_for_service(process, name, host, port, timeout=10):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(
                f"Serwer {name} zakończył start (kod {return_code}). "
                f"Sprawdź log {LOG_DIR / ('web.log' if name == 'WWW' else 'game.log')}."
            )
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return
        except OSError as error:
            last_error = error
            time.sleep(0.2)

    last_error_description = (
        common.format_os_error(last_error) if last_error else "brak odpowiedzi")
    raise RuntimeError(
        f"Serwer {name} nie otworzył portu {host}:{port} w ciągu "
        f"{timeout} sekund. Sprawdź log "
        f"{LOG_DIR / ('web.log' if name == 'WWW' else 'game.log')}. "
        f"Ostatni błąd: {last_error_description}"
    )


def _process_runs_project_script(process, expected_script):
    try:
        command = process.cmdline()
        working_directory = Path(process.cwd()).resolve()
    except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
        return False

    if working_directory != ROOT.resolve():
        return False
    expected_name = expected_script.name.casefold()
    return any(Path(argument).name.casefold() == expected_name
               for argument in command[1:])


def _stop_stale_project_servers(section):
    web_port = section.getint("web_port", fallback=8080)
    listeners_by_port = {
        web_port: WEB_SCRIPT,
        8123: GAME_SCRIPT,
    }
    project_processes = {}
    unrelated_listeners = []

    try:
        connections = psutil.net_connections(kind="inet")
    except psutil.Error:
        raise RuntimeError(
            "Nie można bezpiecznie sprawdzić zajętych portów. "
            "Uruchom menedżer z uprawnieniami administratora lub zamknij "
            "serwer ręcznie."
        ) from error

    for connection in connections:
        if (connection.status != psutil.CONN_LISTEN
                or not connection.laddr
                or connection.laddr.port not in listeners_by_port):
            continue

        port = connection.laddr.port
        if connection.pid is None:
            unrelated_listeners.append(f"port {port} (nieznany proces)")
            continue

        try:
            process = psutil.Process(connection.pid)
            if _process_runs_project_script(
                    process, listeners_by_port[port]):
                project_processes[process.pid] = process
            else:
                unrelated_listeners.append(
                    f"port {port} (PID {process.pid}, {process.name()})")
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            unrelated_listeners.append(
                f"port {port} (PID {connection.pid}, brak dostępu)")

    if unrelated_listeners:
        raise RuntimeError(
            "Nie uruchamiam serwera: zajęty "
            + ", ".join(unrelated_listeners)
            + ". Nie zatrzymałem tych procesów, ponieważ nie należą "
            "jednoznacznie do tego projektu."
        )

    if not project_processes:
        return

    for process in project_processes.values():
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied as error:
            raise RuntimeError(
                f"Brak uprawnień do zatrzymania starego procesu AvA-TR "
                f"(PID {process.pid}). Uruchom launcher jako administrator."
            ) from error

    _, still_running = psutil.wait_procs(
        list(project_processes.values()), timeout=5)
    for process in still_running:
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied as error:
            raise RuntimeError(
                f"Brak uprawnień do zakończenia starego procesu AvA-TR "
                f"(PID {process.pid}). Uruchom launcher jako administrator."
            ) from error
    _, still_running = psutil.wait_procs(still_running, timeout=3)
    if still_running:
        pids = ", ".join(str(process.pid) for process in still_running)
        raise RuntimeError(
            "Nie udało się zatrzymać poprzednich procesów AvA-TR (PID "
            + pids + "). Zamknij je ręcznie i spróbuj ponownie."
        )


class ServerManager:
    def __init__(self, root):
        self.root = root
        self.processes = {}
        self.game_window_process = None
        self.last_failure = ""
        self.status = tk.StringVar(value="Serwer zatrzymany")

        root.title("AvA-TR — menedżer serwera lokalnego")
        root.geometry("480x250")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.close)

        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text="Lokalny menedżer serwera",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text=("Uruchamia serwer WWW i gry na tym komputerze. "
                  "Serwery działają niezależnie od VS Code. "
                  "Klient gry otwiera się w osobnym oknie aplikacji."),
            wraplength=435,
        ).pack(anchor="w", pady=(8, 14))
        ttk.Label(frame, textvariable=self.status).pack(anchor="w", pady=4)

        buttons = ttk.Frame(frame)
        buttons.pack(anchor="w", pady=12)
        self.start_button = ttk.Button(
            buttons, text="Uruchom serwer", command=self.start)
        self.start_button.pack(side="left", padx=(0, 8))
        self.stop_button = ttk.Button(
            buttons, text="Zatrzymaj serwer", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=(0, 8))
        ttk.Button(
            buttons, text="Otwórz grę", command=self.open_game_window).pack(
                side="left", padx=(0, 8))
        ttk.Button(
            buttons, text="Otwórz logi", command=self.open_logs).pack(
                side="left")

        self.refresh()
        root.after(500, self.start)

    def start(self):
        if self.processes:
            messagebox.showinfo("Serwer", "Serwer jest już uruchomiony.")
            return
        self.last_failure = ""
        try:
            section, _ = _load_local_config()
            if not _redis_is_ready():
                raise RuntimeError(
                    "Redis nie odpowiada na 127.0.0.1:6379. "
                    "Uruchom lokalną usługę Redis i spróbuj ponownie."
                )
            _stop_stale_project_servers(section)
            python = _python_executable()
            for script in (WEB_SCRIPT, GAME_SCRIPT):
                if not script.is_file():
                    raise FileNotFoundError(f"Nie znaleziono pliku: {script}")

            LOG_DIR.mkdir(exist_ok=True)
            web_port = section.getint("web_port", fallback=8080)
            web_host = section.get("web_bind_host", "127.0.0.1")
            game_host = section.get("game_bind_host", "127.0.0.1")
            self._start_process("WWW", python, WEB_SCRIPT)
            _wait_for_service(
                self.processes["WWW"], "WWW", web_host, web_port)
            self._start_process("Gra", python, GAME_SCRIPT)
            _wait_for_service(
                self.processes["Gra"], "gry", game_host, 8123)
            self.root.after(3000, self.open_game_window)
        except (OSError, RuntimeError, ValueError) as error:
            self.stop()
            description = (
                common.format_os_error(error)
                if isinstance(error, OSError) else str(error)
            )
            self.last_failure = description
            messagebox.showerror("Nie udało się uruchomić", description)
        self.refresh()

    def _start_process(self, name, python, script):
        process = subprocess.Popen(
            [str(python), str(script)],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.processes[name] = process

    def stop(self):
        for process in reversed(list(self.processes.values())):
            if process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    if process.poll() is None:
                        raise
                if process.poll() is None:
                    try:
                        process.wait(timeout=4)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=4)
        self.processes.clear()
        self.refresh()

    def refresh(self):
        active = {
            name: process for name, process in self.processes.items()
            if process.poll() is None
        }
        exited = [
            f"{name} (kod {process.returncode})"
            for name, process in self.processes.items()
            if process.poll() is not None
        ]
        if exited:
            self.last_failure = (
                "Proces zakończył działanie: " + ", ".join(exited)
                + ". Sprawdź logi."
            )
        self.processes = active
        if active:
            names = " i ".join(active)
            status = f"Uruchomione: {names}."
            if self.last_failure:
                status += " " + self.last_failure
            self.status.set(status)
        elif self.last_failure:
            self.status.set(self.last_failure)
        else:
            self.status.set("Serwer zatrzymany")
        self.start_button.configure(
            state="disabled" if active else "normal")
        self.stop_button.configure(
            state="normal" if active else "disabled")
        self.root.after(1000, self.refresh)

    def open_game_window(self):
        try:
            script = ROOT / "game_window.pyw"
            if not script.is_file():
                raise FileNotFoundError(f"Nie znaleziono pliku: {script}")
            if (self.game_window_process is not None
                    and self.game_window_process.poll() is None):
                messagebox.showinfo("Gra", "Okno gry jest już otwarte.")
                return

            python = _python_executable()
            pythonw = python.with_name("pythonw.exe")
            if not pythonw.is_file():
                raise FileNotFoundError(
                    f"Nie znaleziono programu do okna aplikacji: {pythonw}")
            self.game_window_process = subprocess.Popen(
                [str(pythonw), str(script)],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=(
                    getattr(subprocess, "DETACHED_PROCESS", 0)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                ),
            )
        except (OSError, ValueError) as error:
            description = (
                common.format_os_error(error)
                if isinstance(error, OSError) else str(error)
            )
            messagebox.showerror("Nie udało się otworzyć gry", description)

    def open_logs(self):
        try:
            LOG_DIR.mkdir(exist_ok=True)
            os.startfile(LOG_DIR)
        except OSError as error:
            messagebox.showerror(
                "Nie udało się otworzyć logów",
                common.format_os_error(error),
            )

    def close(self):
        if self.processes:
            choice = messagebox.askyesnocancel(
                "Zamykanie menedżera",
                "Czy zatrzymać serwery?\n\n"
                "Tak — zatrzymaj serwery i zamknij.\n"
                "Nie — pozostaw serwery uruchomione i zamknij menedżer.\n"
                "Anuluj — wróć do menedżera.",
            )
            if choice is None:
                return
            if choice:
                self.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    ServerManager(root)
    root.mainloop()


if __name__ == "__main__":
    main()
