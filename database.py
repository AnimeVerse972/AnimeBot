# database.py
import os
import ssl
from dotenv import load_dotenv
from tortoise import Tortoise, fields
from tortoise.models import Model

load_dotenv()

ADMINS_CACHE = set()  # RAM cache

# ==== MODELLAR ====

class User(Model):
    user_id = fields.BigIntField(pk=True)

class KinoCode(Model):
    code = fields.CharField(max_length=255, pk=True)
    channel = fields.CharField(max_length=255, null=True)
    message_id = fields.IntField(null=True)
    post_count = fields.IntField(default=0)
    title = fields.CharField(max_length=255, null=True)

class Stats(Model):
    code = fields.CharField(max_length=255, pk=True)
    searched = fields.IntField(default=0)

class Admin(Model):
    user_id = fields.BigIntField(pk=True)


# ==== INIT DB ====
async def init_db():
    global ADMINS_CACHE

    db_url = os.getenv("DATABASE_URL")

    # Neon.tech SSL sozlamalari
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    await Tortoise.init(
        db_url=db_url.replace("postgresql://", "postgres://", 1),
        modules={"models": ["database"]},
        connection_params={"ssl": ssl_context}
    )

    await Tortoise.generate_schemas()

    # Default adminlar qo‘shish
    default_admins = [6486825926, 7711928526]
    for admin_id in default_admins:
        await Admin.get_or_create(user_id=admin_id)

    # RAM cache yangilash
    admins = await Admin.all().values_list("user_id", flat=True)
    ADMINS_CACHE = set(admins)
    print("Database connected ✅")


# ==== FUNKSIYALAR ====

async def add_user(user_id):
    await User.get_or_create(user_id=user_id)

async def get_user_count():
    return await User.all().count()

async def add_kino_code(code, channel, message_id, post_count, title):
    await KinoCode.update_or_create(
        defaults={
            "channel": channel,
            "message_id": message_id,
            "post_count": post_count,
            "title": title
        },
        code=code
    )
    await Stats.get_or_create(code=code)

async def get_kino_by_code(code):
    kino = await KinoCode.filter(code=code).first()
    return kino.__dict__ if kino else None

async def get_all_codes():
    return await KinoCode.all().values("code", "title")

async def delete_kino_code(code):
    await Stats.filter(code=code).delete()
    deleted_count = await KinoCode.filter(code=code).delete()
    return deleted_count > 0

async def increment_stat(code, field):
    if field not in ("searched", "init"):
        return
    if field == "init":
        await Stats.get_or_create(code=code)
    else:
        await Stats.filter(code=code).update(
            **{field: fields.F(field) + 1}
        )

async def get_code_stat(code):
    return await Stats.filter(code=code).first()

async def update_anime_code(old_code, new_code, new_title):
    await KinoCode.filter(code=old_code).update(code=new_code, title=new_title)

async def get_all_user_ids():
    return await User.all().values_list("user_id", flat=True)

def get_all_admins():
    return ADMINS_CACHE

async def add_admin(user_id: int):
    global ADMINS_CACHE
    await Admin.get_or_create(user_id=user_id)
    ADMINS_CACHE.add(user_id)

async def remove_admin(user_id: int):
    global ADMINS_CACHE
    await Admin.filter(user_id=user_id).delete()
    ADMINS_CACHE.discard(user_id)
