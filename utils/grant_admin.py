import os

import redis


def main():
    redis_url = os.environ.get(
        "REDIS_URL", "redis://127.0.0.1:6379/0")
    database = redis.Redis.from_url(
        redis_url, decode_responses=True, protocol=2)
    uid = input("Podaj UID istniejącego konta: ").strip()
    if not uid.isdecimal():
        raise ValueError("UID musi być liczbą całkowitą.")

    try:
        database.ping()
    except redis.RedisError as error:
        raise RuntimeError(
            "Nie można połączyć się z Redis. Sprawdź, czy usługa działa "
            "i czy REDIS_URL wskazuje właściwy adres."
        ) from error

    account_key = f"uid:{uid}:exp"
    if (not database.exists(account_key)
            or not database.exists(f"uid:{uid}:slvr")):
        raise ValueError(f"Nie znaleziono konta o UID {uid}.")

    current_role = database.get(f"uid:{uid}:role") or "0"
    print(f"Aktualna rola konta {uid}: {current_role}")
    if input(f"Wpisz ADMIN, aby nadać UID {uid} rolę 5: ").strip() != "ADMIN":
        print("Anulowano — konto nie zostało zmienione.")
        return

    database.set(f"uid:{uid}:role", 5)
    print(f"Nadano kontu UID {uid} najwyższą rangę Administrator (5).")


if __name__ == "__main__":
    main()
