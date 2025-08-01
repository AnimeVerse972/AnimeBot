# database.py
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

db_pool = None

# === Foydalanuvchilar jadvali ===
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        database=os.getenv("DB_NAME"),
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT"))
    )

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

        # Adminlar jadvali
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY
            );
        """)

        # Dastlabki adminlar (o'z IDlaringizni qo'shing)
        default_admins = [6486825926, 7711928526]
        for admin_id in default_admins:
            await conn.execute(
                "INSERT INTO admins (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
                admin_id
            )


# === Foydalanuvchi qo'shish ===
async def add_user(user_id):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id
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

# === Kodni o'chirish (TUZATILGAN) ===
async def delete_kino_code(code):
    async with db_pool.acquire() as conn:
        # Avval stats jadvalidan o'chirish
        await conn.execute("DELETE FROM stats WHERE code = $1", code)
        # So'ng kino_codes jadvalidan o'chirish
        result = await conn.execute("DELETE FROM kino_codes WHERE code = $1", code)
        # asyncpg da natija "DELETE 1" ko'rinishida qaytadi
        return result.split()[-1] == "1"

# === Statistika yangilash (TUZATILGAN - SQL injection himoyasi) ===
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
            # SQL injection himoyasi uchun explicit field nomlari
            if field == "searched":
                await conn.execute("""
                    UPDATE stats SET searched = searched + 1 WHERE code = $1
                """, code)
            elif field == "viewed":
                await conn.execute("""
                    UPDATE stats SET viewed = viewed + 1 WHERE code = $1
                """, code)

# === Kod statistikasi olish ===
async def get_code_stat(code):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT searched, viewed FROM stats WHERE code = $1", code)
        return dict(row) if row else None

# === Kod va nomni yangilash (TUZATILGAN - stats bilan sinxronlash) ===
async def update_anime_code(old_code, new_code, new_title):
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            # Kino kodini yangilash
            await conn.execute("""
                UPDATE kino_codes SET code = $1, title = $2 WHERE code = $3
            """, new_code, new_title, old_code)
            
            # Stats jadvalida ham kod nomini yangilash
            await conn.execute("""
                UPDATE stats SET code = $1 WHERE code = $2
            """, new_code, old_code)

# === Barcha foydalanuvchi IDlarini olish ===
async def get_all_user_ids():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        return [row["user_id"] for row in rows]

# === Barcha adminlarni olish (YANGILANGAN) ===
async def get_all_admins():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM admins")
        return {row["user_id"] for row in rows}

# === Admin tekshirish (YANGI) ===
async def is_admin(user_id: int):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id FROM admins WHERE user_id = $1", user_id)
        return row is not None

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
        result = await conn.execute("DELETE FROM admins WHERE user_id = $1", user_id)
        return result.split()[-1] == "1"

# === Database dan adminlarni olish va global ADMINS ni sinxronlash (YANGI) ===
async def sync_admins_with_db():
    """Database dan adminlarni olib, global ADMINS set ni yangilaydi"""
    return await get_all_admins()

# === Barcha ma'lumotlarni o'chirish (development uchun) ===
async def clear_all_data():
    """EHTIYOT: Barcha ma'lumotlarni o'chiradi!"""
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM stats")
        await conn.execute("DELETE FROM kino_codes") 
        await conn.execute("DELETE FROM users")
        # Adminlarni o'chirmaymiz
        
# === Database holati haqida ma'lumot ===
async def get_db_info():
    """Database haqida umumiy ma'lumot"""
    async with db_pool.acquire() as conn:
        users_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        codes_count = await conn.fetchval("SELECT COUNT(*) FROM kino_codes")
        admins_count = await conn.fetchval("SELECT COUNT(*) FROM admins")
        
        return {
            "users": users_count,
            "codes": codes_count, 
            "admins": admins_count
        }
