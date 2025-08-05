# konkurs.py
import os
import json
import random
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# === ENV dan olish (main.py bilan bir xil .env) ===
MAIN_CHANNELS = os.getenv("MAIN_CHANNELS", "").split(",") if os.getenv("MAIN_CHANNELS") else []

# === Fayl yo'llari ===
DATA_DIR = "data"
CONTEST_FILE = os.path.join(DATA_DIR, "contest.json")

# contest.json struktura:
# {
#   "active": false,
#   "post_message": "matn yoki bo'sh",
#   "participants": [123, 456, ...],
#   "winners": []  # 1-, 2-, 3-o'rin ketma-ketlikda ID lar
# }

class ContestStates(StatesGroup):
    # Hozircha holat kerak emas, lekin kelajak uchun qoldirdik (masalan: maxsus e'lon matni kiritish)
    idle = State()

# === Yordamchi util: @username yoki -100... chat_id uchun ===
def _as_chat_id(value: str):
    v = value.strip()
    if not v:
        return v
    if v.startswith("@"):
        return v
    try:
        return int(v)
    except:
        return v

# === data/contest.json boshqaruvi ===
def _ensure_datafile():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CONTEST_FILE):
        with open(CONTEST_FILE, "w", encoding="utf-8") as f:
            json.dump({"active": False, "post_message": "", "participants": [], "winners": []},
                      f, ensure_ascii=False, indent=2)

def _load_state():
    _ensure_datafile()
    with open(CONTEST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_state(state: dict):
    _ensure_datafile()
    with open(CONTEST_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# === Admin uchun reply keyboard (Konkurs boshqaruvi) ===
def _admin_menu_kb_contest(is_active: bool, winners_count: int):
    """
    is_active=True bo‘lsa: G‘olib(lar)ni aniqlash, Ishtirokchilar, Tugatish
    is_active=False bo‘lsa: Konkursni boshlash
    """
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    if not is_active:
        kb.add(KeyboardButton("▶️ Konkursni boshlash"))
    else:
        step = winners_count + 1  # 1..3
        if winners_count < 3:
            kb.add(KeyboardButton(f"🏁 G‘olibni aniqlash ({step}/3)"))
        kb.add(KeyboardButton("👥 Ishtirokchilar"))
        kb.add(KeyboardButton("⛔ Konkursni tugatish"))
    return kb

# === Foydalanuvchilar uchun "Ishtirok etish" inline tugmasi ===
def _join_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Ishtirok etish", callback_data="contest_join"))
    return kb

# === Handlerlarni ro'yxatdan o'tkazish ===
def register_konkurs_handlers(dp, bot, ADMINS):
    """
    main.py da:
        from konkurs import register_konkurs_handlers
        ...
        register_konkurs_handlers(dp, bot, ADMINS)
    """

    # --- Admin panelda '🏆 Konkurs' tugmasi bosilganda boshqaruv menyusini ko'rsatish
    @dp.message_handler(lambda m: m.text == "🏆 Konkurs", user_id=ADMINS)
    async def contest_admin_menu(message: types.Message):
        st = _load_state()
        kb = _admin_menu_kb_contest(st["active"], len(st["winners"]))
        await message.answer("🏆 Konkurs boshqaruvi:", reply_markup=kb)

    # --- ▶️ Konkursni boshlash (reply tugma, callback emas)
    @dp.message_handler(lambda m: m.text == "▶️ Konkursni boshlash", user_id=ADMINS)
    async def start_contest(message: types.Message, state_ctx: FSMContext):
        st = _load_state()
        if st["active"]:
            await message.answer("ℹ️ Konkurs allaqachon boshlangan.")
            return

        # Boshlash
        st["active"] = True
        st["participants"] = []
        st["winners"] = []
        st["post_message"] = (
            "🎉 *Konkurs boshlandi!*\n\n"
            "Ishtirok etish uchun quyidagi tugmani bosing."
        )
        _save_state(st)

        # MAIN_CHANNELS ga e’lon yuborish (inline "Ishtirok etish" tugmasi bilan)
        for ch in MAIN_CHANNELS:
            ch = ch.strip()
            if not ch:
                continue
            try:
                await bot.send_message(
                    chat_id=_as_chat_id(ch),
                    text=st["post_message"],
                    reply_markup=_join_kb(),
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"[KONKURS] E’lon yuborishda xatolik: {ch} -> {e}")

        kb = _admin_menu_kb_contest(True, 0)
        await message.answer(
            "✅ Konkurs boshlandi!\nIshtirokchilar endi '✅ Ishtirok etish' tugmasi orqali qo‘shila oladi.",
            reply_markup=kb
        )

    # --- Callback: Foydalanuvchi "Ishtirok etish" ni bosganda
    @dp.callback_query_handler(lambda c: c.data == "contest_join")
    async def join_contest(call: types.CallbackQuery):
        st = _load_state()
        if not st["active"]:
            await call.answer("Konkurs faol emas.", show_alert=True)
            return

        uid = call.from_user.id
        if uid in st["participants"]:
            await call.answer("Siz allaqachon ishtirokchisiz.", show_alert=True)
            return

        st["participants"].append(uid)
        _save_state(st)

        # Tasdiq
        try:
            # Post ostiga reply sifatida ham chiqishi mumkin:
            await call.message.reply(
                f"✅ Siz konkurs ishtirokchisiga aylandingiz.\n🆔 ID: `{uid}`",
                parse_mode="Markdown"
            )
        except:
            pass

        # Callbackga javob
        await call.answer("Muvaffaqiyatli!", show_alert=False)

        # Foydalanuvchiga DM (muvaffaqiyat qiyin bo'lishi mumkin agar DM bloklangan bo'lsa)
        try:
            await bot.send_message(uid, "✅ Konkursga muvaffaqiyatli qo‘shildingiz! Omad!")
        except:
            pass

    # --- 👥 Ishtirokchilar ro'yxati (admin)
    @dp.message_handler(lambda m: m.text == "👥 Ishtirokchilar", user_id=ADMINS)
    async def list_participants(message: types.Message):
        st = _load_state()
        cnt = len(st["participants"])
        if cnt == 0:
            await message.answer("Hozircha ishtirokchilar yo‘q.")
            return
        # Juda uzun bo'lishi mumkin — faqat 50 tasini ko'rsatamiz
        preview = st["participants"][:50]
        text = "👥 Ishtirokchilar soni: <b>{}</b>\n\n".format(cnt)
        text += "\n".join(f"• <code>{uid}</code>" for uid in preview)
        if cnt > 50:
            text += f"\n...\n( jami {cnt} ta )"
        await message.answer(text, parse_mode="HTML")

    # --- 🏁 G‘olibni aniqlash (1/3 -> 3 marta bosiladi)
    @dp.message_handler(lambda m: m.text.startswith("🏁 G‘olibni aniqlash"), user_id=ADMINS)
    async def pick_winner(message: types.Message):
        st = _load_state()
        if not st["active"]:
            await message.answer("Konkurs faol emas.")
            return

        winners = st["winners"]
        if len(winners) >= 3:
            await message.answer("G‘oliblar allaqachon aniqlangan.")
            return

        # Tanlov havzasi: allaqachon yutganlar olib tashlanadi
        pool = [u for u in st["participants"] if u not in winners]
        if not pool:
            await message.answer("Tanlash uchun ishtirokchi yetarli emas.")
            return

        chosen = random.choice(pool)
        winners.append(chosen)
        st["winners"] = winners
        _save_state(st)

        place = len(winners)  # 1, 2 yoki 3
        medal = "🥇" if place == 1 else ("🥈" if place == 2 else "🥉")
        await message.answer(f"{medal} G‘olib aniqlandi: <code>{chosen}</code>", parse_mode="HTML")

        # G‘olibga DM
        try:
            await bot.send_message(chosen, f"🎉 Tabriklaymiz! Siz {place}-o‘rinni qo‘lga kiritdingiz! 🏆")
        except Exception as e:
            print(f"[KONKURS] G‘olibga xabar yuborilmadi ({chosen}): {e}")

        # Keyingi holat uchun klaviatura yangilash
        kb = _admin_menu_kb_contest(True, len(winners))
        await message.answer("Davom etish:", reply_markup=kb)

    # --- ⛔ Konkursni tugatish (admin)
    @dp.message_handler(lambda m: m.text == "⛔ Konkursni tugatish", user_id=ADMINS)
    async def end_contest(message: types.Message):
        st = _load_state()
        if not st["active"]:
            await message.answer("Konkurs allaqachon faol emas.")
            return

        st["active"] = False
        winners = st.get("winners", [])
        _save_state(st)

        # Kanallarga e’lon
        if winners:
            text = (
                "🏁 *Konkurs tugadi!*\n\n"
                "G‘oliblar:\n" +
                (f"1-o‘rin: `{winners[0]}`\n" if len(winners) > 0 else "") +
                (f"2-o‘rin: `{winners[1]}`\n" if len(winners) > 1 else "") +
                (f"3-o‘rin: `{winners[2]}`\n" if len(winners) > 2 else "")
            )
        else:
            text = "🏁 *Konkurs tugadi!* G‘oliblar aniqlanmadi."

        for ch in MAIN_CHANNELS:
            ch = ch.strip()
            if not ch:
                continue
            try:
                await message.bot.send_message(
                    chat_id=_as_chat_id(ch),
                    text=text,
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"[KONKURS] Tugash e’loni xatosi: {ch} -> {e}")

        # Adminga yakuniy holat
        await message.answer("✅ Konkurs tugatildi.", reply_markup=_admin_menu_kb_contest(False, len(winners)))
