import asyncio
import aiosqlite
import logging
import sys
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.client.bot import DefaultBotProperties
from aiogram.types import LabeledPrice, PreCheckoutQuery
from aiohttp import web

# --- НАСТРОЙКИ ---
TOKEN = '8725627105:AAFgdBu8u-AYlHRaGtFLUP12uvqGDJRsuco'
ADMIN_ID = 6907295206 
DEV_USERNAME = "@redperr"

# Ссылки на картинки
START_PIC = "https://i.postimg.cc/3NbWzvGj/Frame_1187517897.png"
ADMIN_PIC = "https://i.postimg.cc/FzK7PZYd/Frame-1187517898.png"

# Логирование для Render (чтобы видеть ошибки в панели)
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())

class MyStates(StatesGroup):
    waiting_for_ban = State()
    waiting_for_unban = State()

# Путь к базе данных
DB_PATH = '/data/bot_data.db' if os.path.exists('/data') else 'bot_data.db'

# --- ИНИЦИАЛИЗАЦИЯ БД ---
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS videos 
                            (id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT, owner_id INTEGER)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
                            (user_id INTEGER PRIMARY KEY, username TEXT, views_left INTEGER DEFAULT 0, is_blocked INTEGER DEFAULT 0)''')
        await db.commit()

# --- КЛАВИАТУРЫ ---
def get_start_kb():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="💎 Поддержать автора (5 ⭐)", callback_data="buy_stars"))
    return builder.as_markup()

def get_admin_kb():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats"))
    builder.row(
        types.InlineKeyboardButton(text="🚫 Бан", callback_data="adm_ban_start"),
        types.InlineKeyboardButton(text="🔓 Разбан", callback_data="adm_unban_start")
    )
    builder.row(types.InlineKeyboardButton(text="🧹 Очистить базу", callback_data="adm_clear"))
    return builder.as_markup()

def get_video_actions(video_id):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="❤️", callback_data="next_video"), types.InlineKeyboardButton(text="❌", callback_data="next_video"))
    builder.row(types.InlineKeyboardButton(text="💬 Коммент", callback_data=f"add_comm_{video_id}"), types.InlineKeyboardButton(text="🚩 Жалоба", callback_data=f"report_{video_id}"))
    return builder.as_markup()

# --- ОБРАБОТКА КРУЖКОВ ---
@dp.message(F.video_note)
async def handle_video(message: types.Message):
    uid = message.from_user.id
    un = (message.from_user.username or "none").lower()
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_blocked FROM users WHERE user_id = ?", (uid,)) as cur:
            res = await cur.fetchone()
            if res and res[0]: return

        # Сохраняем видео и даем 3 просмотра
        await db.execute("INSERT INTO videos (file_id, owner_id) VALUES (?, ?)", (message.video_note.file_id, uid))
        await db.execute("INSERT OR REPLACE INTO users (user_id, username, views_left, is_blocked) VALUES (?, ?, 3, 0)", (uid, un))
        await db.commit()
        
        async with db.execute("SELECT id, file_id FROM videos WHERE owner_id != ? ORDER BY RANDOM() LIMIT 1", (uid,)) as cur:
            ans = await cur.fetchone()
        
        if ans:
            await message.answer_video_note(ans[1], reply_markup=get_video_actions(ans[0]))
        else:
            await message.answer("📽 <b>Кружок сохранен!</b> Ты первый автор в базе. Как только кто-то другой запишет кружок, ты его получишь!")

# --- КОМАНДЫ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    un = (message.from_user.username or "none").lower()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (uid, un))
        await db.commit()
    
    # ТВОЕ НАЧАЛЬНОЕ СООБЩЕНИЕ
    caption = (
        f"🌟 <b>Привет, {message.from_user.first_name}!</b>\n\n"
        "Запиши кружок — получишь случайный в ответ!\n\n"
        "💡 <b>Правила:</b>\n"
        "— За 1 свой кружок ты получаешь 3 просмотра.\n"
        "— Никакого спама и запрещенки.\n\n"
        "Жду твой кружок! 👇"
    )
    try:
        await message.answer_photo(photo=START_PIC, caption=caption, reply_markup=get_start_kb())
    except:
        await message.answer(caption, reply_markup=get_start_kb())

@dp.message(Command("admin"))
async def open_admin(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        try:
            await message.answer_photo(photo=ADMIN_PIC, caption="🛠 <b>АДМИН-ПАНЕЛЬ</b>", reply_markup=get_admin_kb())
        except:
            await message.answer("🛠 <b>АДМИН-ПАНЕЛЬ</b>", reply_markup=get_admin_kb())

# --- ЛОГИКА ---
@dp.callback_query(F.data == "next_video")
async def next_v(call: types.CallbackQuery):
    uid = call.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_blocked, views_left FROM users WHERE user_id = ?", (uid,)) as cur:
            res = await cur.fetchone()
            if not res or res[0] or (res[1] <= 0 and uid != ADMIN_ID):
                return await call.answer("🔋 Лимит! Запиши новый кружок!", show_alert=True)
        
        async with db.execute("SELECT id, file_id FROM videos WHERE owner_id != ? ORDER BY RANDOM() LIMIT 1", (uid,)) as cur:
            ans = await cur.fetchone()
        
        if ans:
            if uid != ADMIN_ID:
                await db.execute("UPDATE users SET views_left = views_left - 1 WHERE user_id = ?", (uid,))
                await db.commit()
            await call.message.answer_video_note(ans[1], reply_markup=get_video_actions(ans[0]))
        else:
            await call.answer("Кружков пока нет...", show_alert=True)
    await call.answer()

# Админ-функции
@dp.callback_query(F.data == "adm_ban_start")
async def ban_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Введите username (без @) для бана:")
    await state.set_state(MyStates.waiting_for_ban)

@dp.message(MyStates.waiting_for_ban)
async def ban_proc(message: types.Message, state: FSMContext):
    target = message.text.replace("@", "").lower().strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_blocked = 1 WHERE username = ?", (target,))
        await db.commit()
    await message.answer(f"🚫 {target} забанен.")
    await state.clear()

@dp.callback_query(F.data == "adm_stats")
async def adm_stats(call: types.CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM videos") as c1: v = (await c1.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users") as c2: u = (await c2.fetchone())[0]
    await call.message.answer(f"📈 Кружков: {v}\n👤 Юзеров: {u}")
    await call.answer()

# Донат
@dp.callback_query(F.data == "buy_stars")
async def buy(call: types.CallbackQuery):
    await bot.send_invoice(call.from_user.id, "Поддержка", "Донат 5 звезд", "pay", "XTR", [LabeledPrice("Цена", 5)])
    await call.answer()

@dp.pre_checkout_query()
async def pre(q: PreCheckoutQuery):
    await q.answer(ok=True)

# Веб-сервер для Render
async def handle_ping(request):
    return web.Response(text="OK")

async def start_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()

async def main():
    await init_db()
    asyncio.create_task(start_server())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
