# === 📦 Standart kutubxonalar ===
import io
import os
import asyncio
import time
from datetime import datetime, date
# === 🔧 Konfiguratsiya va sozlamalar ===
from dotenv import load_dotenv

# === 🤖 Aiogram kutubxonalari ===
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils import executor
from aiogram.utils.exceptions import RetryAfter, BotBlocked, ChatNotFound
from aiogram.utils.markdown import escape_md

# === 📂 Loyihaga tegishli modullar ===
from konkurs import register_konkurs_handlers
from keep_alive import keep_alive
from database import init_db, add_user, get_user_count, add_kino_code, get_kino_by_code, get_all_codes, delete_kino_code, get_code_stat, increment_stat, get_all_user_ids, update_anime_code, get_today_users


load_dotenv()
keep_alive()

API_TOKEN = os.getenv("API_TOKEN")
CHANNELS = ["@AniVerseClip", "@AniVerseUzDub"]
MAIN_CHANNELS = ["@anilord_ongoing", "@hoshino_dubbing", "@AniVerseClip"]
BOT_USERNAME = os.getenv("BOT_USERNAME")

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

ADMINS = {6486825926}

class AdminStates(StatesGroup):
    waiting_for_kino_data = State()
    waiting_for_delete_code = State()
    waiting_for_stat_code = State()
    waiting_for_broadcast_data = State()
    waiting_for_admin_id = State()
    waiting_for_user_list = State()
    waiting_for_name = State()       # Anime nomi
    waiting_for_parts = State()      # Qismlar soni
    waiting_for_status = State()     # Tugallangan yoki davom etmoqda
    waiting_for_voice = State()      # Kim ovoz bergan
    waiting_for_genres = State()     # Janrlar (#action #drama ...)
    waiting_for_language = State()   # Tili (O‘zbekcha, Ruscha...)
    waiting_for_year = State()       # Yili (2008, 2015...)
    waiting_for_video = State()
    waiting_for_anime_code = State()

class AdminReplyStates(StatesGroup):
    waiting_for_reply_message = State()

class EditCode(StatesGroup):
    WaitingForOldCode = State()
    WaitingForNewCode = State()
    WaitingForNewTitle = State()
    
class UserStates(StatesGroup):
    waiting_for_admin_message = State()
    
class PostStates(StatesGroup):
    waiting_for_image = State()   # will accept photo or video
    waiting_for_title = State()
    waiting_for_link = State()
    
class KanalStates(StatesGroup):
    waiting_for_channel = State()

# === Klaviaturalar: Admin va Boshqarish ===
def admin_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ Anime qo‘shish")
    kb.add("📊 Statistika", "👮‍♂️ Adminlar")
    kb.add("📄 Kodlar ro‘yxati", "📈 Kod statistikasi", "✏️ Kodni tahrirlash")
    kb.add("🏆 Konkurs", "📤 Post qilish")
    kb.add("📢 Habar yuborish")
    kb.add("❌ Kodni o‘chirish", "📡 Kanal boshqaruvi")
    return kb

def control_keyboard():
    """Har bir state da ko'rsatiladigan '📡 Boshqarish' tugmasi"""
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("📡 Boshqarish"))
    return kb

async def send_admin_panel(message: types.Message):
    """Admin panelni chiqaruvchi yordamchi funktsiya"""
    await message.answer("📡 Siz admin panelga qaytdingiz.", reply_markup=admin_keyboard())

# === Start handler ===
@dp.message_handler(commands=['start'])
async def start_handler(message: types.Message):
    user_id = message.from_user.id
    args = (message.get_args() or "").strip()

    try:
        await add_user(user_id)
    except Exception as e:
        print(f"[add_user] {user_id} -> {e}")
    try:
        unsubscribed = await get_unsubscribed_channels(user_id) if 'get_unsubscribed_channels' in globals() else []
    except Exception as e:
        print(f"[subs_check] {user_id} -> {e}")
        unsubscribed = []

    if unsubscribed:
        # faqat obuna bo‘lmaganlarni chiqaramiz
        markup = await make_unsubscribed_markup(user_id, args)
        await message.answer(
            "❗ Botdan foydalanish uchun quyidagi kanal(lar)ga obuna bo‘ling:",
            reply_markup=markup
        )
        return
        
    if args and args.isdigit():
        code = args
        try:
            await increment_stat(code, "searched")
        except Exception as e:
            print(f"[increment_stat] {code} -> {e}")
        try:
            await send_reklama_post(user_id, code)
        except Exception as e:
            print(f"[send_reklama_post] {user_id}, code={code} -> {e}")
            await message.answer("⚠️ Postni yuborishda muammo bo‘ldi. Keyinroq urinib ko‘ring.")
        return
        
    try:
        if user_id in ADMINS:
            await message.answer(f"👮‍♂️ Admin panel:\n🆔 Sizning ID: <code>{user_id}</code>", reply_markup=admin_keyboard(), parse_mode="HTML")
        else:
            kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
            kb.add(
                KeyboardButton("🎞 Barcha animelar"),
                KeyboardButton("✉️ Admin bilan bog‘lanish")
            )
            await message.answer(
                f"✨",
                reply_markup=kb,
                parse_mode="HTML"
            )
    except Exception as e:
        print(f"[menu] {user_id} -> {e}")

# === Obuna tekshirish uchun yordamchi funksiyalar (agar mavjud bo'lsa) ===
async def make_subscribe_markup(code):
    keyboard = InlineKeyboardMarkup(row_width=1)
    for channel in CHANNELS:
        try:
            invite_link = await bot.create_chat_invite_link(channel.strip())
            keyboard.add(InlineKeyboardButton("📢 Obuna bo‘lish", url=invite_link.invite_link))
        except Exception as e:
            print(f"❌ Link yaratishda xatolik: {channel} -> {e}")
    keyboard.add(InlineKeyboardButton("✅ Tekshirish", callback_data=f"check_sub:{code}"))
    return keyboard

async def get_unsubscribed_channels(user_id):
    unsubscribed = []
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(channel.strip(), user_id)
            if member.status not in ["member", "administrator", "creator"]:
                unsubscribed.append(channel)
        except Exception as e:
            print(f"❗ Obuna tekshirishda xatolik: {channel} -> {e}")
            unsubscribed.append(channel)
    return unsubscribed

async def is_user_subscribed(user_id):
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(channel.strip(), user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception as e:
            print(f"❗ Obuna holatini aniqlab bo‘lmadi: {channel} -> {e}")
            return False
    return True
    
async def make_unsubscribed_markup(user_id: int, code: str):
    markup = InlineKeyboardMarkup(row_width=1)
    unsubscribed = await get_unsubscribed_channels(user_id)

    for ch in unsubscribed:
        try:
            chat = await bot.get_chat(ch.strip())
            invite_link = chat.invite_link or await bot.export_chat_invite_link(chat.id)
            title = chat.title or ch
            markup.add(InlineKeyboardButton(f"➕ {title}", url=invite_link))
        except Exception as e:
            print(f"❗ Kanal linkini olishda xatolik: {ch} -> {e}")

    markup.add(InlineKeyboardButton("✅ Tekshirish", callback_data=f"checksub:{code}"))
    return markup

# === Obuna tekshirish callback ===
@dp.callback_query_handler(lambda c: c.data.startswith("checksub:"))
async def check_subscription_callback(call: CallbackQuery):
    code = call.data.split(":")[1]
    unsubscribed = await get_unsubscribed_channels(call.from_user.id)

    if unsubscribed:
        markup = InlineKeyboardMarkup(row_width=1)
        for ch in unsubscribed:
            try:
                channel = await bot.get_chat(ch.strip())
                invite_link = channel.invite_link or (await bot.export_chat_invite_link(channel.id))
                markup.add(InlineKeyboardButton(f"➕ {channel.title}", url=invite_link))
            except Exception as e:
                print(f"❗ Kanalni olishda xatolik: {ch} -> {e}")
        markup.add(InlineKeyboardButton("✅ Yana tekshirish", callback_data=f"checksub:{code}"))
        await call.message.edit_text("❗ Obuna bo‘lmagan kanal(lar):", reply_markup=markup)
    else:
        await call.message.delete()
        await send_reklama_post(call.from_user.id, code)
        await increment_stat(code, "searched")

# === 📡 KANAL BOSHQARUVI ===
@dp.message_handler(lambda m: m.text == "📡 Kanal boshqaruvi", user_id=ADMINS)
async def kanal_boshqaruvi(message: types.Message):
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("🔗 Majburiy obuna", callback_data="channel_type:sub"),
        InlineKeyboardButton("📌 Asosiy kanallar", callback_data="channel_type:main")
    )
    await message.answer("📡 Qaysi kanal turini boshqarasiz?", reply_markup=kb)


# === TUR TANLASH ===
@dp.callback_query_handler(lambda c: c.data.startswith("channel_type:"), user_id=ADMINS)
async def select_channel_type(callback: types.CallbackQuery, state: FSMContext):
    ctype = callback.data.split(":")[1]

    # Tanlangan turini saqlaymiz
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

    if ctype == "sub":
        await callback.message.edit_text("📡 Majburiy obuna kanallari menyusi:", reply_markup=kb)
    else:
        await callback.message.edit_text("📌 Asosiy kanallar menyusi:", reply_markup=kb)

    await callback.answer()


# === ACTION TANLASH ===
@dp.callback_query_handler(lambda c: c.data.startswith("action:"), user_id=ADMINS)
async def channel_actions(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]
    data = await state.get_data()
    ctype = data.get("channel_type")

    if not ctype:
        await callback.answer("❗ Avval kanal turini tanlang.")
        return

    if action == "add":
        await KanalStates.waiting_for_channel.set()
        await callback.message.answer("📎 Kanal username yuboring (masalan: @mychannel):")

    elif action == "list":
        if ctype == "sub":
            if not CHANNELS:
                await callback.message.answer("📭 Majburiy obuna kanali yo‘q.")
            else:
                text = "📋 Majburiy obuna kanallari:\n\n"
                for i, ch in enumerate(CHANNELS, 1):
                    text += f"{i}. {ch}\n"
                await callback.message.answer(text)
        else:
            if not MAIN_CHANNELS:
                await callback.message.answer("📭 Asosiy kanal yo‘q.")
            else:
                text = "📌 Asosiy kanallar:\n\n"
                for i, ch in enumerate(MAIN_CHANNELS, 1):
                    text += f"{i}. {ch}\n"
                await callback.message.answer(text)

    elif action == "delete":
        kb = InlineKeyboardMarkup()
        if ctype == "sub":
            if not CHANNELS:
                await callback.message.answer("📭 Majburiy obuna kanali yo‘q.")
                return
            for ch in CHANNELS:
                kb.add(InlineKeyboardButton(f"O‘chirish: {ch}", callback_data=f"delch:{ch}"))
        else:
            if not MAIN_CHANNELS:
                await callback.message.answer("📭 Asosiy kanal yo‘q.")
                return
            for ch in MAIN_CHANNELS:
                kb.add(InlineKeyboardButton(f"O‘chirish: {ch}", callback_data=f"delmain:{ch}"))

        await callback.message.answer("❌ Qaysi kanalni o‘chirmoqchisiz?", reply_markup=kb)

    elif action == "back":
        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton("🔗 Majburiy obuna", callback_data="channel_type:sub"),
            InlineKeyboardButton("📌 Asosiy kanallar", callback_data="channel_type:main")
        )
        await callback.message.edit_text("📡 Qaysi kanal turini boshqarasiz?", reply_markup=kb)

    await callback.answer()


# === ➕ KANAL QO‘SHISH (STATE) ===
@dp.message_handler(state=KanalStates.waiting_for_channel, user_id=ADMINS)
async def add_channel_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ctype = data.get("channel_type")

    channel = message.text.strip()
    if not channel.startswith("@"):
        await message.answer("❗ Kanal @ bilan boshlanishi kerak.")
        return

    if ctype == "sub":
        if channel in CHANNELS:
            await message.answer("ℹ️ Bu kanal allaqachon ro‘yxatda bor.")
        else:
            CHANNELS.append(channel)
            await message.answer(f"✅ {channel} qo‘shildi (majburiy obuna).")
    else:
        if channel in MAIN_CHANNELS:
            await message.answer("ℹ️ Bu kanal allaqachon ro‘yxatda bor.")
        else:
            MAIN_CHANNELS.append(channel)
            await message.answer(f"✅ {channel} qo‘shildi (asosiy kanal).")

    await state.finish()


# === ❌ O‘CHIRISH HANDLERLARI ===
@dp.callback_query_handler(lambda c: c.data.startswith("delch:"), user_id=ADMINS)
async def delete_channel_confirm_sub(callback: types.CallbackQuery):
    channel = callback.data.split(":", 1)[1]
    if channel in CHANNELS:
        CHANNELS.remove(channel)
        await callback.message.edit_text(f"✅ {channel} (majburiy obuna) o‘chirildi.")
    else:
        await callback.message.edit_text("⚠️ Bu kanal topilmadi.")
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("delmain:"), user_id=ADMINS)
async def delete_channel_confirm_main(callback: types.CallbackQuery):
    channel = callback.data.split(":", 1)[1]
    if channel in MAIN_CHANNELS:
        MAIN_CHANNELS.remove(channel)
        await callback.message.edit_text(f"✅ {channel} (asosiy kanal) o‘chirildi.")
    else:
        await callback.message.edit_text("⚠️ Bu kanal topilmadi.")
    await callback.answer()



# === 📋 KANAL RO‘YXATI ===
@dp.message_handler(lambda m: m.text == "📋 Kanal ro‘yxati", user_id=ADMINS)
async def list_channels(message: types.Message):
    if not CHANNELS:
        await message.answer("📭 Hozircha hech qanday kanal yo‘q.")
        return
    text = "📋 Majburiy obuna kanallari:\n\n"
    for i, ch in enumerate(CHANNELS, 1):
        text += f"{i}. {ch}\n"
    await message.answer(text)


# === ❌ KANAL O‘CHIRISH ===
@dp.message_handler(lambda m: m.text == "❌ Kanal o‘chirish", user_id=ADMINS)
async def delete_channel_start(message: types.Message):
    if not CHANNELS:
        await message.answer("📭 Hozircha hech qanday kanal yo‘q.")
        return
    kb = InlineKeyboardMarkup()
    for ch in CHANNELS:
        kb.add(InlineKeyboardButton(f"O‘chirish: {ch}", callback_data=f"delch:{ch}"))
    await message.answer("❌ Qaysi kanalni o‘chirmoqchisiz?", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("delch:"), user_id=ADMINS)
async def delete_channel_confirm(callback: types.CallbackQuery):
    channel = callback.data.split(":", 1)[1]
    if channel in CHANNELS:
        CHANNELS.remove(channel)
        await callback.message.edit_text(f"✅ {channel} o‘chirildi.")
    else:
        await callback.message.edit_text("⚠️ Bu kanal topilmadi.")
    await callback.answer()
# ⬅️ Orqaga qaytish (Admin panelga)
@dp.message_handler(lambda m: m.text == "⬅️ Orqaga", user_id=ADMINS)
async def back_to_admin_menu(message: types.Message):
    await message.answer("🔙 Admin menyu:", reply_markup=admin_keyboard())

# === 🎞 Barcha animelar tugmasi
@dp.message_handler(lambda m: m.text == "🎞 Barcha animelar")
async def show_all_animes(message: types.Message):
    kodlar = await get_all_codes()
    if not kodlar:
        await message.answer("⛔️ Hozircha animelar yoʻq.")
        return

    # Kodlarni raqam bo‘yicha tartiblash
    kodlar = sorted(kodlar, key=lambda x: int(x["code"]))

    # Har 100 tadan bo‘lib yuborish
    chunk_size = 100
    for i in range(0, len(kodlar), chunk_size):
        chunk = kodlar[i:i + chunk_size]
        text = "📄 *Barcha animelar:*\n\n"
        for row in chunk:
            text += f"`{row['code']}` – *{row['title']}*\n"

        await message.answer(text, parse_mode="Markdown")


# === Admin bilan bog'lanish (foydalanuvchi) ===
@dp.message_handler(lambda m: m.text == "✉️ Admin bilan bog‘lanish")
async def contact_admin(message: types.Message):
    await UserStates.waiting_for_admin_message.set()
    await message.answer("✍️ Adminlarga yubormoqchi bo‘lgan xabaringizni yozing.\n\n📡 Bekor qilish uchun '📡 Boshqarish' tugmasini bosing.", reply_markup=control_keyboard())

@dp.message_handler(state=UserStates.waiting_for_admin_message)
async def forward_to_admins(message: types.Message, state: FSMContext):
    # Agar foydalanuvchi boshqarish tugmasini bossachi
    if message.text == "📡 Boshqarish":
        await state.finish()
        await message.answer("📡 Amal to‘xtatildi. Bosh menyuga qaytdingiz.")
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

@dp.callback_query_handler(lambda c: c.data.startswith("reply_user:"), user_id=ADMINS)
async def start_admin_reply(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    await state.update_data(reply_user_id=user_id)
    await AdminReplyStates.waiting_for_reply_message.set()
    await callback.message.answer("✍️ Endi foydalanuvchiga yubormoqchi bo‘lgan xabaringizni yozing.", reply_markup=control_keyboard())
    await callback.answer()

@dp.message_handler(state=AdminReplyStates.waiting_for_reply_message, user_id=ADMINS)
async def send_admin_reply(message: types.Message, state: FSMContext):
    # agar boshqarish bosilgan bo'lsa
    if message.text == "📡 Boshqarish":
        await state.finish()
        await send_admin_panel(message)
        return

    data = await state.get_data()
    user_id = data.get("reply_user_id")

    try:
        await bot.send_message(user_id, f"✉️ Admindan javob:\n\n{message.text}")
        await message.answer("✅ Javob foydalanuvchiga yuborildi.")
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")
    finally:
        await state.finish()

# === 📡 Adminlar boshqaruvi ===
@dp.message_handler(lambda m: m.text == "👮‍♂️ Adminlar", user_id=ADMINS)
async def manage_admins(message: types.Message):
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("➕ Yangi admin qo‘shish", callback_data="admin_action:add"),
        InlineKeyboardButton("📋 Adminlar ro‘yxati", callback_data="admin_action:list")
    )
    kb.add(InlineKeyboardButton("❌ Admin o‘chirish", callback_data="admin_action:delete"))
    kb.add(InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_action:back"))
    await message.answer("👮‍♂️ Adminlar boshqaruvi:", reply_markup=kb)


# === Adminlar callback handleri ===
@dp.callback_query_handler(lambda c: c.data.startswith("admin_action:"), user_id=ADMINS)
async def admin_actions(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]

    if action == "add":
        await AdminStates.waiting_for_admin_id.set()
        await callback.message.answer("🆔 Yangi adminning Telegram ID raqamini yuboring.", reply_markup=control_keyboard())

    elif action == "list":
        if not ADMINS:
            await callback.message.answer("📭 Hozircha admin yo‘q.")
        else:
            text = "📋 Adminlar ro‘yxati:\n\n"
            for i, admin_id in enumerate(ADMINS, 1):
                text += f"{i}. <code>{admin_id}</code>\n"
            await callback.message.answer(text, parse_mode="HTML")

    elif action == "delete":
        if not ADMINS:
            await callback.message.answer("📭 Hozircha admin yo‘q.")
            await callback.answer()
            return

        kb = InlineKeyboardMarkup()
        for admin_id in ADMINS:
            # Siz o'zingizni o'chirib bo'lmaydi
            if admin_id == callback.from_user.id:
                continue
            kb.add(InlineKeyboardButton(f"❌ O‘chirish: {admin_id}", callback_data=f"deladmin:{admin_id}"))

        if not kb.inline_keyboard:
            await callback.message.answer("ℹ️ Sizni o‘chiradigan admin yo‘q.")
        else:
            await callback.message.answer("❌ Qaysi adminni o‘chirmoqchisiz?", reply_markup=kb)

    elif action == "back":
        await callback.message.edit_text("🔙 Admin panelga qaytdingiz.", reply_markup=admin_keyboard())

    await callback.answer()


# === Adminni o‘chirish callback handleri ===
@dp.callback_query_handler(lambda c: c.data.startswith("deladmin:"), user_id=ADMINS)
async def delete_admin_confirm(callback: types.CallbackQuery):
    admin_id = int(callback.data.split(":")[1])
    # Sizni o'chirib bo'lmaydi
    if admin_id == callback.from_user.id:
        await callback.answer("❌ Sizni o‘chirib bo‘lmaydi!", show_alert=True)
        return

    if admin_id in ADMINS:
        ADMINS.remove(admin_id)
        await callback.message.edit_text(f"✅ Admin {admin_id} o‘chirildi.")
    else:
        await callback.message.edit_text("⚠️ Admin topilmadi.")

    await callback.answer()



# === Admin o‘chirish callback ===
@dp.callback_query_handler(lambda c: c.data.startswith("deladmin:"), user_id=ADMINS)
async def delete_admin(callback: types.CallbackQuery):
    admin_id = int(callback.data.split(":", 1)[1])
    if admin_id in ADMINS:
        ADMINS.remove(admin_id)
        await callback.message.edit_text(f"✅ Admin <code>{admin_id}</code> o‘chirildi.", parse_mode="HTML")
    else:
        await callback.message.edit_text("⚠️ Bu admin topilmadi.")
    await callback.answer()


# === Admin qo‘shish handleri ===
@dp.message_handler(state=AdminStates.waiting_for_admin_id, user_id=ADMINS)
async def add_admin_process(message: types.Message, state: FSMContext):
    if message.text == "📡 Boshqarish":
        await state.finish()
        await send_admin_panel(message)
        return

    await state.finish()
    text = message.text.strip()

    if not text.isdigit():
        await message.answer("❗ Faqat raqam yuboring (Telegram user ID).")
        return

    new_admin_id = int(text)
    if new_admin_id in ADMINS:
        await message.answer("ℹ️ Bu foydalanuvchi allaqachon admin.")
        return

    ADMINS.add(new_admin_id)
    await message.answer(f"✅ <code>{new_admin_id}</code> admin sifatida qo‘shildi.", parse_mode="HTML", reply_markup=admin_keyboard())

    try:
        await bot.send_message(new_admin_id, "✅ Siz botga admin sifatida qo‘shildingiz.")
    except:
        await message.answer("⚠️ Yangi adminga habar yuborib bo‘lmadi.")

# === Kod statistikasi
@dp.message_handler(lambda m: m.text == "📈 Kod statistikasi")
async def ask_stat_code(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("📥 Kod raqamini yuboring:", reply_markup=control_keyboard())
    await AdminStates.waiting_for_stat_code.set()

@dp.message_handler(state=AdminStates.waiting_for_stat_code)
async def show_code_stat(message: types.Message, state: FSMContext):
    if message.text == "📡 Boshqarish":
        await state.finish()
        await send_admin_panel(message)
        return

    await state.finish()
    code = message.text.strip()
    if not code:
        await message.answer("❗ Kod yuboring.")
        return
    stat = await get_code_stat(code)
    if not stat:
        await message.answer("❗ Bunday kod statistikasi topilmadi.")
        return

    await message.answer(
        f"📊 <b>{code} statistikasi:</b>\n"
        f"🔍 Qidirilgan: <b>{stat.get('searched',0)}</b>\n",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )

# --- Kodni tahrirlash boshlash ---
@dp.message_handler(lambda message: message.text == "✏️ Kodni tahrirlash", user_id=ADMINS)
async def edit_code_start(message: types.Message):
    await message.answer("Qaysi kodni tahrirlashni xohlaysiz? (eski kodni yuboring)", reply_markup=control_keyboard())
    await EditCode.WaitingForOldCode.set()

# --- Eski kodni qabul qilish ---
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

# --- Yangi kodni olish ---
@dp.message_handler(state=EditCode.WaitingForNewCode, user_id=ADMINS)
async def get_new_code(message: types.Message, state: FSMContext):
    if message.text == "📡 Boshqarish":
        await state.finish()
        await send_admin_panel(message)
        return

    await state.update_data(new_code=message.text.strip())

    await message.answer("Yangi nomini yuboring:", reply_markup=control_keyboard())
    await EditCode.WaitingForNewTitle.set()

# --- Yangi nomni olish va yangilash ---
@dp.message_handler(state=EditCode.WaitingForNewTitle, user_id=ADMINS)
async def get_new_title(message: types.Message, state: FSMContext):
    if message.text == "📡 Boshqarish":
        await state.finish()
        await send_admin_panel(message)
        return

    data = await state.get_data()
    try:
        await update_anime_code(
            data['old_code'],
            data['new_code'],
            message.text.strip()
        )
        await message.answer("✅ Kod va nom muvaffaqiyatli tahrirlandi.", reply_markup=admin_keyboard())
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi:\n{e}", reply_markup=admin_keyboard())
    finally:
        await state.finish()

# === Oddiy raqam yuborilganda
@dp.message_handler(lambda message: message.text.isdigit())
async def handle_code_message(message: types.Message):
    code = message.text
    if not await is_user_subscribed(message.from_user.id):
        markup = await make_subscribe_markup(code)
        await message.answer("❗ Kino olishdan oldin quyidagi kanal(lar)ga obuna bo‘ling:", reply_markup=markup)
    else:
        await increment_stat(code, "init")
        await increment_stat(code, "searched")
        await send_reklama_post(message.from_user.id, code)

@dp.message_handler(lambda m: m.text == "📢 Habar yuborish")
async def ask_broadcast_info(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
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
        await message.answer("❗ Format noto‘g‘ri. Masalan: `@kanalim 123`", reply_markup=admin_keyboard())
        return

    channel_username, msg_id = parts
    if not msg_id.isdigit():
        await message.answer("❗ Xabar ID raqam bo‘lishi kerak.", reply_markup=admin_keyboard())
        return

    msg_id = int(msg_id)
    users = await get_all_user_ids()

    success = 0
    fail = 0

    for i, user_id in enumerate(users, start=1):
        try:
            await bot.forward_message(
                chat_id=user_id,
                from_chat_id=channel_username,
                message_id=msg_id
            )
            success += 1
        except RetryAfter as e:
            print(f"Flood limit. Kutyapmiz {e.timeout} sekund...")
            await asyncio.sleep(e.timeout)
            continue
        except (BotBlocked, ChatNotFound):
            fail += 1
        except Exception as e:
            print(f"Xatolik {user_id}: {e}")
            fail += 1

        # Har 25 xabardan keyin 1 sekund kutish
        if i % 25 == 0:
            await asyncio.sleep(1)

    await message.answer(f"✅ Yuborildi: {success} ta\n❌ Xatolik: {fail} ta", reply_markup=admin_keyboard())

# === Reklama postni yuborish
async def send_reklama_post(user_id, code):
    data = await get_kino_by_code(code)
    if not data:
        await bot.send_message(user_id, "❌ Kod topilmadi.")
        return

    channel, reklama_id, post_count = data["channel"], data["message_id"], data["post_count"]

    buttons = [InlineKeyboardButton(str(i), callback_data=f"kino:{code}:{i}") for i in range(1, post_count + 1)]
    keyboard = InlineKeyboardMarkup(row_width=5)
    keyboard.add(*buttons)

    try:
        await bot.copy_message(user_id, channel, reklama_id - 1, reply_markup=keyboard)
    except Exception as e:
        print(f"[send_reklama_post] {e}")
        await bot.send_message(user_id, "❌ Reklama postni yuborib bo‘lmadi.")

# === Tugma orqali kino yuborish
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

# === ➕ Anime qo‘shish bosqichlari ===
@dp.message_handler(lambda m: m.text == "➕ Anime qo‘shish")
async def add_anime_start(message: types.Message):
    if message.from_user.id in ADMINS:
        await AdminStates.waiting_for_name.set()
        await message.answer("📝 Anime nomini kiriting:")

# 1️⃣ Anime nomi
@dp.message_handler(state=AdminStates.waiting_for_name)
async def anime_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await AdminStates.waiting_for_parts.set()
    await message.answer("➤ Qismlar sonini kiriting (masalan: 12):")

# 2️⃣ Qismlar soni
@dp.message_handler(state=AdminStates.waiting_for_parts)
async def anime_parts(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Iltimos, son kiriting.")
        return
    await state.update_data(parts=int(message.text))
    await AdminStates.waiting_for_status.set()
    await message.answer("➤ Holati: Tugallangan / Davom etmoqda (Tugallangan/Ongoing)")

# 3️⃣ Holati
@dp.message_handler(state=AdminStates.waiting_for_status)
async def anime_status(message: types.Message, state: FSMContext):
    status = message.text.strip()
    await state.update_data(status=status)

    await AdminStates.waiting_for_vote.set()
    await message.answer("➤ Kim ovoz berganini yozing (masalan: Hoshino dubbing):")

# 4️⃣ Kim ovoz bergan
@dp.message_handler(state=AdminStates.waiting_for_voice)
async def anime_vote(message: types.Message, state: FSMContext):
    await state.update_data(vote=message.text)
    await AdminStates.waiting_for_genres.set()
    await message.answer("➤ Janrlarini kiriting (#drama #sport ...):")

# 5️⃣ Janrlari
@dp.message_handler(state=AdminStates.waiting_for_genres)
async def anime_genres(message: types.Message, state: FSMContext):
    await state.update_data(genres=message.text)
    await AdminStates.waiting_for_video.set()
    await message.answer("➤ 60 sekundgacha bo‘lgan videoni yuboring:")

# 6️⃣ Video qabul qilish va bazaga saqlash
@dp.message_handler(content_types=types.ContentType.VIDEO, state=AdminStates.waiting_for_video)
async def anime_video(message: types.Message, state: FSMContext):
    data = await state.get_data()
    video = message.video

    if video.duration > 60:
        await message.answer("❌ Video 60 sekunddan uzun bo‘lmasligi kerak.")
        return

    # Oxirgi kodni olish va yangi kodi tayyorlash
    last_code = await get_last_anime_code()  # bazadan oxirgi kodni oladi
    new_code = last_code + 1 if last_code else 1

    # Caption tayyorlash
    caption = (
        f"{data['name']}\n"
        f"──────────────────────\n"
        f"➤ Mavsum: 1\n"
        f"➤ Holati: {data['status']}\n"
        f"➤ Ovoz berdi: {data['voice']}\n"
        f"➤ Qismi: {data['parts']}/qism yuklandi✅\n"
        f"➤ Kanal: @YourChannel\n"
        f"➤ Tili: Oʻzbekcha\n"
        f"➤ Yili: 2008\n"
        f"➤ Janri: {data['genres']}\n"
        f"──────────────────────"
    )

    # Bazaga saqlash
    await add_anime_code(
        code=new_code,
        title=data['name'],
        parts=data['parts'],
        status=data['status'],
        vote=data['voice'],
        genres=data['genres'],
        video_file_id=video.file_id,
        caption=caption
    )

    await message.answer(f"✅ Anime qo‘shildi.\n📌 Ushbu anime kodi: <code>{new_code}</code>", parse_mode="HTML")
    await state.finish()

# ➕ Anime yuborish boshlash
@dp.message_handler(lambda m: m.text == "📤 Animeni yuborish")
async def send_anime_start(message: types.Message):
    if message.from_user.id in ADMINS:
        await AdminStates.waiting_for_anime_code.set()
        await message.answer("📝 Qaysi animeni yubormoqchisiz? Kodini kiriting:", reply_markup=control_keyboard())

# Kodni qabul qilish va yuborish
@dp.message_handler(state=AdminStates.waiting_for_anime_code)
async def send_anime_handler(message: types.Message, state: FSMContext):
    code = message.text.strip()
    
    # Bazadan animeni olish
    anime = await get_anime_by_code(code)  # Sizning bazadagi funksiyangiz
    if not anime:
        await message.answer("❌ Bunday kod topilmadi. Iltimos, to‘g‘ri kod kiriting.")
        return

    # Caption yaratish
    caption = f"""
{anime['title']}
──────────────────────
➤ Mavsum: {anime['season']}
➤ Holati: {anime['status']}
➤ Ovoz berdi: {anime['voice']}
➤ Qismi: {anime['current_part']}/{anime['total_parts']}-qism yuklandi✅
➤ Kanal: {anime['channel']}
➤ Tili: {anime['language']}
➤ Yili: {anime['year']}
➤ Janri: {' '.join([f'#{g}' for g in anime['genres']])}
──────────────────────
"""

    # Inline tugma yaratish
    watch_btn = InlineKeyboardMarkup().add(
        InlineKeyboardButton("🔹Tomosha qilish🔹", url=f"https://t.me/{BOT_USERNAME}?start={code}")
    )

    # Asosiy kanallarga yuborish
    successful = 0
    failed = 0
    for ch in MAIN_CHANNELS:
        try:
            await bot.send_video(
                chat_id=ch,
                video=anime['file_id'],
                caption=caption,
                parse_mode="HTML",
                reply_markup=watch_btn
            )
            successful += 1
        except Exception as e:
            print(f"[send_anime_handler] {e}")
            failed += 1

    await message.answer(f"✅ Anime yuborildi!\n\n📡 Muvaffaqiyatli kanallar: {successful}\n❌ Xatolik: {failed}", reply_markup=admin_keyboard())
    await state.finish()

# === Kodlar ro‘yxat
@dp.message_handler(lambda m: m.text == "📄 Kodlar ro‘yxati")
async def show_all_animes(message: types.Message):
    kodlar = await get_all_codes()
    if not kodlar:
        await message.answer("Ba'zada hech qanday kodlar yo'q!")
        return

    # Kodlarni raqam bo‘yicha tartiblash
    kodlar = sorted(kodlar, key=lambda x: int(x["code"]))

    # Har 100 tadan bo‘lib yuborish
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
        f"👥 Umumiy foydalanuvchilar: {foydalanuvchilar} ta\n\n"
        f"📂 Barcha yuklangan animelar: {len(kodlar)} ta\n\n"
        f"📅 Bugun qo'shilgan foydalanuvchilar: {today_users} ta"
    )
    await message.answer(text)

# === POST QILISH: rasm yoki video (60s) + universal boshqarish tugmasi ===
@dp.message_handler(lambda m: m.text == "📤 Post qilish")
async def start_post_process(message: types.Message):
    if message.from_user.id in ADMINS:
        await PostStates.waiting_for_image.set()
        await message.answer("🖼 Iltimos, post uchun rasm yoki video yuboring (video 60 sekunddan oshmasin).", reply_markup=control_keyboard())
        
@dp.message_handler(content_types=[types.ContentType.PHOTO, types.ContentType.VIDEO], state=PostStates.waiting_for_image)
async def get_post_image_or_video(message: types.Message, state: FSMContext):
    # boshqarish tugmasi matn sifatida kelganda yana ham ishlaydi,
    # ammo bu handler media turlariga moslashtirilgan
    if message.content_type == "photo":
        file_id = message.photo[-1].file_id
        await state.update_data(media=("photo", file_id))
    elif message.content_type == "video":
        # video.duration mavjud bo'lmasa ehtiyot bo'ling
        duration = getattr(message.video, "duration", 0) or 0
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
        await message.answer("❗ Media topilmadi. Iltimos rasm yoki video yuboring.", reply_markup=control_keyboard())
        await PostStates.waiting_for_image.set()
        return

    media_type, file_id = media
    title = data.get("title")
    link = message.text.strip()

    button = InlineKeyboardMarkup().add(
        InlineKeyboardButton("✨Yuklab olish✨", url=link)
    )

    try:
        if media_type == "photo":
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=file_id,
                caption=title,
                reply_markup=button
            )
        elif media_type == "video":
            await bot.send_video(
                chat_id=message.chat.id,
                video=file_id,
                caption=title,
                reply_markup=button
            )
        await message.answer("✅ Post muvaffaqiyatli yuborildi.", reply_markup=admin_keyboard())
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {e}", reply_markup=admin_keyboard())
    finally:
        await state.finish()

# === Kod o'chirish ===
@dp.message_handler(lambda m: m.text == "❌ Kodni o‘chirish")
async def ask_delete_code(message: types.Message):
    if message.from_user.id in ADMINS:
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
        await message.answer("❗ Noto‘g‘ri format. Kod raqamini yuboring.", reply_markup=admin_keyboard())
        return
    deleted = await delete_kino_code(code)
    if deleted:
        await message.answer(f"✅ Kod {code} o‘chirildi.", reply_markup=admin_keyboard())
    else:
        await message.answer("❌ Kod topilmadi yoki o‘chirib bo‘lmadi.", reply_markup=admin_keyboard())

# === 📡 Boshqarish: universal handler (har qanday state da ishlaydi) ===
@dp.message_handler(lambda m: m.text == "📡 Boshqarish", state="*")
async def control_action(message: types.Message, state: FSMContext):
    await state.finish()
    await send_admin_panel(message)

# === on_startup va run ===
async def on_startup(dp):
    await init_db()
    register_konkurs_handlers(dp, bot, ADMINS)
    print("✅ PostgreSQL bazaga ulandi!")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
