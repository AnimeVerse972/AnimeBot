# database.py
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

db_pool = None
ADMINS_CACHE = set()  # RAM da adminlar

# === Foydalanuvchilar jadvali ===
async def init_db():
    global db_pool, ADMINS_CACHE
    db_pool = await asyncpg.create_pool(os.getenv("DATABASE_URL"))

    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS kino_codes (
                code TEXT PRIMARY KEY,
                channel TEXT,
                message_id INTEGER,
                post_count INTEGER,
                title TEXT
            );
            CREATE TABLE IF NOT EXISTS stats (
                code TEXT PRIMARY KEY,
                searched INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS channels (
                id BIGINT PRIMARY KEY,
                title TEXT,
                username TEXT
            );
        """)

        # Adminlarni yuklash
        default_admins = [6486825926, 7711928526]
        await conn.executemany(
            "INSERT INTO admins (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            [(admin_id,) for admin_id in default_admins]
        )
        rows = await conn.fetch("SELECT user_id FROM admins")
        ADMINS_CACHE = {row["user_id"] for row in rows}

# === Foydalanuvchi qo'shish ===
async def add_user(user_id):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id
        )

# === Foydalanuvchilar soni ===
async def get_user_count():
    async with db_pool.acquire() as conn:
        return (await conn.fetchval("SELECT COUNT(*) FROM users"))

# === Kod qo‘shish ===
async def add_kino_code(code, channel, message_id, post_count, title):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO kino_codes (code, channel, message_id, post_count, title)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (code) DO UPDATE SET
                channel = EXCLUDED.channel,
                message_id = EXCLUDED.message_id,
                post_count = EXCLUDED.post_count,
                title = EXCLUDED.title;
        """, code, channel, message_id, post_count, title)
        await conn.execute("""
            INSERT INTO stats (code) VALUES ($1)
            ON CONFLICT DO NOTHING
        """, code)

# === Kodni olish ===
async def get_kino_by_code(code):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT code, channel, message_id, post_count, title
            FROM kino_codes
            WHERE code = $1
        """, code)
        return dict(row) if row else None

# === Barcha kodlarni olish ===
async def get_all_codes():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT code, title FROM kino_codes")
        return [{"code": r["code"], "title": r["title"]} for r in rows]

# === Kodni o'chirish ===
async def delete_kino_code(code):
    async with db_pool.acquire() as conn:
        result = await conn.execute("""
            BEGIN;
            DELETE FROM stats WHERE code = $1;
            DELETE FROM kino_codes WHERE code = $1;
            COMMIT;
        """, code)
        return "DELETE" in result

# === Statistika yangilash ===
async def increment_stat(code, field):
    if field not in ("searched", "init"):
        return
    async with db_pool.acquire() as conn:
        if field == "init":
            await conn.execute(
                "INSERT INTO stats (code, searched) VALUES ($1, 0) ON CONFLICT DO NOTHING",
                code
            )
        else:
            await conn.execute(
                f"UPDATE stats SET {field} = {field} + 1 WHERE code = $1", code
            )

# === Kod statistikasi olish ===
async def get_code_stat(code):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT searched FROM stats WHERE code = $1", code)

# === Kod va nomni yangilash ===
async def update_anime_code(old_code, new_code, new_title):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE kino_codes SET code = $1, title = $2 WHERE code = $3
        """, new_code, new_title, old_code)

# === Barcha foydalanuvchi IDlarini olish ===
async def get_all_user_ids():
    async with db_pool.acquire() as conn:
        return [r["user_id"] for r in await conn.fetch("SELECT user_id FROM users")]

# === Admin RAM dan olish ===
def get_all_admins():
    return ADMINS_CACHE

# === Admin qo'shish ===
async def add_admin(user_id: int):
    global ADMINS_CACHE
    ADMINS_CACHE.add(user_id)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admins (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            user_id
        )

# === Adminni o'chirish ===
async def remove_admin(user_id: int):
    global ADMINS_CACHE
    ADMINS_CACHE.discard(user_id)
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM admins WHERE user_id = $1", user_id)

# =========================
# 📢 Kanallar jadvali uchun funksiyalar
# =========================

async def add_channel_to_db(channel_id: int, title: str, username: str):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO channels (id, title, username)
            VALUES ($1, $2, $3)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                username = EXCLUDED.username
        """, channel_id, title, username)

async def remove_channel_from_db(channel_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM channels WHERE id = $1", channel_id)

async def get_all_channels():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, title, username FROM channels")
        return [{"id": r["id"], "title": r["title"], "username": r["username"]} for r in rows]
