# main.py
import os
import asyncio
import time
from datetime import date
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiogram.utils.exceptions import RetryAfter, BotBlocked, ChatNotFound
from dotenv import load_dotenv

# === Baza ===
from database import (
    init_db, get_db_pool(), add_user, get_user_count, get_today_users, get_all_codes,
    add_kino_code, get_kino_by_code, delete_kino_code, get_code_stat,
    increment_stat, get_all_user_ids, get_last_anime_code
)

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
CHANNELS = ["@AniVerseClip", "@AniVerseUzDub"]
MAIN_CHANNELS = ["@anilord_ongoing", "@hoshino_dubbing", "@AniVerseClip"]
SERVER_CHANNEL = "@aniversebaza"  # .env dan ham olish mumkin
BOT_USERNAME = os.getenv("BOT_USERNAME")

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

ADMINS = {6486825926}

# === FSM Holatlar ===
class AddAnimeStates(StatesGroup):
    waiting_for_video = State()           # 1. Video
    waiting_for_name = State()            # 2. Nom
    waiting_for_parts = State()           # 3. Qismlar
    waiting_for_status = State()          # 4. Holati
    waiting_for_voice = State()           # 5. Ovoz
    waiting_for_genres = State()          # 6. Janrlar

class AdminStates(StatesGroup):
    waiting_for_anime_code = State()
    waiting_for_delete_code = State()

class UserStates(StatesGroup):
    waiting_for_admin_message = State()

class PostStates(StatesGroup):
    waiting_for_image = State()
    waiting_for_title = State()
    waiting_for_link = State()

# === Klaviaturalar ===
def admin_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("➕ Anime qo‘shish", "📤 Animeni yuborish")
    kb.add("❌ Kodni o‘chirish", "📊 Statistika")
    kb.add("📄 Kodlar ro‘yxati")
    return kb

def control_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("📡 Boshqarish"))
    return kb

async def send_admin_panel(message: types.Message):
    await message.answer("👮‍♂️ Admin panel", reply_markup=admin_keyboard())

# === Start ===
@dp.message_handler(commands=['start'])
async def start_handler(message: types.Message):
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
        await message.answer("👮‍♂️ Admin panel", reply_markup=admin_keyboard())
    else:
        kb = ReplyKeyboardMarkup(resize_keyboard=True).add(
            KeyboardButton("🎞 Barcha animelar"),
            KeyboardButton("✉️ Admin bilan bog‘lanish")
        )
        await message.answer("✨ Asosiy menyu", reply_markup=kb)

# === Anime qo'shish: avval video, keyin ma'lumotlar, so'ng serverga yuborish ===
@dp.message_handler(lambda m: m.text == "➕ Anime qo‘shish", user_id=ADMINS)
async def add_anime_start(message: types.Message):
    await AddAnimeStates.waiting_for_video.set()
    await message.answer("🎥 Avvalo videoni yuboring (60s gacha):", reply_markup=control_keyboard())

@dp.message_handler(content_types=["video"], state=AddAnimeStates.waiting_for_video)
async def handle_video(message: types.Message, state: FSMContext):
    video = message.video
    if video.duration > 60:
        await message.answer("❌ Video 60s dan oshmasligi kerak.")
        return

    await state.update_data(video_file_id=video.file_id)
    await AddAnimeStates.waiting_for_name.set()
    await message.answer("📝 Endi anime nomini kiriting:")

@dp.message_handler(state=AddAnimeStates.waiting_for_name)
async def anime_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await AddAnimeStates.waiting_for_parts.set()
    await message.answer("➤ Qismlar sonini kiriting:")

@dp.message_handler(state=AddAnimeStates.waiting_for_parts)
async def anime_parts(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Faqat raqam kiriting.")
        return
    await state.update_data(parts=int(message.text))
    await AddAnimeStates.waiting_for_status.set()
    await message.answer("➤ Holati (Tugallangan / Davom etmoqda):")

@dp.message_handler(state=AddAnimeStates.waiting_for_status)
async def anime_status(message: types.Message, state: FSMContext):
    await state.update_data(status=message.text)
    await AddAnimeStates.waiting_for_voice.set()
    await message.answer("➤ Kim ovoz bergan:")

@dp.message_handler(state=AddAnimeStates.waiting_for_voice)
async def anime_voice(message: types.Message, state: FSMContext):
    await state.update_data(voice=message.text)
    await AddAnimeStates.waiting_for_genres.set()
    await message.answer("➤ Janrlar (#drama #action):")

@dp.message_handler(state=AddAnimeStates.waiting_for_genres)
async def anime_genres(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Janrlar bo'sh bo'lishi mumkin emas.")
        return

    await state.update_data(genres=message.text)  # ✅ Saqlash

    data = await state.get_data()

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

    try:
        sent_msg = await bot.send_video(
            chat_id=SERVER_CHANNEL,
            video=data['video_file_id'],
            caption=caption
        )
        server_message_id = sent_msg.message_id
    except Exception as e:
        await message.answer(f"❌ Server kanalga yuborib bo'lmadi: {e}")
        await state.finish()
        return

    last_code = await get_last_anime_code()
    new_code = last_code + 1

    await add_kino_code(
        code=new_code,
        channel=SERVER_CHANNEL,
        message_id=server_message_id,
        post_count=data['parts'],
        title=data['name'],
        parts=data['parts'],
        status=data['status'],
        voice=data['voice'],
        genres=data['genres'].split(),
        video_file_id=data['video_file_id'],
        caption=caption
    )

    await message.answer(f"✅ Anime qo'shildi! Kod: `{new_code}`", reply_markup=admin_keyboard())
    await state.finish()
    
# === Animeni yuborish ===
@dp.message_handler(lambda m: m.text == "📤 Animeni yuborish", user_id=ADMINS)
async def send_anime_start(message: types.Message):
    await AdminStates.waiting_for_anime_code.set()
    await message.answer("📝 Kodni kiriting:", reply_markup=control_keyboard())

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

    successful = 0
    failed = 0
    for ch in MAIN_CHANNELS:
        try:
            await bot.copy_message(
                chat_id=ch,
                from_chat_id=anime['channel'],
                message_id=anime['message_id'],
                reply_markup=keyboard
            )
            successful += 1
        except Exception as e:
            print(f"Yuborishda xato {ch}: {e}")
            failed += 1

    await message.answer(f"✅ Yuborildi: {successful} ta, ❌ Xatolik: {failed}", reply_markup=admin_keyboard())
    await state.finish()

# === Kod o'chirish ===
@dp.message_handler(lambda m: m.text == "❌ Kodni o‘chirish", user_id=ADMINS)
async def del_code_start(message: types.Message):
    await AdminStates.waiting_for_delete_code.set()
    await message.answer("🗑 Kodni kiriting:", reply_markup=control_keyboard())

@dp.message_handler(state=AdminStates.waiting_for_delete_code)
async def del_code_finish(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Noto'g'ri format.")
        return
    code = int(message.text)
    deleted = await delete_kino_code(code)
    if deleted:
        await message.answer(f"✅ {code} o'chirildi.", reply_markup=admin_keyboard())
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
    text = "📄 *Barcha animelar:*\n"
    for c in codes:
        text += f"`{c['code']}` — {c['title']}\n"
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
