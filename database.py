import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

async def init_db():
    """Ma'lumotlar bazasini ishga tushirish"""
    conn = await asyncpg.connect(DATABASE_URL)
    
    # Foydalanuvchilar jadvali
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    
    # Kino kodlari jadvali
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS kino_codes (
            code TEXT PRIMARY KEY,
            channel TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            post_count INTEGER NOT NULL,
            title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    
    # Statistika jadvali
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS stats (
            code TEXT,
            stat_type TEXT,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (code, stat_type)
        )
    ''')
    
    await conn.close()

async def add_user(user_id):
    """Yangi foydalanuvchi qo'shish"""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            "INSERT INTO users (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING",
            user_id
        )
    finally:
        await conn.close()

async def get_user_count():
    """Foydalanuvchilar sonini olish"""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        count = await conn.fetchval("SELECT COUNT(*) FROM users")
        return count
    finally:
        await conn.close()

async def add_kino_code(code, channel, message_id, post_count, title):
    """Yangi kino kodi qo'shish"""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            "INSERT INTO kino_codes (code, channel, message_id, post_count, title) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (code) DO UPDATE SET channel = $2, message_id = $3, post_count = $4, title = $5",
            code, channel, message_id, post_count, title
        )
    finally:
        await conn.close()

async def get_kino_by_code(code):
    """Kod bo'yicha kino ma'lumotlarini olish"""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow(
            "SELECT channel, message_id, post_count, title FROM kino_codes WHERE code = $1",
            code
        )
        if row:
            return {
                "channel": row["channel"],
                "message_id": row["message_id"],
                "post_count": row["post_count"],
                "title": row["title"]
            }
        return None
    finally:
        await conn.close()

async def get_all_codes():
    """Barcha kodlar ro'yxatini olish"""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch("SELECT code, title FROM kino_codes ORDER BY code")
        return [{"code": row["code"], "title": row["title"]} for row in rows]
    finally:
        await conn.close()

async def delete_kino_code(code):
    """Kino kodini o'chirish"""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        result = await conn.execute("DELETE FROM kino_codes WHERE code = $1", code)
        # Statistika jadvalidan ham o'chirish
        await conn.execute("DELETE FROM stats WHERE code = $1", code)
        return result != "DELETE 0"
    finally:
        await conn.close()

async def get_code_stat(code):
    """Kod statistikasini olish"""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch("SELECT stat_type, count FROM stats WHERE code = $1", code)
        if not rows:
            return None
        
        stats = {}
        for row in rows:
            stats[row["stat_type"]] = row["count"]
        
        return {
            "searched": stats.get("searched", 0),
            "viewed": stats.get("viewed", 0)
        }
    finally:
        await conn.close()

async def increment_stat(code, stat_type):
    """Statistikani oshirish"""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            "INSERT INTO stats (code, stat_type, count) VALUES ($1, $2, 1) ON CONFLICT (code, stat_type) DO UPDATE SET count = stats.count + 1",
            code, stat_type
        )
    finally:
        await conn.close()

async def get_all_user_ids():
    """Barcha foydalanuvchi ID larini olish"""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch("SELECT user_id FROM users")
        return [row["user_id"] for row in rows]
    finally:
        await conn.close()

async def update_anime_code(old_code, new_code, new_title):
    """Anime kodini va nomini yangilash"""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Avval eski kod mavjudligini tekshirish
        exists = await conn.fetchval("SELECT 1 FROM kino_codes WHERE code = $1", old_code)
        if not exists:
            raise Exception("Eski kod topilmadi!")
        
        # Yangi kod allaqachon mavjud emasligini tekshirish (agar old_code != new_code bo'lsa)
        if old_code != new_code:
            exists = await conn.fetchval("SELECT 1 FROM kino_codes WHERE code = $1", new_code)
            if exists:
                raise Exception("Yangi kod allaqachon mavjud!")
        
        # Transaksiya ichida yangilash
        async with conn.transaction():
            # Kino kodini yangilash
            await conn.execute(
                "UPDATE kino_codes SET code = $1, title = $2 WHERE code = $3",
                new_code, new_title, old_code
            )
            
            # Agar kod o'zgargan bo'lsa, statistikani ham yangilash
            if old_code != new_code:
                await conn.execute(
                    "UPDATE stats SET code = $1 WHERE code = $2",
                    new_code, old_code
                )
                
    finally:
        await conn.close()

# ✅ YANGI FUNKSIYA: Anime nomini qidirish
async def search_anime_by_name(search_query):
    """Anime nomini qidirish (ILIKE operatori bilan)"""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # ILIKE operatori bilan qidirish (case-insensitive)
        query = f"%{search_query.lower()}%"
        rows = await conn.fetch(
            "SELECT code, title FROM kino_codes WHERE LOWER(title) LIKE $1 ORDER BY title",
            query
        )
        return [{"code": row["code"], "title": row["title"]} for row in rows]
    finally:
        await conn.close()
