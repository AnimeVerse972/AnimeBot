import asyncpg
import os
from dotenv import load_dotenv
from datetime import date

load_dotenv()

db_pool = None

# === Databasega ulanish ===
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(
        dsn=os.getenv("DATABASE_URL"),
        statement_cache_size=0
    )

    async with db_pool.acquire() as conn:
        # === Foydalanuvchilar jadvali ===
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # === Kino/anime kodlari jadvali ===
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS kino_codes (
                code SERIAL PRIMARY KEY,
                title TEXT,
                channel TEXT,
                message_id INTEGER,
                post_count INTEGER,
                parts INTEGER,
                status TEXT,
                voice TEXT,
                genres TEXT[],
                video_file_id TEXT,
                caption TEXT
            );
        """)

        # === Statistika jadvali ===
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                code INTEGER PRIMARY KEY REFERENCES kino_codes(code) ON DELETE CASCADE,
                searched INTEGER DEFAULT 0,
                viewed INTEGER DEFAULT 0
            );
        """)

        # === Adminlar jadvali ===
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY
            );
        """)

        # Dastlabki admin qo‘shish
        default_admins = [6486825926]
        for admin_id in default_admins:
            await conn.execute(
                "INSERT INTO admins (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
                admin_id
            )

# === Foydalanuvchilar bilan ishlash ===
async def add_user(user_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id
        )

async def get_db_pool():
    global db_pool
    if db_pool is None:
        await init_db()
    return db_pool

async def get_user_count():
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) FROM users")
        return row[0]

async def get_today_users():
    async with db_pool.acquire() as conn:
        today = date.today()
        row = await conn.fetchrow("""
            SELECT COUNT(*) FROM users WHERE DATE(created_at) = $1
        """, today)
        return row[0] if row else 0

async def get_all_user_ids():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        return [row["user_id"] for row in rows]

# === Kodlar bilan ishlash ===
async def add_kino_code(code, channel, message_id, post_count, title, parts=None, status=None, voice=None, genres=None, video_file_id=None, caption=None):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO kino_codes (code, channel, message_id, post_count, title, parts, status, voice, genres, video_file_id, caption)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            ON CONFLICT (code) DO UPDATE SET
                channel = EXCLUDED.channel,
                message_id = EXCLUDED.message_id,
                post_count = EXCLUDED.post_count,
                title = EXCLUDED.title,
                parts = EXCLUDED.parts,
                status = EXCLUDED.status,
                voice = EXCLUDED.voice,
                genres = EXCLUDED.genres,
                video_file_id = EXCLUDED.video_file_id,
                caption = EXCLUDED.caption;
        """, code, channel, message_id, post_count, title, parts, status, voice, genres, video_file_id, caption)

        # Statistika ham qo‘shiladi
        await conn.execute("""
            INSERT INTO stats (code) VALUES ($1)
            ON CONFLICT DO NOTHING
        """, code)

async def get_kino_by_code(code):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM kino_codes WHERE code=$1", code)
        return dict(row) if row else None

# database.py yoki asosiy modulga qo'shing
async def get_anime_by_code(code: str):
    """
    Kod bo'yicha animeni bazadan olish.
    Natija dict shaklida qaytadi:
    {
        'title': str,
        'season': int,
        'status': str,
        'voice': str,
        'current_part': int,
        'total_parts': int,
        'genres': list[str],
        'file_id': str
    }
    """
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT title, status, voice, parts AS total_parts, genres, video_file_id
            FROM kino_codes
            WHERE code = $1
        """, code)

        if not row:
            return None

        return {
            'title': row['title'],
            'season': 1,  # default qiymat
            'status': row['status'],
            'voice': row['voice'],
            'current_part': 1,  # default qiymat
            'total_parts': row['total_parts'],
            'genres': row['genres'] if row['genres'] else [],
            'file_id': row['video_file_id']
        }

async def get_all_codes():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM kino_codes ORDER BY code")
        return [dict(r) for r in rows]

async def delete_kino_code(code):
    async with db_pool.acquire() as conn:
        result = await conn.execute("DELETE FROM kino_codes WHERE code = $1", code)
        return result.endswith("1")

async def update_anime_code(old_code, new_code, new_title):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE kino_codes SET code = $1, title = $2 WHERE code = $3
        """, new_code, new_title, old_code)

async def get_last_anime_code():
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT code FROM kino_codes ORDER BY code DESC LIMIT 1")
        return row['code'] if row else 0

# === Statistika bilan ishlash ===
async def increment_stat(code, field):
    if field not in ("searched", "viewed"):
        return
    async with db_pool.acquire() as conn:
        await conn.execute(f"""
            UPDATE stats SET {field} = {field} + 1 WHERE code = $1
        """, code)

async def get_code_stat(code):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT searched, viewed FROM stats WHERE code = $1", code)

# === Adminlar bilan ishlash ===
async def get_all_admins():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM admins")
        return {row["user_id"] for row in rows}

async def add_admin(user_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admins (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            user_id
        )

async def remove_admin(user_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM admins WHERE user_id = $1", user_id)
