# konkurs.py
import os
import json
import random
from typing import List
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.exceptions import TelegramAPIError

# ====== Muhit ======
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("API_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN (yoki API_TOKEN) .env da topilmadi")

BOT_USERNAME = os.getenv("BOT_USERNAME", "").lstrip("@")

CHANNELS: List[str] = [c.strip() for c in (os.getenv("CHANNEL_USERNAMES") or "").split(",") if c.strip()]
MAIN_CHANNELS: List[str] = [c.strip() for c in (os.getenv("MAIN_CHANNELS") or "").split(",") if c.strip()]

ADMINS = {6486825926, 7711928526}  # <-- o'zingizning admin ID larni qo'shing

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot)

# ====== Fayl saqlash ======
DATA_DIR = "data/konkurs"
CONTEST_FILE = os.path.join(DATA_DIR, "contest.json")

def init_konkurs():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CONTEST_FILE):
        save_konkurs_status({
            "active": False,
            "participants": [],
            "winners": [],
            "post_message_id": None,  # asosiy post id (ixtiyoriy)
        })

def get_konkurs_status():
    with open(CONTEST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_konkurs_status(data: dict):
    with open(CONTEST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ====== Yordamchi tugmalar ======
def join_button():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Ishtirok etish", callback_data="participate"))
    kb.add(InlineKeyboardButton("🔄 Tekshirish", callback_data="check_sub:0"))
    return kb

async def make_subscribe_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    for ch in CHANNELS:
        try:
            chat = await bot.get_chat(ch)
            invite_link = chat.invite_link or await bot.export_chat_invite_link(chat.id)
            title = chat.title or ch
            kb.add(InlineKeyboardButton(f"➕ {title}", url=invite_link))
        except Exception as e:
            print(f"[invite] {ch} -> {e}")
    kb.add(InlineKeyboardButton("✅ Tekshirish", callback_data="check_sub:0"))
    return kb

async def get_unsubscribed_channels(user_id: int) -> List[str]:
    not_sub = []
    for ch in CHANNELS:
        try:
            member = await bot.get_chat_member(ch, user_id)
            if member.status not in ("member", "administrator", "creator"):
                not_sub.append(ch)
        except Exception as e:
            print(f"[check_sub] {ch} -> {e}")
            # xatoda ham majburan ro'yxatga qo'shamiz
            not_sub.append(ch)
    return not_sub

# ====== Admin komandalar ======
@dp.message_handler(commands=["konkurs_start"])
async def konkurs_start_cmd(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    init_konkurs()
    st = get_konkurs_status()
    st["active"] = True
    st["participants"] = []
    st["winners"] = []
    save_konkurs_status(st)

    text = (
        "🎉 <b>Konkurs boshlandi!</b>\n\n"
        "Ishtirok etish uchun quyidagi tugmadan foydalaning.\n"
        "Eng avval majburiy kanallarga obuna bo‘ling."
    )

    # 1) Admin chatga chiqsin
    try:
        sent = await message.answer(text, reply_markup=join_button())
        st["post_message_id"] = sent.message_id
        save_konkurs_status(st)
    except TelegramAPIError as e:
        print(f"[start_admin_chat] -> {e}")

    # 2) Kanallarga yuborish (bot admin bo‘lsin)
    for ch in MAIN_CHANNELS:
        try:
            await bot.send_message(ch, text, reply_markup=join_button())
        except TelegramAPIError as e:
            print(f"[start_to_channel] {ch} -> {e}")

@dp.message_handler(commands=["konkurs_finish"])
async def konkurs_finish_cmd(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    st = get_konkurs_status()
    if not st.get("active"):
        await message.answer("ℹ️ Konkurs allaqachon yakunlangan yoki boshlanmagan.")
        return

    st["active"] = False
    save_konkurs_status(st)

    winners = st.get("winners", [])
    if winners:
        txt = "🏆 <b>Konkurs yakunlandi!</b>\n\nG‘oliblar:\n"
        txt += "\n".join([f"{['🥇','🥈','🥉'][i]} <code>{w}</code>" for i, w in enumerate(winners)])
    else:
        txt = "🏁 Konkurs yakunlandi! G‘olib aniqlanmadi."

    await message.answer(txt)

@dp.message_handler(commands=["konkurs_winner"])
async def konkurs_winner_cmd(message: types.Message):
    """Har chaqirilganda navbatdagi g‘olibni tanlaydi (1->2->3)."""
    if message.from_user.id not in ADMINS:
        return

    st = get_konkurs_status()
    if not st.get("active"):
        await message.answer("ℹ️ Konkurs faol emas.")
        return

    winners = st.get("winners", [])
    participants = st.get("participants", [])

    # 3 tadan ko‘p bo‘lmasin
    if len(winners) >= 3:
        await message.answer("✅ 3 ta g‘olib allaqachon tanlangan.")
        return

    # G'olib bo'lmagan ishtirokchilar ro'yxati
    candidates = [p for p in participants if p not in winners]
    if not candidates:
        await message.answer("❌ G‘olib tanlash uchun ishtirokchi yo‘q.")
        return

    winner = random.choice(candidates)
    winners.append(winner)
    st["winners"] = winners
    save_konkurs_status(st)

    place = len(winners)  # 1..3
    emoji = ["🥇", "🥈", "🥉"][place-1]
    await message.answer(f"{emoji} G‘olib: <code>{winner}</code>")

# ====== Ishtirokchi oqimi ======
@dp.callback_query_handler(lambda c: c.data == "participate")
async def participate_cb(callback: CallbackQuery):
    st = get_konkurs_status()
    if not st.get("active"):
        await callback.answer("Konkurs faol emas!", show_alert=True)
        return

    # obuna tekshirish
    unsub = await get_unsubscribed_channels(callback.from_user.id)
    if unsub:
        kb = await make_subscribe_keyboard()
        await callback.message.answer(
            "❗ Ishtirok etishdan oldin quyidagi kanallarga obuna bo‘ling:",
            reply_markup=kb
        )
        await callback.answer()
        return

    uid = callback.from_user.id
    if uid in st["participants"]:
        await callback.answer("Siz allaqachon ishtirokchisiz.", show_alert=True)
        return

    st["participants"].append(uid)
    save_konkurs_status(st)

    await callback.answer("✅ Ishtirok uchun rahmat!", show_alert=False)
    await callback.message.answer(f"✅ Ishtirokchi qo‘shildi: <code>{uid}</code>")

@dp.callback_query_handler(lambda c: c.data.startswith("check_sub:"))
async def recheck_sub_cb(callback: CallbackQuery):
    st = get_konkurs_status()
    if not st.get("active"):
        await callback.answer("Konkurs faol emas!", show_alert=True)
        return

    unsub = await get_unsubscribed_channels(callback.from_user.id)
    if unsub:
        kb = await make_subscribe_keyboard()
        txt = "❗ Hali ham barcha kanallarga obuna bo‘lmagansiz. Iltimos, barchasiga obuna bo‘ling:"
        await callback.message.edit_text(txt, reply_markup=kb)
        await callback.answer()
        return

    uid = callback.from_user.id
    if uid not in st["participants"]:
        st["participants"].append(uid)
        save_konkurs_status(st)

    await callback.message.edit_text("✅ Obuna tekshirildi va ishtirok qayd etildi.")
    await callback.answer()

# ====== Runner (ixtiyoriy test uchun) ======
# Agar alohida ishga tushirmoqchi bo'lsangiz, quyidagilarni saqlab qo'yishingiz mumkin:
# from aiogram.utils import executor
# async def on_startup(_): init_konkurs()
# if __name__ == "__main__":
#     executor.start_polling(dp, on_startup=on_startup)
