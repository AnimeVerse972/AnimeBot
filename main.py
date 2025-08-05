import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext, filters
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
    update_anime_code
)

# === ENV / STARTUP ===
load_dotenv()
keep_alive()

API_TOKEN = os.getenv("API_TOKEN")
if not API_TOKEN:
    raise RuntimeError("API_TOKEN topilmadi")

def _split_env_list(name: str):
    v = os.getenv(name, "")
    return [s.strip() for s in v.split(",") if s.strip()]

CHANNELS = _split_env_list("CHANNEL_USERNAMES")
MAIN_CHANNELS = _split_env_list("MAIN_CHANNELS")  # kerak bo'lsa, ishlatishingiz mumkin
BOT_USERNAME = os.getenv("BOT_USERNAME", "")

bot = Bot(token=API_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Adminlar
ADMINS = {6486825926, 7711928526}

# --- Holatlar ---
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

# === Helper: faqat adminlar ===
def admin_filter(message: types.Message):
    return message.from_user and message.from_user.id in ADMINS

# === Helper: obunani tekshirish va markup ===
async def get_unsubscribed_channels(user_id: int):
    unsub = []
    for ch in CHANNELS:
        try:
            m = await bot.get_chat_member(ch, user_id)
            if m.status not in ("member", "administrator", "creator"):
                unsub.append(ch)
        except Exception as e:
            # Agar chat private yoki bot admin emas bo'lsa, foydalanuvchi obuna deb hisoblanmasin
            print(f"❗ Obuna tekshirishda xatolik: {ch} -> {e}")
            unsub.append(ch)
    return unsub

async def is_user_subscribed(user_id: int) -> bool:
    unsub = await get_unsubscribed_channels(user_id)
    return len(unsub) == 0

async def _safe_invite_link_for(ch: str) -> str:
    """
    Har safar yangi link yaratmaslikka harakat:
    - Agar chat public bo'lsa, @username ishlaydi (t.me/username).
    - Agar private bo'lsa:
        1) chat.invite_link bo'lsa o'shani
        2) bo'lmasa export_invite_link()
    """
    try:
        chat = await bot.get_chat(ch)
        if chat.username:
            return f"https://t.me/{chat.username}"
        if chat.invite_link:
            return chat.invite_link
        # Agar invite_link yo'q bo'lsa, export qilib olamiz:
        link = await bot.export_chat_invite_link(chat.id)
        return link
    except Exception as e:
        print(f"❗ Link olishda xatolik: {ch} -> {e}")
        # Fallback: t.me/username bo'lmasa ham foydalanuvchiga ko'rsatamiz
        return f"https://t.me/{ch.lstrip('@')}"

def make_check_button(cb: str) -> InlineKeyboardButton:
    return InlineKeyboardButton("✅ Tekshirish", callback_data=cb)

async def make_subscribe_markup(code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    for ch in CHANNELS:
        url = await _safe_invite_link_for(ch)
        kb.add(InlineKeyboardButton("📢 Obuna bo‘lish", url=url))
    kb.add(make_check_button(f"checksub:{code}"))
    return kb

# === /start ===
@dp.message_handler(commands=['start'])
async def start_handler(message: types.Message):
    await add_user(message.from_user.id)
    args = message.get_args()

    # Admin panel yoki foydalanuvchi menyusi
    if message.from_user.id in ADMINS:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("➕ Anime qo‘shish")
        kb.add("📊 Statistika", "📈 Kod statistikasi")
        kb.add("❌ Kodni o‘chirish", "📄 Kodlar ro‘yxati")
        kb.add("✏️ Kodni tahrirlash", "📤 Post qilish")
        kb.add("📢 Habar yuborish", "📘 Qo‘llanma")
        kb.add("➕ Admin qo‘shish")
        kb.add("📥 User qo‘shish")
        # Agar /start ga param kelsa, uni ham ishlaymiz (pastda)
        await message.answer("👮‍♂️ Admin panel:", reply_markup=kb)
    else:
        kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        kb.add(
            KeyboardButton("🎞 Barcha animelar"),
            KeyboardButton("✉️ Admin bilan bog‘lanish")
        )
        await message.answer("🎬 Botga xush kelibsiz!\nKod kiriting:", reply_markup=kb)

    # Agar /start 123 kabi kelgan bo'lsa — shu yerda ishlaymiz
    if args and args.isdigit():
        code = args
        # searched faqat bir marta — /start param bilan keldi
        await increment_stat(code, "searched")

        if not await is_user_subscribed(message.from_user.id):
            markup = await make_subscribe_markup(code)
            await message.answer(
                "❗ Kino olishdan oldin quyidagi kanal(lar)ga obuna bo‘ling:",
                reply_markup=markup
            )
        else:
            await send_reklama_post(message.from_user.id, code)

# === Obuna tekshirish: yagona callback ===
@dp.callback_query_handler(lambda c: c.data.startswith("checksub:"))
async def check_subscription_callback(call: CallbackQuery):
    code = call.data.split(":")[1]
    unsub = await get_unsubscribed_channels(call.from_user.id)

    if unsub:
        kb = InlineKeyboardMarkup(row_width=1)
        for ch in unsub:
            url = await _safe_invite_link_for(ch)
            kb.add(InlineKeyboardButton("📢 Obuna bo‘lish", url=url))
        kb.add(make_check_button(f"checksub:{code}"))
        await call.message.edit_text("❗ Hali ham barcha kanallarga obuna bo‘lmagansiz. Iltimos, barchasiga obuna bo‘ling:", reply_markup=kb)
    else:
        try:
            await call.message.delete()
        except:
            pass
        await send_reklama_post(call.from_user.id, code)
    await call.answer()

# === Foydalanuvchi menyulari ===
@dp.message_handler(lambda m: m.text == "🎞 Barcha animelar")
async def show_all_animes(message: types.Message):
    kodlar = await get_all_codes()
    if not kodlar:
        await message.answer("⛔️ Hozircha animelar yoʻq.")
        return

    # raqam bo‘yicha tartib: raqam bo'lmagan bo'lsa, oxirida qolsin
    def _sort_key(x):
        c = str(x.get("code", "")).strip()
        return (0, int(c)) if c.isdigit() else (1, c)

    kodlar = sorted(kodlar, key=_sort_key)
    text = "📄 <b>Barcha animelar:</b>\n\n"
    for row in kodlar:
        text += f"<code>{row['code']}</code> – <b>{row['title']}</b>\n"

    await message.answer(text)

@dp.message_handler(lambda m: m.text == "✉️ Admin bilan bog‘lanish")
async def contact_admin(message: types.Message):
    await UserStates.waiting_for_admin_message.set()
    await message.answer("✍️ Adminlarga yubormoqchi bo‘lgan xabaringizni yozing.\n\n❌ Bekor qilish uchun '❌ Bekor qilish' tugmasini bosing.")

@dp.message_handler(state=UserStates.waiting_for_admin_message)
async def forward_to_admins(message: types.Message, state: FSMContext):
    await state.finish()
    user = message.from_user
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("✉️ Javob yozish", callback_data=f"reply_user:{user.id}"))

    for admin_id in ADMINS:
        try:
            await bot.send_message(
                admin_id,
                f"📩 <b>Yangi xabar:</b>\n\n"
                f"<b>👤 Foydalanuvchi:</b> {user.full_name} | <code>{user.id}</code>\n"
                f"<b>💬 Xabar:</b> {message.text}",
                reply_markup=kb
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

HELP_TEXTS = {
    "help_add": (
        "📥 <b>Anime qo‘shish</b>\n\n"
        "<code>KOD @kanal REKLAMA_ID POST_SONI ANIME_NOMI</code>\n\n"
        "Misol: <code>91 @MyKino 4 12 Naruto</code>\n\n"
        "• <b>Kod</b> – foydalanuvchi yozadigan raqam\n"
        "• <b>@kanal</b> – server kanal username\n"
        "• <b>REKLAMA_ID</b> – post ID raqami (raqam)\n"
        "• <b>POST_SONI</b> – nechta qism borligi\n"
        "• <b>ANIME_NOMI</b> – ko‘rsatiladigan sarlavha\n\n"
        "📩 Endi shu formatda xabar yuboring:"
    ),
    "help_channel": (
        "📡 <b>Kanal yaratish</b>\n\n"
        "1) 2 ta kanal yarating: Server va Reklama\n"
        "2) Har ikkisiga botni admin qiling\n"
        "3) Kanalni public (@username) qiling yoki invite link bering"
    ),
    "help_id": (
        "🆔 <b>Reklama ID olish</b>\n\n"
        "1) Server kanalga post joylang\n"
        "2) Post → Share → Copy link\n"
        "3) Link oxiridagi son ID bo'ladi (masalan: t.me/MyKino/4 → ID=4)"
    ),
    "help_code": (
        "🔁 <b>Kod ishlashi</b>\n\n"
        "1) Foydalanuvchi kod yozadi (masalan: <code>91</code>)\n"
        "2) Obuna tekshiriladi → reklama post yuboriladi\n"
        "3) Tugmalar orqali qismlarni ochadi"
    ),
    "help_faq": (
        "❓ <b>Tez-tez so‘raladigan savollar</b>\n\n"
        "• Kod ulashish: <code>https://t.me/{BOT}?start=91</code>\n"
        "• Har safar yangi kanal kerakmi? — Yo‘q\n"
        "• Tahrirlash/o‘chirish — Admin menyudan"
    ).replace("{BOT}", BOT_USERNAME or "YourBot")
}

@dp.callback_query_handler(lambda c: c.data.startswith("help_"))
async def show_help_page(callback: types.CallbackQuery):
    key = callback.data
    text = HELP_TEXTS.get(key, "❌ Ma'lumot topilmadi.")
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Ortga", callback_data="back_help"))
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
        with contextlib.suppress(Exception):
            await callback.message.delete()
    finally:
        await callback.answer()

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
    except Exception:
        await callback.message.answer("📘 Qanday yordam kerak?", reply_markup=kb)
        with contextlib.suppress(Exception):
            await callback.message.delete()
    finally:
        await callback.answer()

# === User qo'shish (admin)
@dp.message_handler(lambda m: m.text == "📥 User qo‘shish", func=admin_filter)
async def add_users_start(message: types.Message):
    await AdminStates.waiting_for_user_list.set()
    await message.answer("📋 Foydalanuvchi ID ro‘yxatini yuboring (har bir qatorda bitta ID yoki vergul bilan):")

@dp.message_handler(state=AdminStates.waiting_for_user_list, func=admin_filter)
async def add_users_process(message: types.Message, state: FSMContext):
    await state.finish()
    raw_ids = message.text.replace(",", "\n").split("\n")
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

# === Admin qo'shish
@dp.message_handler(lambda m: m.text == "➕ Admin qo‘shish", func=admin_filter)
async def add_admin_start(message: types.Message):
    await message.answer("🆔 Yangi adminning Telegram ID raqamini yuboring.")
    await AdminStates.waiting_for_admin_id.set()

@dp.message_handler(state=AdminStates.waiting_for_admin_id, func=admin_filter)
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
    await message.answer(f"✅ <code>{new_admin_id}</code> admin sifatida qo‘shildi.")
    with contextlib.suppress(Exception):
        await bot.send_message(new_admin_id, "✅ Siz botga admin sifatida qo‘shildingiz.")

# === Kod statistikasi
@dp.message_handler(lambda m: m.text == "📈 Kod statistikasi", func=admin_filter)
async def ask_stat_code(message: types.Message):
    await message.answer("📥 Kod raqamini yuboring:")
    await AdminStates.waiting_for_stat_code.set()

@dp.message_handler(state=AdminStates.waiting_for_stat_code, func=admin_filter)
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
        f"🔍 Qidirilgan: <b>{stat.get('searched', 0)}</b>"
        # 'viewed' ataylab olib tashlandi — endi ko'rsatilmaydi
    )

# === Kodni tahrirlash
@dp.message_handler(lambda m: m.text == "✏️ Kodni tahrirlash", func=admin_filter)
async def edit_code_start(message: types.Message):
    await message.answer("Qaysi kodni tahrirlashni xohlaysiz? (eski kodni yuboring)")
    await EditCode.WaitingForOldCode.set()

@dp.message_handler(state=EditCode.WaitingForOldCode, func=admin_filter)
async def get_old_code(message: types.Message, state: FSMContext):
    code = message.text.strip()
    post = await get_kino_by_code(code)
    if not post:
        await message.answer("❌ Bunday kod topilmadi. Qaytadan urinib ko‘ring.")
        return
    await state.update_data(old_code=code)
    await message.answer(f"🔎 Kod: {code}\n📌 Nomi: {post['title']}\n\nYangi kodni yuboring:")
    await EditCode.WaitingForNewCode.set()

@dp.message_handler(state=EditCode.WaitingForNewCode, func=admin_filter)
async def get_new_code(message: types.Message, state: FSMContext):
    await state.update_data(new_code=message.text.strip())
    await message.answer("Yangi nomini yuboring:")
    await EditCode.WaitingForNewTitle.set()

@dp.message_handler(state=EditCode.WaitingForNewTitle, func=admin_filter)
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

# === Raqam yuborilganda (kod)
@dp.message_handler(lambda message: message.text and message.text.isdigit())
async def handle_code_message(message: types.Message):
    code = message.text.strip()

    if not await is_user_subscribed(message.from_user.id):
        markup = await make_subscribe_markup(code)
        await message.answer("❗ Kino olishdan oldin quyidagi kanal(lar)ga obuna bo‘ling:", reply_markup=markup)
        return

    # searched faqat shu yerda oshadi (kod yozilganda)
    await increment_stat(code, "searched")
    await send_reklama_post(message.from_user.id, code)

# === 📢 Habar yuborish (forward)
@dp.message_handler(lambda m: m.text == "📢 Habar yuborish", func=admin_filter)
async def ask_broadcast_info(message: types.Message):
    await AdminStates.waiting_for_broadcast_data.set()
    await message.answer("📨 Habar yuborish uchun format:\n<code>@kanal xabar_id</code>")

@dp.message_handler(state=AdminStates.waiting_for_broadcast_data, func=admin_filter)
async def send_forward_only(message: types.Message, state: FSMContext):
    await state.finish()
    parts = message.text.strip().split()
    if len(parts) != 2:
        await message.answer("❗ Format noto‘g‘ri. Masalan: <code>@kanalim 123</code>")
        return

    channel_username, msg_id = parts
    if not msg_id.isdigit():
        await message.answer("❗ Xabar ID raqam bo‘lishi kerak.")
        return

    msg_id = int(msg_id)
    users = await get_all_user_ids()

    success = 0
    fail = 0
    for user_id in users:
        try:
            await bot.forward_message(chat_id=user_id, from_chat_id=channel_username, message_id=msg_id)
            success += 1
        except Exception as e:
            print(f"Xatolik {user_id} uchun: {e}")
            fail += 1

    await message.answer(f"✅ Yuborildi: {success} ta\n❌ Xatolik: {fail} ta")

# === Reklama postni yuborish
async def send_reklama_post(user_id: int, code: str):
    data = await get_kino_by_code(code)
    if not data:
        await bot.send_message(user_id, "❌ Kod topilmadi.")
        return

    channel = data["channel"]
    reklama_id = int(data["message_id"])
    post_count = int(data["post_count"])

    # 1..post_count tugmalar
    buttons = [InlineKeyboardButton(str(i), callback_data=f"kino:{code}:{i}") for i in range(1, post_count + 1)]
    keyboard = InlineKeyboardMarkup(row_width=5)
    keyboard.add(*buttons)

    try:
        # Siz avval bazaga reklama_id+1 qo'shgansiz; copy qilishda to'g'ri postni yuboramiz
        await bot.copy_message(user_id, channel, reklama_id - 1, reply_markup=keyboard)
    except Exception as e:
        print(f"❌ Reklama copy_message xatosi: {e}")
        await bot.send_message(user_id, "❌ Reklama postni yuborib bo‘lmadi.")

# === Tugma orqali kino yuborish
@dp.callback_query_handler(lambda c: c.data.startswith("kino:"))
async def kino_button(callback: types.CallbackQuery):
    _, code, number = callback.data.split(":")
    number = int(number)

    result = await get_kino_by_code(code)
    if not result:
        await callback.message.answer("❌ Kod topilmadi.")
        await callback.answer()
        return

    channel = result["channel"]
    base_id = int(result["message_id"])
    post_count = int(result["post_count"])

    if number > post_count or number < 1:
        await callback.answer("❌ Bunday post yo‘q!", show_alert=True)
        return

    try:
        await bot.copy_message(callback.from_user.id, channel, base_id + number - 1)
    except Exception as e:
        print(f"❌ Kino copy_message xatosi: {e}")
        await callback.message.answer("❌ Postni yuborib bo‘lmadi.")
    await callback.answer()

# === ➕ Anime qo‘shish
@dp.message_handler(lambda m: m.text == "➕ Anime qo‘shish", func=admin_filter)
async def add_start(message: types.Message):
    await AdminStates.waiting_for_kino_data.set()
    await message.answer("📝 Format: <code>KOD @kanal REKLAMA_ID POST_SONI ANIME_NOMI</code>\nMasalan: <code>91 @MyKino 4 12 Naruto</code>")

@dp.message_handler(state=AdminStates.waiting_for_kino_data, func=admin_filter)
async def add_kino_handler(message: types.Message, state: FSMContext):
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

        # Bazaga saqlaymiz: eski kodingizga mos ravishda reklama_id + 1 qilib saqlaysiz
        try:
            await add_kino_code(code, server_channel, reklama_id + 1, post_count, title)
            successful += 1
        except Exception as e:
            print(f"❌ add_kino_code xato: {e}")
            failed += 1

    await message.answer(f"✅ Muvaffaqiyatli: {successful}\n❌ Xatolik: {failed}")
    await state.finish()

# === Kodlar ro‘yxati
@dp.message_handler(lambda m: m.text.strip() == "📄 Kodlar ro‘yxati")
async def kodlar(message: types.Message):
    kodlar = await get_all_codes()
    if not kodlar:
        await message.answer("⛔️ Hech qanday kod topilmadi.")
        return

    def _sort_key(x):
        c = str(x.get("code", "")).strip()
        return (0, int(c)) if c.isdigit() else (1, c)

    kodlar = sorted(kodlar, key=_sort_key)
    text = "📄 <b>Kodlar ro‘yxati:</b>\n\n"
    for row in kodlar:
        text += f"<code>{row['code']}</code> - <b>{row['title']}</b>\n"

    await message.answer(text)

# === Statistika
@dp.message_handler(lambda m: m.text == "📊 Statistika")
async def stats(message: types.Message):
    kodlar = await get_all_codes()
    foydalanuvchilar = await get_user_count()
    await message.answer(f"📦 Kodlar: {len(kodlar)}\n👥 Foydalanuvchilar: {foydalanuvchilar}")

# === Post qilish (rasm+caption+link)
@dp.message_handler(lambda m: m.text == "📤 Post qilish", func=admin_filter)
async def start_post_process(message: types.Message):
    await PostStates.waiting_for_image.set()
    await message.answer("🖼 Iltimos, post uchun rasm yuboring.")

@dp.message_handler(content_types=types.ContentType.PHOTO, state=PostStates.waiting_for_image, func=admin_filter)
async def get_post_image(message: types.Message, state: FSMContext):
    photo = message.photo[-1].file_id
    await state.update_data(photo=photo)
    await PostStates.waiting_for_title.set()
    await message.answer("📌 Endi rasm ostiga yoziladigan nomni yuboring.")

@dp.message_handler(state=PostStates.waiting_for_title, func=admin_filter)
async def get_post_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await PostStates.waiting_for_link.set()
    await message.answer("🔗 Yuklab olish uchun havolani yuboring.")

@dp.message_handler(state=PostStates.waiting_for_link, func=admin_filter)
async def get_post_link(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photo = data.get("photo")
    title = data.get("title")
    link = message.text.strip()

    button = InlineKeyboardMarkup().add(InlineKeyboardButton("📥 Yuklab olish", url=link))

    try:
        await bot.send_photo(chat_id=message.chat.id, photo=photo, caption=title, reply_markup=button)
        await message.answer("✅ Post muvaffaqiyatli yuborildi.")
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {e}")
    finally:
        await state.finish()

# === Kodni o‘chirish
@dp.message_handler(lambda m: m.text == "❌ Kodni o‘chirish", func=admin_filter)
async def ask_delete_code(message: types.Message):
    await AdminStates.waiting_for_delete_code.set()
    await message.answer("🗑 Qaysi kodni o‘chirmoqchisiz? Kodni yuboring.")

@dp.message_handler(state=AdminStates.waiting_for_delete_code, func=admin_filter)
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

# === Startup
async def on_startup(dp):
    await init_db()
    print("✅ PostgreSQL bazaga ulandi!")

if __name__ == "__main__":
    import contextlib
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
