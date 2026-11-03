import errno
import logging
import ipaddress


def format_os_error(error):
    if isinstance(error, FileNotFoundError):
        if error.filename:
            return (
                "Nie znaleziono wymaganego pliku lub programu: "
                f"{error.filename}"
            )
        message = str(error)
        if message.startswith("Nie znaleziono"):
            return message
        return "Nie znaleziono wymaganego pliku lub programu."
    if isinstance(error, PermissionError):
        return "Brak uprawnień do wykonania tej czynności."
    if isinstance(error, ConnectionRefusedError):
        return (
            "Połączenie zostało odrzucone. "
            "Sprawdź, czy serwer jest uruchomiony."
        )
    if isinstance(error, TimeoutError):
        return "Przekroczono czas oczekiwania na odpowiedź."

    code = getattr(error, "winerror", None) or error.errno
    if code in (errno.EADDRINUSE, 10048):
        return "Port jest już zajęty przez inny program."
    if code in (errno.EACCES, errno.EPERM, 10013):
        return "Brak uprawnień do wykonania tej czynności."
    if code == 10061:
        return (
            "Połączenie zostało odrzucone. "
            "Sprawdź, czy serwer jest uruchomiony."
        )
    if code == 10060:
        return "Przekroczono czas oczekiwania na odpowiedź."
    return f"Wystąpił błąd systemowy (kod {code or 'nieznany'})."


def is_loopback_address(host):
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def get_prefix(location):
    prefix = location.split("_")[0]
    if prefix in ["cafe", "club", "street", "yard", "skiResort", "publicBeach",
                  "couturier", "ballroom", "park", "canyon", "salon",
                  "photoSalon", "weddingBeach", "iceRink", "podium", "garden",
                  "avaCitySchool", "islBeach", "avaBirthday2016Beach"]:
        return "o"
    elif prefix == "house":
        return "h"
    elif prefix == "work":
        return "w"
    else:
        logging.warning(f"Location prefix {prefix} not found")
        return "o"
