import os
import json
import random
from aiogram import types

DATA_DIR = "data/konkurs"
CONTEST_FILE = os.path.join(DATA_DIR, "contest.json")

MAIN_CHANNELS = ["@your_channel_1", "@your_channel_2"]  # o'zingizniki
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))     # .env dan oling

def init_konkurs():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CONTEST_FILE):
        with open(CONTEST_FILE, "w", encoding="utf-8") as f:
            json.dump({"active": False, "participants": [], "winners": []}, f, indent=2)

def get_konkurs_status():
    with open(CONTEST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_konkurs_status(data):
    with open(CONTEST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def join_button():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Ishtirok etish", callback_data="participate"))
    return kb

async def start_konkurs(bot, chat_id):
    status = get_konkurs_status()
    status["active"] = True
    status["participants"] = []
    status["winners"] = []
    save_konkurs_status(status)

    message_text = "🎉 Konkurs boshlandi! Ishtirok etish uchun quyidagi tugmani bosing."
    # 1) Bosgan chatga yuborish
    try:
        await bot.send_message(chat_id=chat_id, text=message_text, reply_markup=join_button())
    except Exception as e:
        print(f"[XATOLIK] start_konkurs -> chatga yuborishda: {e}")

    # 2) Kanallarga ham yuborish (bot admin bo‘lishi kerak)
    for channel in MAIN_CHANNELS:
        try:
            await bot.send_message(chat_id=channel, text=message_text, reply_markup=join_button())
        except Exception as e:
            print(f"[XATOLIK] Kanalga yuborishda: {channel} -> {e}")

async def join_konkurs(callback: types.CallbackQuery):
    status = get_konkurs_status()
    if not status["active"]:
        await callback.answer("Konkurs faol emas!", show_alert=True)
        return

    user_id = callback.from_user.id
    if user_id in status["participants"]:
        await callback.answer("Siz allaqachon ishtirok etgansiz!", show_alert=True)
        return

    status["participants"].append(user_id)
    save_konkurs_status(status)

    await callback.answer("Ishtirok uchun rahmat!", show_alert=False)
    await callback.message.answer(f"✅ {user_id} ishtirokchi sifatida qo‘shildi")

async def select_winner(bot, admin_id):
    status = get_konkurs_status()
    if len(status["winners"]) >= 3:
        await bot.send_message(admin_id, "❌ Barcha g‘oliblar aniqlangan")
        return None

    candidates = [pid for pid in status["participants"] if pid not in status["winners"]]
    if not candidates:
        await bot.send_message(admin_id, "❌ Ishtirokchilar mavjud emas")
        return None

    winner = random.choice(candidates)
    status["winners"].append(winner)
    save_konkurs_status(status)

    place = len(status["winners"])
    emoji = ["🥇", "🥈", "🥉"][place-1]
    await bot.send_message(admin_id, f"{emoji} G‘olib: {winner}")

    if len(status["winners"]) == 3:
        await finish_konkurs(bot)

    return winner

async def finish_konkurs(bot):
    status = get_konkurs_status()
    if not status["active"]:
        return

    status["active"] = False
    save_konkurs_status(status)

    winners = "\n".join(f"{i+1}. {wid}" for i, wid in enumerate(status["winners"]))
    to_chat = ADMIN_CHAT_ID if ADMIN_CHAT_ID else None
    if to_chat:
        await bot.send_message(chat_id=to_chat, text=f"🏆 Konkurs yakunlandi!\nG‘oliblar:\n{winners}")
