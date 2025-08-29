# database.py
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

db_pool = None

async def init_db():
    global db_pool
    try:
        # ✅ Pool yaratish
        db_pool = await asyncpg.create_pool(
            dsn=os.getenv("DATABASE_URL"),
            statement_cache_size=0
        )
        print("✅ PostgreSQL bazaga ulandi!")
    except Exception as e:
        print(f"❌ DB ulanishda xato: {e}")
        raise

    async with db_pool.acquire() as conn:
        # === Foydalanuvchilar ===
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # === Kino kodlari ===
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS kino_codes (
                code SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
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

        # === Statistika ===
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                code INTEGER PRIMARY KEY REFERENCES kino_codes(code) ON DELETE CASCADE,
                searched INTEGER DEFAULT 0,
                viewed INTEGER DEFAULT 0
            );
        """)

        # === Adminlar ===
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY
            );
        """)

        # Dastlabki admin
        default_admin = 6486825926
        await conn.execute(
            "INSERT INTO admins (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            default_admin
        )

async def get_db_pool():
    global db_pool
    if db_pool is None:
        await init_db()
    return db_pool

# === Foydalanuvchilar ===
async def add_user(user_id: int):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            user_id
        )

async def get_user_count():
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) FROM users")
        return row[0] if row else 0

async def get_anime_by_code(code: str):
    if not code.isdigit():
        return None
    code = int(code)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT title, status, voice, parts AS total_parts, genres, video_file_id
            FROM kino_codes WHERE code = $1
        """, code)
        if not row:
            return None
        return {
            'title': row['title'],
            'season': 1,
            'status': row['status'],
            'voice': row['voice'],
            'current_part': 1,
            'total_parts': row['total_parts'],
            'genres': row['genres'] or [],
            'file_id': row['video_file_id']
        }

async def get_today_users():
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT COUNT(*) FROM users WHERE DATE(created_at) = CURRENT_DATE
        """)
        return row[0] if row else 0

async def get_all_user_ids():
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        return [r['user_id'] for r in rows]

# === Kino kodlari ===
async def add_kino_code(code: int, channel: str, message_id: int, post_count: int,
                        title: str, parts: int = None, status: str = None,
                        voice: str = None, genres: list = None,
                        video_file_id: str = None, caption: str = None):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO kino_codes (code, channel, message_id, post_count, title, parts, status, voice, genres, video_file_id, caption)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
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
                caption = EXCLUDED.caption
        """, code, channel, message_id, post_count, title, parts, status, voice, genres, video_file_id, caption)

        await conn.execute("""
            INSERT INTO stats (code) VALUES ($1) ON CONFLICT DO NOTHING
        """, code)

async def get_kino_by_code(code: int):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM kino_codes WHERE code = $1", code)
        return dict(row) if row else None

# ✅ YANGI: get_anime_by_code — main.py da ishlatiladi
async def get_anime_by_code(code: str):
    """
    Kod bo'yicha animeni olish.
    main.py dagi send_anime_handler uchun.
    """
    if not code.isdigit():
        return None
    code = int(code)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT title, status, voice, parts AS total_parts, genres, video_file_id
            FROM kino_codes WHERE code = $1
        """, code)
        if not row:
            return None
        return {
            'title': row['title'],
            'season': 1,
            'status': row['status'],
            'voice': row['voice'],
            'current_part': 1,
            'total_parts': row['total_parts'],
            'genres': row['genres'] or [],
            'file_id': row['video_file_id']
        }

async def get_all_codes():
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM kino_codes ORDER BY code")
        return [dict(r) for r in rows]

async def delete_kino_code(code: int):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM kino_codes WHERE code = $1", code)
        return "1" in res

async def update_anime_code(old_code: int, new_code: int, new_title: str):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE kino_codes SET code = $1, title = $2 WHERE code = $3
        """, new_code, new_title, old_code)

async def get_last_anime_code():
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT MAX(code) FROM anime_codes")
        return row['max'] if row['max'] is not None else 0

# === Statistika ===
async def increment_stat(code: int, field: str):
    if field not in ("searched", "viewed"):
        return
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(f"UPDATE stats SET {field} = {field} + 1 WHERE code = $1", code)

async def get_code_stat(code: int):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT searched, viewed FROM stats WHERE code = $1", code)

# === Adminlar ===
async def get_all_admins():
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM admins")
        return {r['user_id'] for r in rows}

async def add_admin(user_id: int):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admins (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            user_id
        )

async def remove_admin(user_id: int):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM admins WHERE user_id = $1", user_id)
