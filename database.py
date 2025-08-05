import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

db_pool = None

# === Asosiy jadvallarni yaratish va ulanish ===
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(os.getenv("DATABASE_URL"))

    async with db_pool.acquire() as conn:
        # Foydalanuvchilar
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY
            );
        """)
        # Anime kodlari
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS kino_codes (
                code TEXT PRIMARY KEY,
                channel TEXT,
                message_id INTEGER,
                post_count INTEGER,
                title TEXT
            );
        """)
        # Statistika
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                code TEXT PRIMARY KEY,
                searched INTEGER DEFAULT 0,
                viewed INTEGER DEFAULT 0
            );
        """)
        # Adminlar
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY
            );
        """)

        # Dastlabki adminlar
        default_admins = [6486825926, 7711928526]
        for admin_id in default_admins:
            await conn.execute(
                "INSERT INTO admins (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
                admin_id
            )
        # === KONKURS JADVALLARI ===
        # Konkurslar
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contests (
                id SERIAL PRIMARY KEY,
                status TEXT CHECK (status IN ('active', 'finished')) DEFAULT 'active',
                message_text TEXT,
                photo_id TEXT,
                started_at TIMESTAMP DEFAULT NOW(),
                finished_at TIMESTAMP
            );
        """)

        # Qatnashuvchilar
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contest_participants (
                user_id BIGINT PRIMARY KEY,
                referrals INTEGER DEFAULT 0 CHECK (referrals >= 0),
                joined_at TIMESTAMP DEFAULT NOW()
            );
        """)

# === Foydalanuvchi qo'shish ===
async def add_user(user_id):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            user_id
        )

# === Foydalanuvchilar soni ===
async def get_user_count():
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) FROM users")
        return row[0]

# === Kod qo'shish ===
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
        return [{"code": row["code"], "title": row["title"]} for row in rows]

# === Kodni o'chirish ===
async def delete_kino_code(code):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM stats WHERE code = $1", code)
        result = await conn.execute("DELETE FROM kino_codes WHERE code = $1", code)
        return result.endswith("1")

# === Statistika yangilash ===
async def increment_stat(code, field):
    if field not in ("searched", "viewed", "init"):
        return
    async with db_pool.acquire() as conn:
        if field == "init":
            await conn.execute("""
                INSERT INTO stats (code, searched, viewed) VALUES ($1, 0, 0)
                ON CONFLICT DO NOTHING
            """, code)
        else:
            await conn.execute(f"""
                UPDATE stats SET {field} = {field} + 1 WHERE code = $1
            """, code)

# === Kod statistikasi olish ===
async def get_code_stat(code):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT searched, viewed FROM stats WHERE code = $1", code)

# === Kod va nomni yangilash ===
async def update_anime_code(old_code, new_code, new_title):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE kino_codes SET code = $1, title = $2 WHERE code = $3
        """, new_code, new_title, old_code)

# === Barcha foydalanuvchi IDlarini olish ===
async def get_all_user_ids():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        return [row["user_id"] for row in rows]

# === Barcha adminlarni olish ===
async def get_all_admins():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM admins")
        return {row["user_id"] for row in rows}

# === Yangi admin qo'shish ===
async def add_admin(user_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admins (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            user_id
        )

# === Adminni o'chirish ===
async def remove_admin(user_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM admins WHERE user_id = $1", user_id)

# === KONKURS UCHUN QO'SHIMCHA FUNKSIYALAR ===
# === Konkursni boshlash ===
async def start_contest(message_text: str, photo_id: str):
    async with db_pool.acquire() as conn:
        # Barcha aktiv konkurslarni tugatish
        await conn.execute("UPDATE contests SET status = 'finished', finished_at = NOW() WHERE status = 'active'")
        # Yangi konkursni boshlash
        await conn.execute("""
            INSERT INTO contests (status, message_text, photo_id)
            VALUES ('active', $1, $2)
        """, message_text, photo_id)

# === Joriy konkursni olish ===
async def get_active_contest():
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT message_text, photo_id
            FROM contests
            WHERE status = 'active'
            LIMIT 1
        """)
        return dict(row) if row else None

# === Konkursni tugatish ==
async def finish_contest():
    async with db_pool.acquire() as conn:
        result = await conn.execute("UPDATE contests SET status = 'finished', finished_at = NOW() WHERE status = 'active'")
        await conn.execute("DELETE FROM contest_participants")
        return "UPDATE 1" in str(result)

# === Qatnashuvchini qo'shish ===
async def add_contest_participant(user_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO contest_participants (user_id, referrals)
            VALUES ($1, 0)
            ON CONFLICT (user_id) DO NOTHING
        """, user_id)

# === Taklif qilganlar sonini oshirish ===
async def increment_referral(inviter_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO contest_participants (user_id, referrals)
            VALUES ($1, 1)
            ON CONFLICT (user_id) DO UPDATE SET referrals = contest_participants.referrals + 1
        """, inviter_id)

# === Foydalanuvchining takliflari soni ===
async def get_user_referrals(user_id: int) -> int:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT referrals FROM contest_participants WHERE user_id = $1
        """, user_id)
        return row['referrals'] if row else 0

# === Top 10 qatnashuvchilarni olish ===
async def get_top_participants(limit: int = 10):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT user_id, referrals
            FROM contest_participants
            ORDER BY referrals DESC, joined_at ASC
            LIMIT $1
        """, limit)
        return [{"user_id": r["user_id"], "referrals": r["referrals"]} for r in rows]

# === Barcha qatnashuvchilarni olish (random uchun) ===
async def get_all_participants():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM contest_participants")
        return [r["user_id"] for r in rows]
