# main.py
import os
import asyncio
from datetime import datetime, date
from aiogram import Bot, Dispatcher, types, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# === Baza ===
from database import (
    init_db, add_user, get_user_count, get_today_users, get_all_codes,
    add_kino_code, get_kino_by_code, delete_kino_code, get_code_stat,
    increment_stat, get_all_user_ids, get_last_anime_code
)

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")

CHANNELS = ["@AniVerseClip", "@AniVerseUzDub"]
MAIN_CHANNELS = ["@anilord_ongoing", "@hoshino_dubbing", "@AniVerseClip"]

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

ADMINS = {6486825926}

# === FSM Holatlar ===
class AdminStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_parts = State()
    waiting_for_status = State()
    waiting_for_voice = State()
    waiting_for_genres = State()
    waiting_for_video = State()
    waiting_for_anime_code = State()
    waiting_for_delete_code = State()

# === Admin klaviaturasi ===
def admin_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("➕ Anime qo‘shish", "📤 Animeni yuborish")
    kb.add("❌ Kodni o‘chirish", "📊 Statistika")
    kb.add("📄 Kodlar ro‘yxati")
    return kb

# === Start ===
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    user_id = message.from_user.id
    args = message.get_args().strip()

    await add_user(user_id)

    if args and args.isdigit():
        code = int(args)
        await increment_stat(code, "searched")
        anime = await get_kino_by_code(code)
        if anime:
            keyboard = InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔹 Tomosha qilish 🔹", url=f"https://t.me/{BOT_USERNAME}?start={code}")
            )
            await bot.send_video(
                user_id,
                video=anime['video_file_id'],
                caption=anime['caption'],
                reply_markup=keyboard
            )
        else:
            await message.answer("❌ Kod topilmadi.")
        return

    if user_id in ADMINS:
        await message.answer("👮‍♂️ Admin panel", reply_markup=admin_kb())
    else:
        kb = ReplyKeyboardMarkup(resize_keyboard=True).add(
            KeyboardButton("🎞 Barcha animelar"),
            KeyboardButton("✉️ Admin bilan bog‘lanish")
        )
        await message.answer("✨ Asosiy menyu", reply_markup=kb)

# === Anime qo'shish ===
@dp.message_handler(lambda m: m.text == "➕ Anime qo‘shish", user_id=ADMINS)
async def add_anime_start(message: types.Message):
    await AdminStates.waiting_for_name.set()
    await message.answer("📝 Anime nomini kiriting:")

@dp.message_handler(state=AdminStates.waiting_for_name)
async def anime_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await AdminStates.waiting_for_parts.set()
    await message.answer("➤ Qismlar soni (raqam):")

@dp.message_handler(state=AdminStates.waiting_for_parts)
async def anime_parts(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Faqat raqam kiriting.")
        return
    await state.update_data(parts=int(message.text))
    await AdminStates.waiting_for_status.set()
    await message.answer("➤ Holati (Tugallangan / Davom etmoqda):")

@dp.message_handler(state=AdminStates.waiting_for_status)
async def anime_status(message: types.Message, state: FSMContext):
    await state.update_data(status=message.text)
    await AdminStates.waiting_for_voice.set()
    await message.answer("➤ Kim ovoz bergan:")

@dp.message_handler(state=AdminStates.waiting_for_voice)
async def anime_voice(message: types.Message, state: FSMContext):
    await state.update_data(voice=message.text)
    await AdminStates.waiting_for_genres.set()
    await message.answer("➤ Janrlar (#drama #action):")

@dp.message_handler(state=AdminStates.waiting_for_genres)
async def anime_genres(message: types.Message, state: FSMContext):
    await state.update_data(genres=message.text)
    await AdminStates.waiting_for_video.set()
    await message.answer("🎥 60s gacha video yuboring:")

@dp.message_handler(content_types=["video"], state=AdminStates.waiting_for_video)
async def anime_video(message: types.Message, state: FSMContext):
    video = message.video
    if video.duration > 60:
        await message.answer("❌ Video 60s dan oshmasligi kerak.")
        return

    data = await state.get_data()
    last_code = await get_last_anime_code()
    new_code = last_code + 1

    caption = f"""{data['name']}
──────────────────────
➤ Mavsum: 1
➤ Holati: {data['status']}
➤ Ovoz berdi: {data['voice']}
➤ Qismi: {data['parts']}/qism yuklandi✅
➤ Kanal: @YourChannel
➤ Tili: Oʻzbekcha
➤ Yili: 2008
➤ Janri: {data['genres']}
──────────────────────"""

    await add_kino_code(
        code=new_code,
        channel="@YourChannel",
        message_id=0,
        post_count=0,
        title=data['name'],
        parts=data['parts'],
        status=data['status'],
        voice=data['voice'],
        genres=data['genres'].split(),
        video_file_id=video.file_id,
        caption=caption
    )

    await message.answer(f"✅ Anime qo‘shildi! Kod: `{new_code}`", reply_markup=admin_kb())
    await state.finish()

# === Animeni yuborish ===
@dp.message_handler(lambda m: m.text == "📤 Animeni yuborish", user_id=ADMINS)
async def send_anime_start(message: types.Message):
    await AdminStates.waiting_for_anime_code.set()
    await message.answer("📝 Kodni kiriting:")

@dp.message_handler(state=AdminStates.waiting_for_anime_code)
async def send_anime_handler(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Kod raqam bo'lishi kerak.")
        return
    code = int(message.text)
    anime = await get_kino_by_code(code)
    if not anime:
        await message.answer("❌ Kod topilmadi.")
        return

    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("🔹 Tomosha qilish 🔹", url=f"https://t.me/{BOT_USERNAME}?start={code}")
    )

    for ch in MAIN_CHANNELS:
        try:
            await bot.send_video(
                chat_id=ch,
                video=anime['video_file_id'],
                caption=anime['caption'],
                reply_markup=keyboard
            )
        except Exception as e:
            print(f"Yuborishda xato {ch}: {e}")

    await message.answer("✅ Kanallarga yuborildi.", reply_markup=admin_kb())
    await state.finish()

# === Kod o'chirish ===
@dp.message_handler(lambda m: m.text == "❌ Kodni o‘chirish", user_id=ADMINS)
async def del_code_start(message: types.Message):
    await AdminStates.waiting_for_delete_code.set()
    await message.answer("🗑 Kodni kiriting:")

@dp.message_handler(state=AdminStates.waiting_for_delete_code)
async def del_code_finish(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Noto'g'ri format.")
        return
    code = int(message.text)
    deleted = await delete_kino_code(code)
    if deleted:
        await message.answer(f"✅ {code} o'chirildi.", reply_markup=admin_kb())
    else:
        await message.answer("❌ Kod topilmadi.")
    await state.finish()

# === Barcha kodlar ===
@dp.message_handler(lambda m: m.text == "📄 Kodlar ro‘yxati", user_id=ADMINS)
async def list_codes(message: types.Message):
    codes = await get_all_codes()
    if not codes:
        await message.answer("❌ Hozircha animelar yo'q.")
        return
    text = "📄 Barcha animelar:\n"
"
    for c in codes:
        text += f"`{c['code']}` — {c['title']}
"
    await message.answer(text, parse_mode="Markdown")

# === Statistika ===
@dp.message_handler(lambda m: m.text == "📊 Statistika", user_id=ADMINS)
async def stats(message: types.Message):
    users = await get_user_count()
    today = await get_today_users()
    codes = await get_all_codes()
    await message.answer(f"""
📊 Statistika:
👥 Foydalanuvchilar: {users}
📅 Bugun: {today}
🎬 Animelar: {len(codes)}
""")

# === Boshlash ===
async def on_startup(dp):
    await init_db()
    print("✅ Bot ishga tushdi!")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
