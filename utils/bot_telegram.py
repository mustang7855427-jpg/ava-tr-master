import os
import redis
from aiogram import Bot, Dispatcher, executor, types
import bot_common

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError(
        "Set the TELEGRAM_BOT_TOKEN environment variable before starting the bot."
    )

issues_link = "https://www.youtube.com/channel/UCwtU6EBcXZVjd8g2-fzdh4A"

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)
r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)


async def require_private_chat(message: types.Message) -> bool:
    if message.chat.type != "private":
        await message.reply(
            "Ta komenda jest dostępna wyłącznie w prywatnej rozmowie z botem."
        )
        return False
    return True


@dp.message_handler(commands=["start", "pomoc", "yardım"])
async def send_welcome(message: types.Message):
    await message.reply("Witaj! Pomogę Ci korzystać z serwera Avatarii. "
                        "Nie udostępniaj nikomu danych logowania.\n"
                        "Dane konta: /konto\n"
                        "Zmiana hasła: /zmien_haslo\n"
                        "Reset konta: /resetuj_konto\n"
                        f"Informacje o aktualizacjach: {issues_link}")


@dp.message_handler(commands=["konto", "bilgilerim"])
async def password(message: types.Message):
    if not await require_private_chat(message):
        return
    passwd = r.get(f"tg:{message.from_user.id}")
    if passwd:
        uid = r.get(f"auth:{passwd}")
    else:
        uid, passwd = bot_common.new_account(r)
        r.set(f"tg:{message.from_user.id}", passwd)
    await message.reply(f"Identyfikator: {uid}\nHasło: {passwd}")


@dp.message_handler(commands=["zmien_haslo", "sifre_degistir"])
async def change_password(message: types.Message):
    if not await require_private_chat(message):
        return
    passwd = r.get(f"tg:{message.from_user.id}")
    if not passwd:
        return await message.reply("Konto nie zostało utworzone.")
    while True:
        new_passwd = bot_common.random_string()
        if r.get(f"auth:{new_passwd}"):
            continue
        break
    uid = r.get(f"auth:{passwd}")
    r.delete(f"auth:{passwd}")
    r.set(f"auth:{new_passwd}", uid)
    r.set(f"tg:{message.from_user.id}", new_passwd)
    await message.reply(f"Nowe hasło: {new_passwd}")


@dp.message_handler(commands=["resetuj_konto", "sifirla"])
async def reset(message: types.Message):
    if not await require_private_chat(message):
        return
    passwd = r.get(f"tg:{message.from_user.id}")
    if not passwd:
        return await message.reply("Konto nie zostało utworzone.")
    uid = r.get(f"auth:{passwd}")
    bot_common.reset_account(r, uid)
    await message.reply("Konto zostało zresetowane.")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
