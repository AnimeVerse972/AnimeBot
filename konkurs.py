# konkurs.py
import os
import json
import random
from typing import List, Dict, Any, Optional

import asyncpg
from aiogram import types, Dispatcher
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup

# ==== ENV ====
MAIN_CHANNELS = [c.strip() for c in (os.getenv("MAIN_CHANNELS") or "").split(",") if c.strip()]
DATABASE_URL = os.getenv("DATABASE_URL")  # postgresql://user:pass@host:port/dbname

# ==== GLOBAL DB POOL ====
_pool: Optional[asyncpg.pool.Pool] = None


# ==== HOLATLAR ====
class KonkursStates(StatesGroup):
    waiting_for_image = State()
    waiting_for_caption = State()


# ==== TUGMALAR ====
def konkurs_menu_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("🚀 Konkursni boshlash", callback_data="konkurs:start"),
        InlineKeyboardButton("🏅 G‘olibni aniqlash", callback_data="konkurs:pick"),
        InlineKeyboardButton("👥 Ishtirokchilar", callback_data="konkurs:participants"),
        InlineKeyboardButton("⛔️ Konkursni yakunlash", callback_data="konkurs:finish"),
    )
    return kb


def participate_kb(bot_username: str):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Ishtirok etish", url=f"https://t.me/{bot_username}?start=konkurs"))
    return kb


# ==== DB INIT ====
async def db_init():
    """
    Ilk ishga tushirishda chaqiring.
    """
    global _pool
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL topilmadi (env).")

    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)

    async with _pool.acquire() as conn:
        # participants: har bir user 1 martadan yoziladi
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS participants (
                id SERIAL PRIMARY KEY,
                user_id BIGINT UNIQUE NOT NULL
            );
        """)

        # contest: bitta satrda joriy konkurs holati saqlanadi
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contest (
                id SERIAL PRIMARY KEY,
                active BOOLEAN DEFAULT FALSE,
                winners BIGINT[] DEFAULT '{}',
                post_ids JSONB DEFAULT '[]'::jsonb
            );
        """)

        # Agar satr yo'q bo'lsa, bitta qo'shib qo'yamiz
        row = await conn.fetchrow("SELECT id FROM contest LIMIT 1;")
        if not row:
            await conn.execute("INSERT INTO contest (active, winners, post_ids) VALUES (FALSE, '{}', '[]');")


# ==== DB HELPERS ====
async def load_participants() -> Dict[str, List[int]]:
    async with _pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM participants ORDER BY id;")
    return {"participants": [r["user_id"] for r in rows]}


async def save_participant(user_id: int) -> None:
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO participants (user_id) VALUES ($1)
            ON CONFLICT (user_id) DO NOTHING;
        """, user_id)


async def clear_participants() -> None:
    async with _pool.acquire() as conn:
        await conn.execute("TRUNCATE participants;")


async def load_contest() -> Dict[str, Any]:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("SELECT active, winners, post_ids FROM contest LIMIT 1;")
    if not row:
        return {"active": False, "winners": [], "post_ids": []}
    # post_ids JSONB bo'ladi: [{"chat": <str|int>, "message_id": <int>}, ...]
    return {
        "active": row["active"],
        "winners": list(row["winners"] or []),
        "post_ids": row["post_ids"] or []
    }


async def save_contest(data: Dict[str, Any]) -> None:
    active = bool(data.get("active", False))
    winners = list(data.get("winners", []))
    post_ids = data.get("post_ids", [])

    # JSONB sifatida saqlash uchun dump qilamiz
    post_ids_json = json.dumps(post_ids)

    async with _pool.acquire() as conn:
        await conn.execute("""
            UPDATE contest
            SET active=$1, winners=$2, post_ids=$3::jsonb
            WHERE id=(SELECT id FROM contest LIMIT 1);
        """, active, winners, post_ids_json)


# ==== SUBS TEKSHIRUV ====
async def is_user_subscribed(bot, user_id: int) -> bool:
    """
    MAIN_CHANNELS bo'sh bo'lsa True qaytaradi.
    Aks holda har bir kanalga a'zolikni tekshiradi.
    """
    if not MAIN_CHANNELS:
        return True
    for ch in MAIN_CHANNELS:
        try:
            member = await bot.get_chat_member(ch, user_id)
            if getattr(member, "status", None) not in ("member", "administrator", "creator"):
                return False
        except Exception:
            return False
    return True


# ==== E'LON & DM ====
async def announce_winners_to_channels(bot, winners: List[int]):
    """
    G'oliblarni MAIN_CHANNELS ga e'lon qiladi.
    return: (ok_soni, fail_soni)
    """
    if not winners:
        return 0, 0

    text = "🏆 <b>Konkurs yakunlandi!</b>\n\nG‘oliblar:\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, uid in enumerate(winners[:3]):
        text += f"{medals[i]} <a href='tg://user?id={uid}'>{uid}</a>\n"

    ok = fail = 0
    for ch in MAIN_CHANNELS:
        try:
            await bot.send_message(ch, text, parse_mode="HTML", disable_web_page_preview=True)
            ok += 1
        except Exception as e:
            print(f"[announce] {ch} -> {e}")
            fail += 1
    return ok, fail


async def dm_winners(bot, winners: List[int]):
    medals = ["🥇", "🥈", "🥉"]
    for i, uid in enumerate(winners[:3]):
        try:
            await bot.send_message(
                uid,
                f"{medals[i]} Tabriklaymiz! Siz g‘olib bo‘ldingiz. 🎉\nAdmin tez orada bog‘lanadi.",
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[dm_winner] {uid} -> {e}")


# ==== HANDLERLAR ====
def register_konkurs_handlers(dp: Dispatcher, bot, ADMINS: set):
    """
    main.py dan:
        from konkurs import register_konkurs_handlers, db_init
        ...
        await db_init()
        register_konkurs_handlers(dp, bot, ADMINS)
    """

    @dp.message_handler(commands=["start"])
    async def cmd_start(message: types.Message):
        args = message.get_args().strip() if hasattr(message, "get_args") else ""
        if args == "konkurs":
            # 1) Obuna tekshiruvi
            subscribed = await is_user_subscribed(message.bot, message.from_user.id)
            if not subscribed:
                await message.answer("❗️ Avval kanallarga obuna bo‘ling, so‘ngra qayta urinib ko‘ring.")
                return

            # 2) Ishtirokchilar bazasiga qo'shish
            await save_participant(message.from_user.id)
            await message.answer("✅ Ishtirok uchun rahmat! Siz ro‘yxatga qo‘shildingiz.")
            return

        await message.answer("Salom! Bu bot konkurslar o‘tkazadi.")

    @dp.message_handler(lambda m: m.text == "🏆 Konkurs")
    async def open_konkurs_menu(message: types.Message):
        if message.from_user.id not in ADMINS:
            return
        st = await load_contest()
        status = "🟢 Faol" if st.get("active") else "🔴 Faol emas"
        winners = st.get("winners", [])
        win_line = f"\nG‘oliblar soni: {len(winners)}" if winners else ""
        await message.answer(f"🏆 Konkurs bo‘limi\nHolat: {status}{win_line}", reply_markup=konkurs_menu_kb())

    @dp.callback_query_handler(lambda c: c.data.startswith("konkurs:"))
    async def konkurs_menu_cb(callback: CallbackQuery, state: FSMContext):
        if callback.from_user.id not in ADMINS:
            await callback.answer()
            return

        _, action = callback.data.split(":", 1)

        if action == "start":
            await KonkursStates.waiting_for_image.set()
            await callback.message.answer("🖼 Konkurs post uchun rasm yuboring.")

        elif action == "participants":
            data = await load_participants()
            ids = data.get("participants", [])
            if not ids:
                await callback.message.answer("ℹ️ Ishtirokchilar yo‘q.")
            else:
                # uzun ro'yxatni bo'laklab yuboramiz
                chunk = "👥 Ishtirokchilar:\n\n"
                for i, uid in enumerate(ids, 1):
                    line = f"{i}. <code>{uid}</code>\n"
                    if len(chunk) + len(line) > 3800:
                        await callback.message.answer(chunk, parse_mode="HTML")
                        chunk = ""
                    chunk += line
                if chunk:
                    await callback.message.answer(chunk, parse_mode="HTML")

        elif action == "finish":
            st = await load_contest()
            st["active"] = False
            await save_contest(st)

            winners = st.get("winners", [])
            if winners:
                ok, fail = await announce_winners_to_channels(callback.message.bot, winners)
                await dm_winners(callback.message.bot, winners)
                await callback.message.answer(f"✅ Konkurs yakunlandi. E’lon: {ok} ta, xato: {fail} ta.")
            else:
                await callback.message.answer("✅ Konkurs yakunlandi (g‘oliblar yo‘q).")

            # Agar yakunda ishtirokchilar ro'yxatini tozalamoqchi bo'lsangiz, quyidagini oching:
            # await clear_participants()

        elif action == "pick":
            st = await load_contest()
            if not st.get("active"):
                await callback.message.answer("ℹ️ Konkurs faol emas.")
                return

            pdata = await load_participants()
            participants = pdata.get("participants", [])
            winners = st.get("winners", [])

            if len(winners) >= 3:
                await callback.message.answer("✅ 3 ta g‘olib tanlangan.")
                return

            candidates = [uid for uid in participants if uid not in winners]
            if not candidates:
                await callback.message.answer("❌ Nomzod qolmadi.")
                return

            winner = random.choice(candidates)
            winners.append(winner)
            st["winners"] = winners
            await save_contest(st)

            medals = ["🥇", "🥈", "🥉"]
            await callback.message.answer(
                f"{medals[len(winners)-1]} G‘olib: <a href='tg://user?id={winner}'>{winner}</a>",
                parse_mode="HTML"
            )

            if len(winners) == 3:
                st["active"] = False
                await save_contest(st)
                ok, fail = await announce_winners_to_channels(callback.message.bot, winners)
                await dm_winners(callback.message.bot, winners)
                await callback.message.answer(f"🏁 Konkurs yakunlandi.\n📣 E’lon: {ok} ta, xato: {fail} ta.")

    @dp.message_handler(content_types=types.ContentType.PHOTO, state=KonkursStates.waiting_for_image)
    async def konkurs_get_image(message: types.Message, state: FSMContext):
        if message.from_user.id not in ADMINS:
            return
        await state.update_data(photo=message.photo[-1].file_id)
        await KonkursStates.waiting_for_caption.set()
        await message.answer("✍️ Endi post matnini yuboring.")

    @dp.message_handler(state=KonkursStates.waiting_for_caption)
    async def konkurs_get_caption_and_post(message: types.Message, state: FSMContext):
        if message.from_user.id not in ADMINS:
            return

        data = await state.get_data()
        photo_id = data.get("photo")
        caption = (message.text or "").strip()

        if not MAIN_CHANNELS:
            await message.answer("❌ MAIN_CHANNELS topilmadi.")
            await state.finish()
            return

        # Konkurs holatini tiklaymiz
        st = await load_contest()
        st["active"] = True
        st["post_ids"] = []
        st["winners"] = []
        await save_contest(st)

        me = await message.bot.get_me()
        kb = participate_kb(me.username)

        ok = fail = 0
        # Har bir kanalga yuboramiz va post_ids ni yig'amiz
        for ch in MAIN_CHANNELS:
            try:
                sent = await message.bot.send_photo(ch, photo=photo_id, caption=caption, reply_markup=kb)
                st = await load_contest()
                post_ids = st.get("post_ids", [])
                post_ids.append({"chat": ch, "message_id": sent.message_id})
                st["post_ids"] = post_ids
                await save_contest(st)
                ok += 1
            except Exception as e:
                print(f"[POST] {ch} -> {e}")
                fail += 1

        await message.answer(f"✅ Yuborildi: {ok} ta\n❌ Xato: {fail} ta\n🟢 Konkurs FAOL")
        await state.finish()
