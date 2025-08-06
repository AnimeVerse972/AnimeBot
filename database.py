# database.py
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

db_pool = None
ADMINS_CACHE = set()  # RAM da adminlar

async def init_db():
    """
    Barcha jadvallarni yaratadi va adminlarni RAMga yuklaydi.
    """
    global db_pool, ADMINS_CACHE
    db_pool = await asyncpg.create_pool(os.getenv("DATABASE_URL"))

    async with db_pool.acquire() as conn:
        # === Asosiy jadvallar (mavjud loyihangdan) ===
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS kino_codes (
                code TEXT PRIMARY KEY,
                channel TEXT,
                message_id INTEGER,
                post_count INTEGER,
                title TEXT
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                code TEXT PRIMARY KEY,
                searched INTEGER DEFAULT 0
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY
            );
        """)

        # === Konkurs uchun jadvallar ===
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS participants (
                user_id BIGINT PRIMARY KEY
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contest (
                id SERIAL PRIMARY KEY,
                active BOOLEAN DEFAULT FALSE,
                winners BIGINT[] DEFAULT '{}',
                post_ids JSONB DEFAULT '[]'::jsonb
            );
        """)

        # contest jadvalida kamida bitta satr bo‘lsin
        row = await conn.fetchrow("SELECT id FROM contest LIMIT 1;")
        if not row:
            await conn.execute("INSERT INTO contest (active, winners, post_ids) VALUES (FALSE, '{}', '[]');")

        # Adminlarni boshlang'ich to'ldirish va RAMga yuklash
        default_admins = [6486825926, 7711928526]
        await conn.executemany(
            "INSERT INTO admins (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            [(admin_id,) for admin_id in default_admins]
        )
        rows = await conn.fetch("SELECT user_id FROM admins")
        ADMINS_CACHE = {row["user_id"] for row in rows}

# ======= Umumiy foydalanuvchi funksiyalari =======
async def add_user(user_id):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id
        )

async def get_user_count():
    async with db_pool.acquire() as conn:
        return (await conn.fetchval("SELECT COUNT(*) FROM users"))

# ======= Kino code (mavjud loyihang) =======
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

async def get_kino_by_code(code):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT code, channel, message_id, post_count, title
            FROM kino_codes
            WHERE code = $1
        """, code)
        return dict(row) if row else None

async def get_all_codes():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT code, title FROM kino_codes")
        return [{"code": r["code"], "title": r["title"]} for r in rows]

async def delete_kino_code(code):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM stats WHERE code = $1", code)
        res = await conn.execute("DELETE FROM kino_codes WHERE code = $1", code)
        return res  # masalan "DELETE 1"

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

async def get_code_stat(code):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT searched FROM stats WHERE code = $1", code)

async def update_anime_code(old_code, new_code, new_title):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE kino_codes SET code = $1, title = $2 WHERE code = $3
        """, new_code, new_title, old_code)

async def get_all_user_ids():
    async with db_pool.acquire() as conn:
        return [r["user_id"] for r in await conn.fetch("SELECT user_id FROM users")]

# ======= Adminlar =======
def get_all_admins():
    return ADMINS_CACHE

async def add_admin(user_id: int):
    global ADMINS_CACHE
    ADMINS_CACHE.add(user_id)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admins (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            user_id
        )

async def remove_admin(user_id: int):
    global ADMINS_CACHE
    ADMINS_CACHE.discard(user_id)
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM admins WHERE user_id = $1", user_id)

# ======= KONKURS: participants & contest =======
async def add_participant(user_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO participants (user_id) VALUES ($1)
            ON CONFLICT (user_id) DO NOTHING;
        """, user_id)

async def get_participants():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM participants ORDER BY user_id;")
        return [r["user_id"] for r in rows]

async def reset_participants():
    async with db_pool.acquire() as conn:
        await conn.execute("TRUNCATE participants;")

async def get_contest():
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT active, winners, post_ids FROM contest LIMIT 1;")
        if not row:
            return {"active": False, "winners": [], "post_ids": []}
        return {
            "active": row["active"],
            "winners": list(row["winners"] or []),
            "post_ids": row["post_ids"] or []
        }

async def save_contest(active: bool = None, winners=None, post_ids=None):
    """
    Berilgan maydonlargina yangilanadi.
    """
    # joriy holatni olib, diff qo'llaymiz
    current = await get_contest()
    if active is None:
        active = current["active"]
    if winners is None:
        winners = current["winners"]
    if post_ids is None:
        post_ids = current["post_ids"]

    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE contest
            SET active=$1, winners=$2, post_ids=$3::jsonb
            WHERE id=(SELECT id FROM contest LIMIT 1);
        """, bool(active), list(winners), json_serialize(post_ids))

def json_serialize(value):
    import json
    return json.dumps(value)
