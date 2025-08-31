# === IMPORTLAR ===
import io
import os
import time
from datetime import datetime, date
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.utils import executor
from keep_alive import keep_alive
from database import (
    init_db,
    add_user,
    get_user_count,
    add_kino_code,
    get_kino_by_code,
    get_all_codes,
    delete_kino_code,
    get_code_stat,
    increment_stat,
    get_all_user_ids,
    update_anime_code,
    get_today_users
)

# === YUKLAMALAR ===
load_dotenv()
keep_alive()

API_TOKEN = os.getenv("API_TOKEN")
CHANNELS = []
LINKS = []
MAIN_CHANNELS = []
MAIN_LINKS = []
BOT_USERNAME = os.getenv("BOT_USERNAME")

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

ADMINS = {6486825926, 7227368893}

# === KEYBOARDS ===
def admin_keyboard():
    """Asosiy admin paneli — 'Boshqarish' tugmasi MAVJUD EMAS"""
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("➕ Anime qo‘shish")
    kb.add("📊 Statistika", "📈 Kod statistikasi")
    kb.add("❌ Kodni o‘chirish", "📄 Kodlar ro‘yxati")
    kb.add("✏️ Kodni tahrirlash", "📤 Post qilish")
    kb.add("📢 Habar yuborish", "📘 Qo‘llanma")
    kb.add("➕ Admin qo‘shish", "📡 Kanal boshqaruvi")
    return kb

def control_keyboard():
    """Faol jarayonlarda foydalaniladigan 'Boshqarish' tugmasi"""
    return ReplyKeyboardMarkup(resize_keyboard=True).add("📡 Boshqarish")

async def send_admin_panel(message: types.Message):
    await message.answer("👮‍♂️ Admin panel:", reply_markup=admin_keyboard())

# === HOLATLAR ===
class AdminStates(StatesGroup):
    waiting_for_kino_data = State()
    waiting_for_delete_code = State()
    waiting_for_stat_code = State()
    waiting_for_broadcast_data = State()
    waiting_for_admin_id = State()

class AdminReplyStates(StatesGroup):
    waiting_for_reply_message = State()

class EditCode(StatesGroup):
    WaitingForOldCode = State()
    WaitingForNewCode = State()
    WaitingForNewTitle = State()

class UserStates(StatesGroup):
    waiting_for_admin_message = State()

class SearchStates(StatesGroup):
    waiting_for_anime_name = State()

class PostStates(StatesGroup):
    waiting_for_image = State()
    waiting_for_title = State()
    waiting_for_link = State()
    
class KanalStates(StatesGroup):
    waiting_for_channel_id = State()
    waiting_for_channel_link = State()


# === OBUNA TEKSHIRISH ===
async def get_unsubscribed_channels(user_id):
    unsubscribed = []
    for channel_id in CHANNELS:
        try:
            member = await bot.get_chat_member(channel_id, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                unsubscribed.append(channel_id)
        except Exception as e:
            print(f"❗ Obuna tekshirishda xatolik: {channel_id} -> {e}")
            unsubscribed.append(channel_id)
    return unsubscribed

async def is_user_subscribed(user_id):
    for channel_id in CHANNELS:
        try:
            member = await bot.get_chat_member(channel_id, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception as e:
            print(f"❗ Obuna holatini aniqlab bo‘lmadi: {channel_id} -> {e}")
            return False
    return True

# === OBUNA BO‘LMAGANLAR MARKUP ===
async def make_unsubscribed_markup(user_id, code):
    unsubscribed = await get_unsubscribed_channels(user_id)
    markup = InlineKeyboardMarkup(row_width=1)

    for idx, channel_id in enumerate(CHANNELS):
        if channel_id in unsubscribed:
            try:
                chat = await bot.get_chat(channel_id)
                channel_link = LINKS[idx]  # ID ga mos linkdan tugma yaratamiz
                markup.add(
                    InlineKeyboardButton(f"➕ {chat.title}", url=channel_link)
                )
            except Exception as e:
                print(f"❗ Kanal tugmasini yaratishda xatolik: {channel_id} -> {e}")

    # Tekshirish tugmasi
    markup.add(InlineKeyboardButton("✅ Tekshirish", callback_data=f"checksub:{code}"))
    return markup


# === /start HANDLER (to‘g‘rilangan) ===
@dp.message_handler(commands=['start'])
async def start_handler(message: types.Message):
    await add_user(message.from_user.id)
    args = message.get_args()

    if args and args.isdigit():
        code = args
        await increment_stat(code, "init")
        await increment_stat(code, "searched")

        unsubscribed = await get_unsubscribed_channels(message.from_user.id)
        if unsubscribed:
            markup = await make_unsubscribed_markup(message.from_user.id, code)
            await message.answer(
                "❗ Animeni olishdan oldin quyidagi homiy kanal(lar)ga obuna bo‘ling:",
                reply_markup=markup
            )
        else:
            await send_reklama_post(message.from_user.id, code)
            await increment_stat(code, "searched")
        return

    if message.from_user.id in ADMINS:
        await send_admin_panel(message)
    else:
        kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        kb.add(KeyboardButton("🎞 Barcha animelar"), KeyboardButton("✉️ Admin bilan bog‘lanish"))
        await message.answer("✨", reply_markup=kb)


# === TEKSHIRUV CALLBACK ===
@dp.callback_query_handler(lambda c: c.data.startswith("checksub:"))
async def check_subscription_callback(call: CallbackQuery):
    code = call.data.split(":")[1]
    unsubscribed = await get_unsubscribed_channels(call.from_user.id)

    if unsubscribed:
        markup = InlineKeyboardMarkup(row_width=1)
        for idx, channel_id in enumerate(CHANNELS):
            if channel_id in unsubscribed:
                try:
                    chat = await bot.get_chat(channel_id)
                    channel_link = LINKS[idx]
                    markup.add(
                        InlineKeyboardButton(f"➕ {chat.title}", url=channel_link)
                    )
                except Exception as e:
                    print(f"❗ Kanal tugmasini qayta yaratishda xatolik: {channel_id} -> {e}")

        markup.add(InlineKeyboardButton("✅ Yana tekshirish", callback_data=f"checksub:{code}"))
        await call.message.edit_text("❗ Obuna bo‘lmagan kanal(lar):", reply_markup=markup)
    else:
        await call.message.delete()
        await send_reklama_post(call.from_user.id, code)
        await increment_stat(code, "searched")


# === Barcha animelar ===
@dp.message_handler(lambda m: m.text == "🎞 Barcha animelar")
async def show_all_animes(message: types.Message):
    kodlar = await get_all_codes()
    if not kodlar:
        await message.answer("⛔️ Hozircha animelar yoʻq.")
        return

    kodlar = sorted(kodlar, key=lambda x: int(x["code"]))
    text = "📄 *Barcha animelar:*\n\n"
    for row in kodlar:
        text += f"`{row['code']}` – *{row['title']}*\n"
    await message.answer(text, parse_mode="Markdown")


# === Admin bilan bog‘lanish ===
@dp.message_handler(lambda m: m.text == "✉️ Admin bilan bog‘lanish")
async def contact_admin(message: types.Message):
    await UserStates.waiting_for_admin_message.set()
    await message.answer("✍️ Adminlarga yubormoqchi bo‘lgan xabaringizni yozing.\n\n❌ Bekor qilish uchun '❌ Bekor qilish' tugmasini bosing.", reply_markup=control_keyboard())

@dp.message_handler(state=UserStates.waiting_for_admin_message)
async def forward_to_admins(message: types.Message, state: FSMContext):
    if message.text == "📡 Boshqarish":
        await state.finish()
        await send_admin_panel(message)
        return

    await state.finish()
    user = message.from_user
    for admin_id in ADMINS:
        try:
            keyboard = InlineKeyboardMarkup().add(
                InlineKeyboardButton("✉️ Javob yozish", callback_data=f"reply_user:{user.id}")
            )
            await bot.send_message(
                admin_id,
                f"📩 <b>Yangi xabar:</b>\n\n"
                f"<b>👤 Foydalanuvchi:</b> {user.full_name} | <code>{user.id}</code>\n"
                f"<b>💬 Xabar:</b> {message.text}",
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except Exception as e:
            print(f"Adminga yuborishda xatolik: {e}")
    await message.answer("✅ Xabaringiz yuborildi. Tez orada admin siz bilan bog‘lanadi.")


# === Kanal boshqaruvi menyusi ===
@dp.message_handler(lambda m: m.text == "📡 Kanal boshqaruvi", user_id=ADMINS)
async def kanal_boshqaruvi(message: types.Message):
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("🔗 Majburiy obuna", callback_data="channel_type:sub"),
        InlineKeyboardButton("📌 Asosiy kanallar", callback_data="channel_type:main")
    )
    await message.answer("📡 Qaysi kanal turini boshqarasiz?", reply_markup=kb)


# === Kanal turi tanlanadi ===
@dp.callback_query_handler(lambda c: c.data.startswith("channel_type:"), user_id=ADMINS)
async def select_channel_type(callback: types.CallbackQuery, state: FSMContext):
    ctype = callback.data.split(":")[1]
    await state.update_data(channel_type=ctype)

    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("➕ Kanal qo‘shish", callback_data="action:add"),
        InlineKeyboardButton("📋 Kanal ro‘yxati", callback_data="action:list")
    )
    kb.add(
        InlineKeyboardButton("❌ Kanal o‘chirish", callback_data="action:delete"),
        InlineKeyboardButton("⬅️ Orqaga", callback_data="action:back")
    )

    text = "📡 Majburiy obuna kanallari menyusi:" if ctype == "sub" else "📌 Asosiy kanallar menyusi:"
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


# === Actionlarni boshqarish ===
@dp.callback_query_handler(lambda c: c.data.startswith("action:"), user_id=ADMINS)
async def channel_actions(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]
    data = await state.get_data()
    ctype = data.get("channel_type")

    if not ctype:
        await callback.answer("❗ Avval kanal turini tanlang.")
        return

    if action == "add":
        await KanalStates.waiting_for_channel_id.set()
        await callback.message.answer("🆔 Kanal ID yuboring (masalan: -1001234567890):")

    elif action == "list":
        if ctype == "sub":
            channels = zip(CHANNELS, LINKS)
            title = "📋 Majburiy obuna kanallari:\n\n"
        else:
            channels = zip(MAIN_CHANNELS, MAIN_LINKS)
            title = "📌 Asosiy kanallar:\n\n"

        if not list(channels):
            await callback.message.answer("📭 Hali kanal yo‘q.")
        else:
            text = title + "\n".join(
                f"{i}. 🆔 {cid}\n   🔗 {link}" for i, (cid, link) in enumerate(channels, 1)
            )
            await callback.message.answer(text)

    elif action == "delete":
        if ctype == "sub":
            channels = zip(CHANNELS, LINKS)
            prefix = "del_sub"
        else:
            channels = zip(MAIN_CHANNELS, MAIN_LINKS)
            prefix = "del_main"

        channels = list(channels)
        if not channels:
            await callback.message.answer("📭 Hali kanal yo‘q.")
            return

        kb = InlineKeyboardMarkup()
        for cid, link in channels:
            kb.add(InlineKeyboardButton(f"O‘chirish: {cid}", callback_data=f"{prefix}:{cid}"))
        await callback.message.answer("❌ Qaysi kanalni o‘chirmoqchisiz?", reply_markup=kb)

    elif action == "back":
        await kanal_boshqaruvi(callback.message)

    await callback.answer()


# === 1. Kanal ID qabul qilish ===
@dp.message_handler(state=KanalStates.waiting_for_channel_id, user_id=ADMINS)
async def add_channel_id(message: types.Message, state: FSMContext):
    try:
        channel_id = int(message.text.strip())
        await state.update_data(channel_id=channel_id)
        await KanalStates.waiting_for_channel_link.set()
        await message.answer("🔗 Endi kanal linkini yuboring (masalan: https://t.me/+invitehash):")
    except ValueError:
        await message.answer("❗ Faqat sonlardan iborat ID yuboring (masalan: -1001234567890).")


# === 2. Kanal linkini qabul qilish va saqlash ===
@dp.message_handler(state=KanalStates.waiting_for_channel_link, user_id=ADMINS)
async def add_channel_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ctype = data.get("channel_type")
    channel_id = data.get("channel_id")
    channel_link = message.text.strip()

    if not channel_link.startswith("http"):
        await message.answer("❗ To‘liq link yuboring (masalan: https://t.me/...)")
        return

    if ctype == "sub":
        if channel_id in CHANNELS:
            await message.answer("ℹ️ Bu kanal allaqachon qo‘shilgan.")
        else:
            CHANNELS.append(channel_id)
            LINKS.append(channel_link)
            await message.answer(f"✅ Kanal qo‘shildi!\n🆔 {channel_id}\n🔗 {channel_link}")
    else:
        if channel_id in MAIN_CHANNELS:
            await message.answer("ℹ️ Bu kanal allaqachon qo‘shilgan.")
        else:
            MAIN_CHANNELS.append(channel_id)
            MAIN_LINKS.append(channel_link)
            await message.answer(f"✅ Asosiy kanal qo‘shildi!\n🆔 {channel_id}\n🔗 {channel_link}")

    await state.finish()


# === Kanalni o‘chirish ===
@dp.callback_query_handler(lambda c: c.data.startswith("del_"), user_id=ADMINS)
async def delete_channel(callback: types.CallbackQuery):
    action, cid = callback.data.split(":")
    cid = int(cid)

    if action == "del_sub":
        if cid in CHANNELS:
            idx = CHANNELS.index(cid)
            CHANNELS.pop(idx)
            LINKS.pop(idx)
            await callback.message.answer(f"❌ Kanal o‘chirildi!\n🆔 {cid}")
    elif action == "del_main":
        if cid in MAIN_CHANNELS:
            idx = MAIN_CHANNELS.index(cid)
            MAIN_CHANNELS.pop(idx)
            MAIN_LINKS.pop(idx)
            await callback.message.answer(f"❌ Asosiy kanal o‘chirildi!\n🆔 {cid}")

    await callback.answer("O‘chirildi ✅")
    
# === Admin qo'shish ===
@dp.message_handler(lambda m: m.text == "➕ Admin qo‘shish", user_id=ADMINS)
async def add_admin_start(message: types.Message):
    await AdminStates.waiting_for_admin_id.set()
    await message.answer("🆔 Yangi adminning Telegram ID raqamini yuboring.", reply_markup=control_keyboard())

@dp.message_handler(state=AdminStates.waiting_for_admin_id, user_id=ADMINS)
async def add_admin_process(message: types.Message, state: FSMContext):
    if message.text == "📡 Boshqarish":
        await state.finish()
        await send_admin_panel(message)
        return

    await state.finish()
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("❗ Faqat raqam yuboring (Telegram user ID).", reply_markup=control_keyboard())
        return

    new_admin_id = int(text)
    if new_admin_id in ADMINS:
        await message.answer("ℹ️ Bu foydalanuvchi allaqachon admin.", reply_markup=control_keyboard())
        return

    ADMINS.add(new_admin_id)
    await message.answer(f"✅ <code>{new_admin_id}</code> admin sifatida qo‘shildi.", parse_mode="HTML", reply_markup=control_keyboard())
    try:
        await bot.send_message(new_admin_id, "✅ Siz botga admin sifatida qo‘shildingiz.")
    except:
        pass


# === Kod statistikasi ===
@dp.message_handler(lambda m: m.text == "📈 Kod statistikasi", user_id=ADMINS)
async def ask_stat_code(message: types.Message):
    await AdminStates.waiting_for_stat_code.set()
    await message.answer("📥 Kod raqamini yuboring:", reply_markup=control_keyboard())

@dp.message_handler(state=AdminStates.waiting_for_stat_code)
async def show_code_stat(message: types.Message, state: FSMContext):
    if message.text == "📡 Boshqarish":
        await state.finish()
        await send_admin_panel(message)
        return

    await state.finish()
    code = message.text.strip()
    if not code:
        await message.answer("❗ Kod yuboring.", reply_markup=control_keyboard())
        return
    stat = await get_code_stat(code)
    if not stat:
        await message.answer("❗ Bunday kod statistikasi topilmadi.", reply_markup=control_keyboard())
        return

    await message.answer(
        f"📊 <b>{code} statistikasi:</b>\n"
        f"🔍 Qidirilgan: <b>{stat['searched']}</b>\n"
        f"👁 Ko‘rilgan: <b>{stat['viewed']}</b>",
        parse_mode="HTML",
        reply_markup=control_keyboard()
    )


# === Kodni tahrirlash ===
@dp.message_handler(lambda m: m.text == "✏️ Kodni tahrirlash", user_id=ADMINS)
async def edit_code_start(message: types.Message):
    await EditCode.WaitingForOldCode.set()
    await message.answer("Qaysi kodni tahrirlashni xohlaysiz? (eski kodni yuboring)", reply_markup=control_keyboard())

@dp.message_handler(state=EditCode.WaitingForOldCode, user_id=ADMINS)
async def get_old_code(message: types.Message, state: FSMContext):
    if message.text == "📡 Boshqarish":
        await state.finish()
        await send_admin_panel(message)
        return

    code = message.text.strip()
    post = await get_kino_by_code(code)
    if not post:
        await message.answer("❌ Bunday kod topilmadi. Qaytadan urinib ko‘ring.", reply_markup=control_keyboard())
        return
    await state.update_data(old_code=code)
    await message.answer(f"🔎 Kod: {code}\n📌 Nomi: {post['title']}\n\nYangi kodni yuboring:", reply_markup=control_keyboard())
    await EditCode.WaitingForNewCode.set()

@dp.message_handler(state=EditCode.WaitingForNewCode, user_id=ADMINS)
async def get_new_code(message: types.Message, state: FSMContext):
    if message.text == "📡 Boshqarish":
        await state.finish()
        await send_admin_panel(message)
        return

    await state.update_data(new_code=message.text.strip())
    await message.answer("Yangi nomini yuboring:", reply_markup=control_keyboard())
    await EditCode.WaitingForNewTitle.set()

@dp.message_handler(state=EditCode.WaitingForNewTitle, user_id=ADMINS)
async def get_new_title(message: types.Message, state: FSMContext):
    if message.text == "📡 Boshqarish":
        await state.finish()
        await send_admin_panel(message)
        return

    data = await state.get_data()
    try:
        await update_anime_code(data['old_code'], data['new_code'], message.text.strip())
        await message.answer("✅ Kod va nom muvaffaqiyatli tahrirlandi.", reply_markup=admin_keyboard())
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi:\n{e}", reply_markup=admin_keyboard())
    finally:
        await state.finish()


# === Kodni o'chirish ===
@dp.message_handler(lambda m: m.text == "❌ Kodni o‘chirish", user_id=ADMINS)
async def ask_delete_code(message: types.Message):
    await AdminStates.waiting_for_delete_code.set()
    await message.answer("🗑 Qaysi kodni o‘chirmoqchisiz? Kodni yuboring.", reply_markup=control_keyboard())

@dp.message_handler(state=AdminStates.waiting_for_delete_code)
async def delete_code_handler(message: types.Message, state: FSMContext):
    if message.text == "📡 Boshqarish":
        await state.finish()
        await send_admin_panel(message)
        return

    await state.finish()
    code = message.text.strip()
    if not code.isdigit():
        await message.answer("❗ Noto‘g‘ri format. Kod raqamini yuboring.", reply_markup=control_keyboard())
        return
    deleted = await delete_kino_code(code)
    if deleted:
        await message.answer(f"✅ Kod {code} o‘chirildi.", reply_markup=admin_keyboard())
    else:
        await message.answer("❌ Kod topilmadi yoki o‘chirib bo‘lmadi.", reply_markup=admin_keyboard())


# === Post qilish ===
@dp.message_handler(lambda m: m.text == "📤 Post qilish", user_id=ADMINS)
async def start_post_process(message: types.Message):
    await PostStates.waiting_for_image.set()
    await message.answer("🖼 Iltimos, post uchun rasm yoki video yuboring (video 60 sekunddan oshmasin).", reply_markup=control_keyboard())

@dp.message_handler(content_types=[types.ContentType.PHOTO, types.ContentType.VIDEO], state=PostStates.waiting_for_image)
async def get_post_image_or_video(message: types.Message, state: FSMContext):
    if message.content_type == "text" and message.text == "📡 Boshqarish":
        await state.finish()
        await send_admin_panel(message)
        return

    if message.content_type == "photo":
        file_id = message.photo[-1].file_id
        await state.update_data(media=("photo", file_id))
    elif message.content_type == "video":
        duration = getattr(message.video, "duration", 0)
        if duration > 60:
            await message.answer("❌ Video 60 sekunddan oshmasligi kerak. Qaytadan yuboring.", reply_markup=control_keyboard())
            return
        file_id = message.video.file_id
        await state.update_data(media=("video", file_id))

    await PostStates.waiting_for_title.set()
    await message.answer("📌 Endi rasm/video ostiga yoziladigan nomni yuboring.", reply_markup=control_keyboard())

@dp.message_handler(state=PostStates.waiting_for_title)
async def get_post_title(message: types.Message, state: FSMContext):
    if message.text == "📡 Boshqarish":
        await state.finish()
        await send_admin_panel(message)
        return

    await state.update_data(title=message.text.strip())
    await PostStates.waiting_for_link.set()
    await message.answer("🔗 Yuklab olish uchun havolani yuboring.", reply_markup=control_keyboard())

@dp.message_handler(state=PostStates.waiting_for_link)
async def get_post_link(message: types.Message, state: FSMContext):
    if message.text == "📡 Boshqarish":
        await state.finish()
        await send_admin_panel(message)
        return

    data = await state.get_data()
    media = data.get("media")
    if not media:
        await message.answer("❗ Media topilmadi.", reply_markup=control_keyboard())
        await PostStates.waiting_for_image.set()
        return

    media_type, file_id = media
    title = data.get("title")
    link = message.text.strip()

    button = InlineKeyboardMarkup().add(InlineKeyboardButton("✨Yuklab olish✨", url=link))

    try:
        if media_type == "photo":
            await bot.send_photo(message.chat.id, file_id, caption=title, reply_markup=button)
        elif media_type == "video":
            await bot.send_video(message.chat.id, file_id, caption=title, reply_markup=button)
        await message.answer("✅ Post muvaffaqiyatli yuborildi.", reply_markup=admin_keyboard())
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}", reply_markup=admin_keyboard())
    finally:
        await state.finish()


# === Anime qo'shish ===
@dp.message_handler(lambda m: m.text == "➕ Anime qo‘shish", user_id=ADMINS)
async def add_start(message: types.Message):
    await AdminStates.waiting_for_kino_data.set()
    await message.answer("📝 Format: `KOD @kanal REKLAMA_ID POST_SONI ANIME_NOMI`\nMasalan: `91 @MyKino 4 12 naruto`", parse_mode="Markdown", reply_markup=control_keyboard())

@dp.message_handler(state=AdminStates.waiting_for_kino_data)
async def add_kino_handler(message: types.Message, state: FSMContext):
    if message.text == "📡 Boshqarish":
        await state.finish()
        await send_admin_panel(message)
        return

    rows = message.text.strip().split("\n")
    successful = 0
    failed = 0
    for row in rows:
        parts = row.strip().split()
        if len(parts) < 5:
            failed += 1
            continue
        code, server_channel, reklama_id, post_count = parts[:4]
        title = " ".join(parts[4:])
        if not (code.isdigit() and reklama_id.isdigit() and post_count.isdigit()):
            failed += 1
            continue
        reklama_id = int(reklama_id)
        post_count = int(post_count)
        await add_kino_code(code, server_channel, reklama_id + 1, post_count, title)
        download_btn = InlineKeyboardMarkup().add(
            InlineKeyboardButton("✨Yuklab olish✨", url=f"https://t.me/{BOT_USERNAME}?start={code}")
        )
        for ch in MAIN_CHANNELS:
            try:
                await bot.copy_message(ch, server_channel, reklama_id, reply_markup=download_btn)
                successful += 1
            except:
                failed += 1

    await message.answer(f"✅ Yangi kodlar qo‘shildi:\n\n✅ Muvaffaqiyatli: {successful}\n❌ Xatolik: {failed}", reply_markup=admin_keyboard())
    await state.finish()


# === Kodlar ro'yxati ===
@dp.message_handler(lambda m: m.text == "📄 Kodlar ro‘yxati")
async def show_all_animes(message: types.Message):
    kodlar = await get_all_codes()
    if not kodlar:
        await message.answer("Ba'zada hech qanday kodlar yo'q!")
        return
    kodlar = sorted(kodlar, key=lambda x: int(x["code"]))
    chunk_size = 100
    for i in range(0, len(kodlar), chunk_size):
        chunk = kodlar[i:i + chunk_size]
        text = "📄 *Barcha animelar:*\n\n"
        for row in chunk:
            text += f"`{row['code']}` – *{row['title']}*\n"
        await message.answer(text, parse_mode="Markdown")


# 📊 Statistika
@dp.message_handler(lambda m: m.text == "📊 Statistika")
async def stats(message: types.Message):
    # ⏱ Pingni o'lchash
    from database import db_pool
    async with db_pool.acquire() as conn:
        start = time.perf_counter()
        await conn.fetch("SELECT 1;")  # oddiy so'rov
        ping = (time.perf_counter() - start) * 1000  # ms ga aylantiramiz

    # 📂 Kodlar va foydalanuvchilar soni
    kodlar = await get_all_codes()
    foydalanuvchilar = await get_user_count()

    # 📅 Bugun qo'shilgan foydalanuvchilar
    today_users = await get_today_users()

    # 📊 Xabar
    text = (
        f"💡 O'rtacha yuklanish: {ping:.2f} ms\n\n"
        f"👥 Foydalanuvchilar: {foydalanuvchilar} ta\n\n"
        f"📂 Barcha yuklangan animelar: {len(kodlar)} ta\n\n"
        f"📅 Bugun qo'shilgan foydalanuvchilar: {today_users} ta"
    )
    await message.answer(text)



# === Orqaga tugmasi ===
@dp.message_handler(lambda m: m.text == "⬅️ Orqaga", user_id=ADMINS)
async def back_to_admin_menu(message: types.Message):
    await send_admin_panel(message)


# === Qo'llanma ===
@dp.message_handler(lambda m: m.text == "📘 Qo‘llanma")
async def qollanma(message: types.Message):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("📥 1. Anime qo‘shish", callback_data="help_add"),
        InlineKeyboardButton("📡 2. Kanal yaratish", callback_data="help_channel"),
        InlineKeyboardButton("🆔 3. Reklama ID olish", callback_data="help_id"),
        InlineKeyboardButton("🔁 4. Kod ishlashi", callback_data="help_code"),
        InlineKeyboardButton("❓ 5. Savol-javob", callback_data="help_faq")
    )
    await message.answer("📘 Qanday yordam kerak?", reply_markup=kb)


# === Qo'llanma sahifalari ===
HELP_TEXTS = {
    "help_add": ("📥 *Anime qo‘shish*\n\n`KOD @kanal REKLAMA_ID POST_SONI ANIME_NOMI`\n\nMisol: `91 @MyKino 4 12 Naruto`\n\n• *Kod* – foydalanuvchi yozadigan raqam\n• *@kanal* – server kanal username\n• *REKLAMA_ID* – post ID raqami (raqam)\n• *POST_SONI* – nechta qism borligi\n• *ANIME_NOMI* – ko‘rsatiladigan sarlavha\n\n📩 Endi formatda xabar yuboring:"),
    "help_channel": ("📡 *Kanal yaratish*\n\n1. 2 ta kanal yarating:\n   • *Server kanal* – post saqlanadi\n   • *Reklama kanal* – bot ulashadi\n\n2. Har ikkasiga botni admin qiling\n\n3. Kanalni public (@username) qiling"),
    "help_id": ("🆔 *Reklama ID olish*\n\n1. Server kanalga post joylang\n\n2. Post ustiga bosing → *Share* → *Copy link*\n\n3. Link oxiridagi sonni oling\n\nMisol: `t.me/MyKino/4` → ID = `4`"),
    "help_code": ("🔁 *Kod ishlashi*\n\n1. Foydalanuvchi kod yozadi (masalan: `91`)\n\n2. Obuna tekshiriladi → reklama post yuboriladi\n\n3. Tugmalar orqali qismlarni ochadi"),
    "help_faq": ("❓ *Tez-tez so‘raladigan savollar*\n\n• *Kodni qanday ulashaman?*\n  `https://t.me/{BOT_USERNAME}?start=91`\n\n• *Har safar yangi kanal kerakmi?*\n  – Yo‘q, bitta server kanal yetarli\n\n• *Kodni tahrirlash/o‘chirish mumkinmi?*\n  – Ha, admin menyuda ✏️ / ❌ tugmalari bor")
}

@dp.callback_query_handler(lambda c: c.data.startswith("help_"))
async def show_help_page(callback: types.CallbackQuery):
    key = callback.data
    text = HELP_TEXTS.get(key, "❌ Ma'lumot topilmadi.")
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Ortga", callback_data="back_help"))
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        await callback.message.delete()
    finally:
        await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "back_help")
async def back_to_qollanma(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("📥 1. Anime qo‘shish", callback_data="help_add"),
        InlineKeyboardButton("📡 2. Kanal yaratish", callback_data="help_channel"),
        InlineKeyboardButton("🆔 3. Reklama ID olish", callback_data="help_id"),
        InlineKeyboardButton("🔁 4. Kod ishlashi", callback_data="help_code"),
        InlineKeyboardButton("❓ 5. Savol-javob", callback_data="help_faq")
    )
    try:
        await callback.message.edit_text("📘 Qanday yordam kerak?", reply_markup=kb)
    except:
        await callback.message.answer("📘 Qanday yordam kerak?", reply_markup=kb)
        await callback.message.delete()
    finally:
        await callback.answer()


# === Habar yuborish ===
@dp.message_handler(lambda m: m.text == "📢 Habar yuborish", user_id=ADMINS)
async def ask_broadcast_info(message: types.Message):
    await AdminStates.waiting_for_broadcast_data.set()
    await message.answer("📨 Habar yuborish uchun format:\n`@kanal xabar_id`", parse_mode="Markdown", reply_markup=control_keyboard())

@dp.message_handler(state=AdminStates.waiting_for_broadcast_data)
async def send_forward_only(message: types.Message, state: FSMContext):
    if message.text == "📡 Boshqarish":
        await state.finish()
        await send_admin_panel(message)
        return

    await state.finish()
    parts = message.text.strip().split()
    if len(parts) != 2:
        await message.answer("❗ Format noto‘g‘ri. Masalan: `@kanalim 123`", reply_markup=control_keyboard())
        return
    channel_username, msg_id = parts
    if not msg_id.isdigit():
        await message.answer("❗ Xabar ID raqam bo‘lishi kerak.", reply_markup=control_keyboard())
        return
    msg_id = int(msg_id)
    users = await get_all_user_ids()
    success = 0
    fail = 0
    for user_id in users:
        try:
            await bot.forward_message(user_id, channel_username, msg_id)
            success += 1
        except Exception as e:
            print(f"Xatolik {user_id} uchun: {e}")
            fail += 1
    await message.answer(f"✅ Yuborildi: {success} ta\n❌ Xatolik: {fail} ta", reply_markup=admin_keyboard())


# === Kodni qidirish (raqam) ===
@dp.message_handler(lambda message: message.text.isdigit())
async def handle_code_message(message: types.Message):
    code = message.text
    if not await is_user_subscribed(message.from_user.id):
        markup = await make_unsubscribed_markup(message.from_user.id, code)
        await message.answer("❗ Anime olishdan oldin quyidagi kanal(lar)ga obuna bo‘ling:", reply_markup=markup)
    else:
        await increment_stat(code, "init")
        await increment_stat(code, "searched")
        await send_reklama_post(message.from_user.id, code)
        await increment_stat(code, "viewed")


# === Reklama post yuborish ===
async def send_reklama_post(user_id, code):
    data = await get_kino_by_code(code)
    if not data:
        await bot.send_message(user_id, "❌ Kod topilmadi.")
        return
    channel, reklama_id, post_count = data["channel"], data["message_id"], data["post_count"]
    buttons = [InlineKeyboardButton(str(i), callback_data=f"kino:{code}:{i}") for i in range(1, post_count + 1)]
    keyboard = InlineKeyboardMarkup(row_width=5).add(*buttons)
    try:
        await bot.copy_message(user_id, channel, reklama_id - 1, reply_markup=keyboard)
    except:
        await bot.send_message(user_id, "❌ Reklama postni yuborib bo‘lmadi.")


# === Kino tugmasi ===
@dp.callback_query_handler(lambda c: c.data.startswith("kino:"))
async def kino_button(callback: types.CallbackQuery):
    _, code, number = callback.data.split(":")
    number = int(number)
    result = await get_kino_by_code(code)
    if not result:
        await callback.message.answer("❌ Kod topilmadi.")
        return
    channel, base_id, post_count = result["channel"], result["message_id"], result["post_count"]
    if number > post_count:
        await callback.answer("❌ Bunday post yo‘q!", show_alert=True)
        return
    await bot.copy_message(callback.from_user.id, channel, base_id + number - 1)
    await callback.answer()

# === START ===
async def on_startup(dp):
    await init_db()
    print("✅ PostgreSQL bazaga ulandi!")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
