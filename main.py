# === 📦 Standart kutubxonalar ===
import io
import os
import asyncio

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

# === 📂 Loyihaga tegishli modullar ===
from konkurs import register_konkurs_handlers
from keep_alive import keep_alive
from database import init_db, add_user, get_user_count, add_kino_code, get_kino_by_code, get_all_codes, delete_kino_code, get_code_stat, increment_stat, get_all_user_ids, update_anime_code, add_channel_to_db, remove_channel_from_db, get_all_channels


load_dotenv()
keep_alive()

API_TOKEN = os.getenv("API_TOKEN")
CHANNELS = os.getenv("CHANNEL_USERNAMES").split(",")
MAIN_CHANNELS = os.getenv("MAIN_CHANNELS").split(",")
BOT_USERNAME = os.getenv("BOT_USERNAME")

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

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

ADMINS = {6486825926}

class AdminStates(StatesGroup):
    waiting_for_kino_data = State()
    waiting_for_delete_code = State()
    waiting_for_stat_code = State()
    waiting_for_broadcast_data = State()
    waiting_for_admin_id = State()
    waiting_for_user_list = State()

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

class ChannelStates(StatesGroup):
    waiting_for_add_channel = State()
    waiting_for_remove_channel = State()

# === OBUNA TEKSHIRISH FUNKSIYASI ===
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

# === BARCHA KANALLAR UCHUN OBUNA MARKUP ===
async def make_full_subscribe_markup(code):
    markup = InlineKeyboardMarkup(row_width=1)
    for ch in CHANNELS:
        try:
            channel = await bot.get_chat(ch.strip())
            invite_link = channel.invite_link or (await channel.export_invite_link())
            markup.add(InlineKeyboardButton(f"➕ {channel.title}", url=invite_link))
        except Exception as e:
            print(f"❗ Kanalni olishda xatolik: {ch} -> {e}")
    markup.add(InlineKeyboardButton("✅ Tekshirish", callback_data=f"checksub:{code}"))
    return markup
    
@dp.message_handler(commands=['start'])
async def start_handler(message: types.Message):
    user_id = message.from_user.id
    # get_args() aiogram 2.25 da bor; None bo‘lsa bo‘sh qatorga tushirsin
    args = (message.get_args() or "").strip()

    # 0) Userni ro‘yxatga olish (sening funksiyang)
    try:
        await add_user(user_id)
    except Exception as e:
        # ro‘yxatga qo‘shish muvaffiyatsiz bo‘lsa ham flow to‘xtamasin
        print(f"[add_user] {user_id} -> {e}")

    # 1) Majburiy obuna tekshiruvi (deeplink parametrini saqlagan holda)
    try:
        unsubscribed = await get_unsubscribed_channels(user_id)
    except Exception as e:
        print(f"[subs_check] {user_id} -> {e}")
        unsubscribed = []

    if unsubscribed:
        # args ni markup ga uzatyapmiz — obuna bo‘lgandan keyin qaytishda deeplink saqlansin
        markup = await make_full_subscribe_markup(args)
        await message.answer(
            "❗ Botdan foydalanish uchun quyidagi kanal(lar)ga obuna bo‘ling:",
            reply_markup=markup
        )
        return

    # 2) Raqamli deeplink: /start 12345 -> kodni yuborish
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

    # 3) Oddiy /start: xush kelibsiz + foydalanuvchi ID
    try:
        if user_id in ADMINS:
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            kb.add("➕ Anime qo‘shish")
            kb.add("📊 Statistika", "📈 Kod statistikasi")
            kb.add("❌ Kodni o‘chirish", "📄 Kodlar ro‘yxati")
            kb.add("✏️ Kodni tahrirlash", "📤 Post qilish")
            kb.add("📢 Habar yuborish", "📘 Qo‘llanma")
            kb.add("➕ Admin qo‘shish", "🏆 Konkurs")
            kb.add("📥 User qo‘shish", "📢 Kanallar")
            kb.add("📦 Bazani olish")
            await message.answer(f"👮‍♂️ Admin panel:\n🆔 Sizning ID: <code>{user_id}</code>", reply_markup=kb, parse_mode="HTML")
        else:
            kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
            kb.add(
                KeyboardButton("🎞 Barcha animelar"),
                KeyboardButton("✉️ Admin bilan bog‘lanish")
            )
            await message.answer(
                f"🎬 Botga xush kelibsiz!\n🆔 Sizning ID: <code>{user_id}</code>\nKod kiriting:",
                reply_markup=kb,
                parse_mode="HTML"
            )
    except Exception as e:
        print(f"[menu] {user_id} -> {e}")

@dp.callback_query_handler(lambda c: c.data.startswith("check_sub:"))
async def check_subscription(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    args = callback_query.data.split("check_sub:")[1]  # kod bo‘lishi mumkin
    bot_info = await bot.get_me()

    # Kanal ro‘yxati — ENV dan yoki kod ichidan olasan
    channels = MAIN_CHANNELS  # list: ['@kanal1', '@kanal2', ...]

    not_subscribed = []
    for channel in channels:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status not in ("member", "administrator", "creator"):
                not_subscribed.append(channel)
        except Exception:
            not_subscribed.append(channel)

    if not_subscribed:
        # Obuna bo‘lmagan foydalanuvchi
        kb = InlineKeyboardMarkup()
        for ch in channels:
            kb.add(InlineKeyboardButton(f"🔗 {ch}", url=f"https://t.me/{ch.lstrip('@')}"))
        kb.add(InlineKeyboardButton("✅ Obunani tekshirish", callback_data=f"check_sub:{args}"))

        await callback_query.message.edit_text(
            "❗ Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling:",
            reply_markup=kb
        )
        return

    # Agar foydalanuvchi obuna bo‘lsa
    if args:
        # Bu yerda kod kiritilgan bo‘lishi mumkin, masalan anime qidirish
        # send_anime_by_code(args, user_id) funksiyani chaqirasan
        await callback_query.message.edit_text(f"✅ Kod topildi: {args}")
    else:
        await callback_query.message.edit_text("✅ Obuna tasdiqlandi!")



# ------------------------------------------------------------------
# ➕ Add anime – first choose target channel
# ------------------------------------------------------------------
@dp.message_handler(lambda m: m.text == "➕ Anime qo‘shish", user_id=ADMINS)
async def add_start(message: types.Message):
    channels = await get_all_channels()
    if not channels:
        await message.answer("❌ Hozircha kanallar yo‘q. Avval kanal qo‘shing.")
        return

    kb = InlineKeyboardMarkup(row_width=1)
    for ch in channels:
        kb.add(InlineKeyboardButton(ch["title"], callback_data=f"pick:{ch['username']}"))
    await message.answer("📢 Animeni qaysi kanalga yuborishni tanlang:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("pick:"), user_id=ADMINS)
async def pick_channel(callback: CallbackQuery, state: FSMContext):
    channel = callback.data.split(":", 1)[1]
    await state.update_data(target_channel=channel)
    await AdminStates.waiting_for_kino_data.set()
    await callback.message.edit_text(
        f"📌 Reklama kanal: {channel}\n\n"
        "📝 Format: `KOD @MyAnimeStorage REKLAMA_ID POST_SONI ANIME_NOMI`",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message_handler(state=AdminStates.waiting_for_kino_data, user_id=ADMINS)
async def add_kino_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_channel = data["target_channel"]

    parts = message.text.strip().split()
    if len(parts) < 5:
        await message.answer("❗ Format noto‘g‘ri. Masalan: `91 @MyAnimeStorage 45 12 Naruto`")
        return

    code, server_channel, reklama_id, post_count = parts[:4]
    title = " ".join(parts[4:])
    if not (code.isdigit() and reklama_id.isdigit() and post_count.isdigit()):
        await message.answer("❗ Hammasi raqam bo‘lishi kerak.")
        return

    reklama_id = int(reklama_id)
    post_count = int(post_count)

    await add_kino_code(code, server_channel, reklama_id + 1, post_count, title)

    download_btn = InlineKeyboardMarkup().add(
        InlineKeyboardButton("📥 Yuklab olish", url=f"https://t.me/{BOT_USERNAME}?start={code}")
    )

    try:
        await bot.copy_message(
            chat_id=target_channel,
            from_chat_id=server_channel,
            message_id=reklama_id,
            reply_markup=download_btn
        )
    except Exception as e:
        await message.answer(f"❌ Reklama yuborishda xatolik: {e}")

    await message.answer("✅ Anime qo‘shildi va reklama yuborildi.")
    await state.finish()


@dp.message_handler(lambda m: m.text == "🎞 Barcha animelar")
async def show_all_animes(message: types.Message):
    kodlar = await get_all_codes()
    if not kodlar:
        await message.answer("⛔️ Hozircha animelar yoʻq.")
        return

    kodlar = sorted(kodlar, key=lambda x: int(x["code"]))  # raqam bo‘yicha tartib
    text = "📄 *Barcha animelar:*\n\n"
    for row in kodlar:
        text += f"`{row['code']}` – *{row['title']}*\n"

    await message.answer(text, parse_mode="Markdown")

@dp.message_handler(lambda m: m.text == "✉️ Admin bilan bog‘lanish")
async def contact_admin(message: types.Message):
    await UserStates.waiting_for_admin_message.set()
    await message.answer("✍️ Adminlarga yubormoqchi bo‘lgan xabaringizni yozing.\n\n❌ Bekor qilish uchun '❌ Bekor qilish' tugmasini bosing.")

@dp.message_handler(state=UserStates.waiting_for_admin_message)
async def forward_to_admins(message: types.Message, state: FSMContext):
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
    await callback.message.answer("✍️ Endi foydalanuvchiga yubormoqchi bo‘lgan xabaringizni yozing.")
    await callback.answer()

@dp.message_handler(state=AdminReplyStates.waiting_for_reply_message, user_id=ADMINS)
async def send_admin_reply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("reply_user_id")

    try:
        await bot.send_message(user_id, f"✉️ Admindan javob:\n\n{message.text}")
        await message.answer("✅ Javob foydalanuvchiga yuborildi.")
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")
    finally:
        await state.finish()


@dp.callback_query_handler(lambda c: c.data == "back_channels", user_id=ADMINS)
async def back_to_channels(callback: CallbackQuery):
    await manage_channels(callback.message)
    await callback.answer()

# ==== QO‘LLANMA MENYUSI ====
@dp.message_handler(lambda m: m.text == "📘 Qo‘llanma")
async def qollanma(message: types.Message):
    kb = (
        InlineKeyboardMarkup(row_width=1)
        .add(InlineKeyboardButton("📥 1. Anime qo‘shish", callback_data="help_add"))
        .add(InlineKeyboardButton("📡 2. Kanal yaratish", callback_data="help_channel"))
        .add(InlineKeyboardButton("🆔 3. Reklama ID olish", callback_data="help_id"))
        .add(InlineKeyboardButton("🔁 4. Kod ishlashi", callback_data="help_code"))
        .add(InlineKeyboardButton("❓ 5. Savol-javob", callback_data="help_faq"))
    )
    await message.answer("📘 Qanday yordam kerak?", reply_markup=kb)


# ==== MATNLAR ====
HELP_TEXTS = {
    "help_add": (
        "📥 *Anime qo‘shish*\n\n"
        "`KOD @kanal REKLAMA_ID POST_SONI ANIME_NOMI`\n\n"
        "Misol: `91 @MyKino 4 12 Naruto`\n\n"
        "• *Kod* – foydalanuvchi yozadigan raqam\n"
        "• *@kanal* – server kanal username\n"
        "• *REKLAMA_ID* – post ID raqami (raqam)\n"
        "• *POST_SONI* – nechta qism borligi\n"
        "• *ANIME_NOMI* – ko‘rsatiladigan sarlavha\n\n"
        "📩 Endi formatda xabar yuboring:"
    ),
    "help_channel": (
        "📡 *Kanal yaratish*\n\n"
        "1. 2 ta kanal yarating:\n"
        "   • *Server kanal* – post saqlanadi\n"
        "   • *Reklama kanal* – bot ulashadi\n\n"
        "2. Har ikkasiga botni admin qiling\n\n"
        "3. Kanalni public (@username) qiling"
    ),
    "help_id": (
        "🆔 *Reklama ID olish*\n\n"
        "1. Server kanalga post joylang\n\n"
        "2. Post ustiga bosing → *Share* → *Copy link*\n\n"
        "3. Link oxiridagi sonni oling\n\n"
        "Misol: `t.me/MyKino/4` → ID = `4`"
    ),
    "help_code": (
        "🔁 *Kod ishlashi*\n\n"
        "1. Foydalanuvchi kod yozadi (masalan: `91`)\n\n"
        "2. Obuna tekshiriladi → reklama post yuboriladi\n\n"
        "3. Tugmalar orqali qismlarni ochadi"
    ),
    "help_faq": (
        "❓ *Tez-tez so‘raladigan savollar*\n\n"
        "• *Kodni qanday ulashaman?*\n"
        "  `https://t.me/<BOT_USERNAME>?start=91`\n\n"
        "• *Har safar yangi kanal kerakmi?*\n"
        "  – Yo‘q, bitta server kanal yetarli\n\n"
        "• *Kodni tahrirlash/o‘chirish mumkinmi?*\n"
        "  – Ha, admin menyuda ✏️ / ❌ tugmalari bor"
    )
}


# ==== CALLBACK: HAR BIR YORDAM SAHIFASI ====
@dp.callback_query_handler(lambda c: c.data.startswith("help_"))
async def show_help_page(callback: types.CallbackQuery):
    key = callback.data
    text = HELP_TEXTS.get(key, "❌ Ma'lumot topilmadi.")
    
    # Ortga tugmasi
    kb = InlineKeyboardMarkup().add(
        InlineKeyboardButton("⬅️ Ortga", callback_data="back_help")
    )
    
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        # Agar matn o'zgartirilmayotgan bo'lsa (masalan, rasmli xabar bo'lsa)
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        await callback.message.delete()  # Eski xabarni o'chirish
    finally:
        await callback.answer()


# ==== ORTGA TUGMASI ====
@dp.callback_query_handler(lambda c: c.data == "back_help")
async def back_to_qollanma(callback: types.CallbackQuery):
    kb = (
        InlineKeyboardMarkup(row_width=1)
        .add(InlineKeyboardButton("📥 1. Anime qo‘shish", callback_data="help_add"))
        .add(InlineKeyboardButton("📡 2. Kanal yaratish", callback_data="help_channel"))
        .add(InlineKeyboardButton("🆔 3. Reklama ID olish", callback_data="help_id"))
        .add(InlineKeyboardButton("🔁 4. Kod ishlashi", callback_data="help_code"))
        .add(InlineKeyboardButton("❓ 5. Savol-javob", callback_data="help_faq"))
    )
    
    try:
        await callback.message.edit_text("📘 Qanday yordam kerak?", reply_markup=kb)
    except Exception as e:
        await callback.message.answer("📘 Qanday yordam kerak?", reply_markup=kb)
        await callback.message.delete()
    finally:
        await callback.answer()

@dp.message_handler(lambda m: m.text == "📥 User qo‘shish", user_id=ADMINS)
async def add_users_start(message: types.Message):
    await AdminStates.waiting_for_user_list.set()
    await message.answer("📋 Foydalanuvchi ID ro‘yxatini yuboring (har bir qatorda bitta ID yoki vergul bilan):")
@dp.message_handler(state=AdminStates.waiting_for_user_list, user_id=ADMINS)
async def add_users_process(message: types.Message, state: FSMContext):
    await state.finish()
    text = message.text.strip()

    # Har bir qatordagi yoki vergul bilan ajratilgan ID larni ajratish
    raw_ids = text.replace(",", "\n").split("\n")
    user_ids = [i.strip() for i in raw_ids if i.strip().isdigit()]

    added = 0
    errors = 0

    for uid in user_ids:
        try:
            await add_user(int(uid))
            added += 1
        except Exception as e:
            print(f"❌ Xato: {uid} -> {e}")
            errors += 1

    await message.answer(f"✅ Qo‘shildi: {added} ta\n❌ Xato: {errors} ta")

@dp.message_handler(lambda m: m.text == "📦 Bazani olish", user_id=ADMINS)
async def dump_database_handler(message: types.Message):
    try:
        # 1️⃣ Users IDs olish
        users = await get_all_user_ids()  # Kutilgan: [1,2,3] yoki [{'user_id':1}, ...]
        normalized_user_ids = []
        for u in users:
            if isinstance(u, dict):
                normalized_user_ids.append(str(u.get('user_id', next(iter(u.values()), ''))))
            elif isinstance(u, (list, tuple)) and u:
                normalized_user_ids.append(str(u[0]))
            else:
                normalized_user_ids.append(str(u))

        users_text = ", ".join(normalized_user_ids) if normalized_user_ids else "Foydalanuvchilar yo'q"

        # 2️⃣ Kodlar olish va formatlash
        codes = await get_all_codes()  # Kutilgan: [{'code','kanal_id','reklamapost_id','qism','nom'}, ...]
        codes_lines = []

        for row in codes:
            if isinstance(row, dict):
                code = row.get("code", "")
                kanal_id = row.get("kanal_id", "")
                reklamapost_id = row.get("reklamapost_id", "")
                qism = row.get("qism", "")
                nom = row.get("nom", "")
            else:
                # Tuple yoki list
                code, kanal_id, reklamapost_id, qism, nom = (list(row) + [""] * 5)[:5]

            codes_lines.append(f"{code} {kanal_id} {reklamapost_id} {qism} {nom}")

        codes_text = "\n".join(codes_lines) if codes_lines else "Kodlar yo'q"

        # 3️⃣ Yuborish — uzun bo‘lsa fayl sifatida
        dump_content = f"--- USERS ---\n{users_text}\n\n--- KODLAR ---\n{codes_text}"
        if len(dump_content) > 3900:
            bio = io.BytesIO()
            bio.name = "database_dump.txt"
            bio.write(dump_content.encode("utf-8"))
            bio.seek(0)
            await message.answer("📦 Bazaning natijasi juda uzun — fayl sifatida yuborilmoqda.")
            await message.answer_document(types.InputFile(bio, filename="database_dump.txt"))
        else:
            await message.answer(f"📋 *Users IDlari:*\n`{users_text}`", parse_mode="Markdown")
            await message.answer(f"🎬 *Kodlar:*\n```\n{codes_text}\n```", parse_mode="Markdown")

    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {e}")
        print(f"[dump_database_handler] Error: {e}")
        
# === Admin qo'shish===
@dp.message_handler(lambda m: m.text == "➕ Admin qo‘shish", user_id=ADMINS)
async def add_admin_start(message: types.Message):
    await message.answer("🆔 Yangi adminning Telegram ID raqamini yuboring.")
    await AdminStates.waiting_for_admin_id.set()

@dp.message_handler(state=AdminStates.waiting_for_admin_id, user_id=ADMINS)
async def add_admin_process(message: types.Message, state: FSMContext):
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
    await message.answer(f"✅ <code>{new_admin_id}</code> admin sifatida qo‘shildi.", parse_mode="HTML")

    try:
        await bot.send_message(new_admin_id, "✅ Siz botga admin sifatida qo‘shildingiz.")
    except:
        await message.answer("⚠️ Yangi adminga habar yuborib bo‘lmadi.")

# === Kod statistikasi
@dp.message_handler(lambda m: m.text == "📈 Kod statistikasi")
async def ask_stat_code(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("📥 Kod raqamini yuboring:")
    await AdminStates.waiting_for_stat_code.set()

@dp.message_handler(state=AdminStates.waiting_for_stat_code)
async def show_code_stat(message: types.Message, state: FSMContext):
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
        f"🔍 Qidirilgan: <b>{stat['searched']}</b>\n",
        parse_mode="HTML"
    )

@dp.message_handler(lambda message: message.text == "✏️ Kodni tahrirlash", user_id=ADMINS)
async def edit_code_start(message: types.Message):
    await message.answer("Qaysi kodni tahrirlashni xohlaysiz? (eski kodni yuboring)")
    await EditCode.WaitingForOldCode.set()

# --- Eski kodni qabul qilish ---
@dp.message_handler(state=EditCode.WaitingForOldCode, user_id=ADMINS)
async def get_old_code(message: types.Message, state: FSMContext):
    code = message.text.strip()
    post = await get_kino_by_code(code)
    if not post:
        await message.answer("❌ Bunday kod topilmadi. Qaytadan urinib ko‘ring.")
        return
    await state.update_data(old_code=code)
    await message.answer(f"🔎 Kod: {code}\n📌 Nomi: {post['title']}\n\nYangi kodni yuboring:")
    await EditCode.WaitingForNewCode.set()

# --- Yangi kodni olish ---
@dp.message_handler(state=EditCode.WaitingForNewCode, user_id=ADMINS)
async def get_new_code(message: types.Message, state: FSMContext):
    await state.update_data(new_code=message.text.strip())
    await message.answer("Yangi nomini yuboring:")
    await EditCode.WaitingForNewTitle.set()

# --- Yangi nomni olish va yangilash ---
@dp.message_handler(state=EditCode.WaitingForNewTitle, user_id=ADMINS)
async def get_new_title(message: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        await update_anime_code(
            data['old_code'],
            data['new_code'],
            message.text.strip()
        )
        await message.answer("✅ Kod va nom muvaffaqiyatli tahrirlandi.")
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi:\n{e}")
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
    await message.answer("📨 Habar yuborish uchun format:\n`@kanal xabar_id`", parse_mode="Markdown")

@dp.message_handler(state=AdminStates.waiting_for_broadcast_data)
async def send_forward_only(message: types.Message, state: FSMContext):
    await state.finish()
    parts = message.text.strip().split()
    if len(parts) != 2:
        await message.answer("❗ Format noto‘g‘ri. Masalan: `@kanalim 123`")
        return

    channel_username, msg_id = parts
    if not msg_id.isdigit():
        await message.answer("❗ Xabar ID raqam bo‘lishi kerak.")
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

    await message.answer(f"✅ Yuborildi: {success} ta\n❌ Xatolik: {fail} ta")

# === Obuna tekshirish callback
@dp.callback_query_handler(lambda c: c.data.startswith("check_sub:"))
async def check_sub_callback(callback_query: types.CallbackQuery):
    code = callback_query.data.split(":")[1]
    user_id = callback_query.from_user.id

    not_subscribed = []
    buttons = []

    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ['left', 'kicked']:
                not_subscribed.append(channel)
                invite_link = await bot.create_chat_invite_link(channel)
                buttons.append([
                    InlineKeyboardButton("🔔 Obuna bo‘lish", url=invite_link.invite_link)
                ])
        except Exception as e:
            print(f"❌ Obuna tekshiruv xatosi: {channel} -> {e}")
            continue

    if not_subscribed:
        buttons.append([InlineKeyboardButton("✅ Tekshirish", callback_data=f"check_sub:{code}")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback_query.message.edit_text(
            "❗ Hali ham barcha kanallarga obuna bo‘lmagansiz. Iltimos, barchasiga obuna bo‘ling:",
            reply_markup=keyboard
        )
    else:
        await callback_query.message.edit_text("✅ Obuna muvaffaqiyatli tekshirildi!")
        await send_reklama_post(user_id, code)

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
    except:
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

# === Kodlar ro‘yxati
@dp.message_handler(lambda m: m.text.strip() == "📄 Kodlar ro‘yxati")
async def kodlar(message: types.Message):
    kodlar = await get_all_codes()
    if not kodlar:
        await message.answer("⛔️ Hech qanday kod topilmadi.")
        return

    # Kodlarni raqam bo‘yicha kichikdan kattasiga saralash
    kodlar = sorted(kodlar, key=lambda x: int(x["code"]))

    text = "📄 *Kodlar ro‘yxati:*\n\n"
    for row in kodlar:
        code = row["code"]
        title = row["title"]
        text += f"`{code}` - *{title}*\n"

    await message.answer(text, parse_mode="Markdown")

@dp.message_handler(lambda m: m.text == "📢 Kanallar", user_id=ADMINS)
async def manage_channels(message: types.Message):
    kb = (
        InlineKeyboardMarkup(row_width=1)
        .add(InlineKeyboardButton("➕ Kanal qo‘shish", callback_data="add_channel"))
        .add(InlineKeyboardButton("➖ Kanal o‘chirish", callback_data="remove_channel"))
        .add(InlineKeyboardButton("📋 Kanallar ro‘yxati", callback_data="list_channels"))
    )
    await message.answer("📢 Kanallar boshqaruvi:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "add_channel", user_id=ADMINS)
async def ask_add_channel(callback: CallbackQuery, state: FSMContext):
    await ChannelStates.waiting_for_add_channel.set()
    await callback.message.edit_text("➕ Kanal username yoki ID ni yuboring:\nMasalan: @mychannel")
    await callback.answer()

@dp.message_handler(state=ChannelStates.waiting_for_add_channel, user_id=ADMINS)
async def add_channel(message: types.Message, state: FSMContext):
    channel = message.text.strip()
    try:
        chat = await bot.get_chat(channel)
        await add_channel_to_db(chat.id, chat.title, chat.username)
        await message.answer(f"✅ Kanal qo‘shildi: {chat.title}")
    except Exception as e:
        await message.answer("❌ Kanal topilmadi yoki botga admin qilinmagan.")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "remove_channel", user_id=ADMINS)
async def ask_remove_channel(callback: CallbackQuery, state: FSMContext):
    channels = await get_all_channels()
    if not channels:
        await callback.message.edit_text("❌ Hozircha kanallar yo‘q.")
        return
    kb = InlineKeyboardMarkup(row_width=1)
    for ch in channels:
        kb.add(InlineKeyboardButton(ch["title"], callback_data=f"del_{ch['id']}"))
    kb.add(InlineKeyboardButton("⬅️ Ortga", callback_data="back_channels"))
    await callback.message.edit_text("➖ O‘chirmoqchi bo‘lgan kanalni tanlang:", reply_markup=kb)
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("del_"), user_id=ADMINS)
async def confirm_remove_channel(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[1])
    await remove_channel_from_db(channel_id)
    await callback.message.edit_text("✅ Kanal o‘chirildi.")

@dp.callback_query_handler(lambda c: c.data == "list_channels", user_id=ADMINS)
async def list_channels(callback: CallbackQuery):
    channels = await get_all_channels()
    if not channels:
        await callback.message.edit_text("❌ Hozircha kanallar yo‘q.")
        return
    text = "📋 Barcha kanallar:\n\n"
    for ch in channels:
        text += f"📢 `@{ch['username']}` – {ch['title']}\n"
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Ortga", callback_data="back_channels"))
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "back_channels", user_id=ADMINS)
async def back_to_channels(callback: CallbackQuery):
    await manage_channels(callback.message)
    await callback.answer()

@dp.message_handler(lambda m: m.text == "📊 Statistika")
async def stats(message: types.Message):
    kodlar = await get_all_codes()
    foydalanuvchilar = await get_user_count()
    await message.answer(f"📦 Kodlar: {len(kodlar)}\n👥 Foydalanuvchilar: {foydalanuvchilar}")

@dp.message_handler(lambda m: m.text == "📤 Post qilish")
async def start_post_process(message: types.Message):
    if message.from_user.id in ADMINS:
        await PostStates.waiting_for_image.set()
        await message.answer("🖼 Iltimos, post uchun rasm yuboring.")
        
@dp.message_handler(content_types=types.ContentType.PHOTO, state=PostStates.waiting_for_image)
async def get_post_image(message: types.Message, state: FSMContext):
    photo = message.photo[-1].file_id
    await state.update_data(photo=photo)
    await PostStates.waiting_for_title.set()
    await message.answer("📌 Endi rasm ostiga yoziladigan nomni yuboring.")
@dp.message_handler(state=PostStates.waiting_for_title)
async def get_post_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await PostStates.waiting_for_link.set()
    await message.answer("🔗 Yuklab olish uchun havolani yuboring.")
@dp.message_handler(state=PostStates.waiting_for_link)
async def get_post_link(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photo = data.get("photo")
    title = data.get("title")
    link = message.text.strip()

    button = InlineKeyboardMarkup().add(
        InlineKeyboardButton("📥 Yuklab olish", url=link)
    )

    try:
        await bot.send_photo(
            chat_id=message.chat.id,
            photo=photo,
            caption=title,
            reply_markup=button
        )
        await message.answer("✅ Post muvaffaqiyatli yuborildi.")
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {e}")
    finally:
        await state.finish()

@dp.message_handler(lambda m: m.text == "❌ Kodni o‘chirish")
async def ask_delete_code(message: types.Message):
    if message.from_user.id in ADMINS:
        await AdminStates.waiting_for_delete_code.set()
        await message.answer("🗑 Qaysi kodni o‘chirmoqchisiz? Kodni yuboring.")

@dp.message_handler(state=AdminStates.waiting_for_delete_code)
async def delete_code_handler(message: types.Message, state: FSMContext):
    await state.finish()
    code = message.text.strip()
    if not code.isdigit():
        await message.answer("❗ Noto‘g‘ri format. Kod raqamini yuboring.")
        return
    deleted = await delete_kino_code(code)
    if deleted:
        await message.answer(f"✅ Kod {code} o‘chirildi.")
    else:
        await message.answer("❌ Kod topilmadi yoki o‘chirib bo‘lmadi.")

# ------------------------------------------------------------------
# 🚀 Startup
# ------------------------------------------------------------------
async def on_startup(dp):
    await init_db()
    register_konkurs_handlers(dp, bot, ADMINS)
    print("✅ PostgreSQL bazaga ulandi!")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
