import asyncio
import aiosqlite
import logging
import sys
import os
import random
from datetime import datetime
from typing import Union, Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.client.bot import DefaultBotProperties
from aiogram.types import LabeledPrice, PreCheckoutQuery, Message, CallbackQuery
from aiohttp import web

# ==========================================
# КРИТИЧЕСКИЕ НАСТРОЙКИ REDVIDEO
# ==========================================
TOKEN = '8725627105:AAFgdBu8u-AYlHRaGtFLUP12uvqGDJRsuco'
ADMIN_ID = 6907295206 
DEV_USERNAME = "@redperr"

# Ресурсы (Картинки проекта)
START_PIC = "https://i.postimg.cc/3NbWzvGj/Frame_1187517897.png"
ADMIN_PIC = "https://i.postimg.cc/FzK7PZYd/Frame-1187517898.png"

# Путь к базе данных (оптимизировано под Render Volumes)
DB_PATH = '/data/redvideo_final.db' if os.path.exists('/data') else 'redvideo_final.db'

# Настройка глубокого логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("RedVideo_Engine")

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())

# Состояния системы (FSM)
class RedStates(StatesGroup):
    WAITING_BAN = State()
    WAITING_UNBAN = State()
    WAITING_REPLY = State()

# ==========================================
# СЛОЙ ДАННЫХ (DATABASE LAYER)
# ==========================================
async def db_initialize():
    """Создание таблиц с расширенной структурой"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Хранилище видео
        await db.execute('''CREATE TABLE IF NOT EXISTS red_content 
                            (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                             file_id TEXT NOT NULL, 
                             owner_id INTEGER NOT NULL, 
                             timestamp DATETIME)''')
        # Реестр пользователей
        await db.execute('''CREATE TABLE IF NOT EXISTS red_users 
                            (user_id INTEGER PRIMARY KEY, 
                             username TEXT, 
                             quota INTEGER DEFAULT 0, 
                             is_banned INTEGER DEFAULT 0)''')
        await db.commit()
    logger.info("RedVideo DB: Система инициализирована.")

async def check_user_access(user_id: int):
    """Проверка прав доступа пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_banned, quota FROM red_users WHERE user_id = ?", (user_id,)) as cur:
            return await cur.fetchone()

# ==========================================
# ИНТЕРФЕЙСЫ (UI GENERATORS)
# ==========================================
class RedUI:
    @staticmethod
    def main_menu():
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="💎 Поддержать RedVideo (5 ⭐)", callback_data="stars_pay"))
        return builder.as_markup()

    @staticmethod
    def admin_panel():
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="📊 Аналитика Системы", callback_data="adm_stats_show"))
        builder.row(
            types.InlineKeyboardButton(text="🚫 Забанить", callback_data="adm_ban_start"),
            types.InlineKeyboardButton(text="🔓 Разбанить", callback_data="adm_unban_start")
        )
        builder.row(types.InlineKeyboardButton(text="🧹 Полная очистка базы", callback_data="adm_clear_data"))
        return builder.as_markup()

    @staticmethod
    def video_controls(v_id: int):
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(text="❤️", callback_data="feed_next"),
            types.InlineKeyboardButton(text="❌", callback_data="feed_next")
        )
        builder.row(
            types.InlineKeyboardButton(text="💬 Ответить", callback_data=f"rep_{v_id}"),
            types.InlineKeyboardButton(text="🚩 Жалоба", callback_data=f"report_{v_id}")
        )
        return builder.as_markup()

# ==========================================
# ОСНОВНАЯ ЛОГИКА (HANDLERS)
# ==========================================

@dp.message(Command("start"))
async def start_handler(message: Message):
    uid = message.from_user.id
    uname = (message.from_user.username or f"id{uid}").lower()
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO red_users (user_id, username) VALUES (?, ?)", (uid, uname))
        await db.commit()
    
    welcome_text = (
        f"🌟 <b>Добро пожаловать в RedVideo, {message.from_user.first_name}!</b>\n\n"
        f"Запиши кружок — получишь случайный в ответ!\n\n"
        f"💡 <b>Правила проекта:</b>\n"
        f"— 1 кружок открывает 3 просмотра ленты.\n"
        f"— Запрещен спам и оскорбления.\n\n"
        f"Жду твой первый кружок! 👇"
    )
    try:
        await message.answer_photo(photo=START_PIC, caption=welcome_text, reply_markup=RedUI.main_menu())
    except Exception as e:
        logger.error(f"UI Error: {e}")
        await message.answer(welcome_text, reply_markup=RedUI.main_menu())

# --- ОБРАБОТКА КОНТЕНТА ---
@dp.message(F.video_note)
async def video_handler(message: Message):
    uid = message.from_user.id
    uname = (message.from_user.username or f"id{uid}").lower()
    
    status = await check_user_access(uid)
    if status and status[0] == 1:
        return await message.answer("🚫 <b>Доступ заблокирован администратором.</b>")

    async with aiosqlite.connect(DB_PATH) as db:
        # Сохранение видео
        await db.execute("INSERT INTO red_content (file_id, owner_id, timestamp) VALUES (?, ?, ?)", 
                         (message.video_note.file_id, uid, datetime.now()))
        # Выдача квоты
        await db.execute("INSERT OR REPLACE INTO red_users (user_id, username, quota, is_banned) VALUES (?, ?, 3, 0)", 
                         (uid, uname, 3, 0))
        await db.commit()
        
        # Поиск случайного видео
        async with db.execute("SELECT id, file_id FROM red_content WHERE owner_id != ? ORDER BY RANDOM() LIMIT 1", (uid,)) as cur:
            video_data = await cur.fetchone()
        
        if video_data:
            await message.answer_video_note(video_data[1], reply_markup=RedUI.video_controls(video_data[0]))
        else:
            await message.answer("📽 <b>RedVideo:</b> Кружок принят! Ты первый в базе, ждем других участников.")

@dp.callback_query(F.data == "feed_next")
async def next_video_handler(call: CallbackQuery):
    uid = call.from_user.id
    status = await check_user_access(uid)
    
    if not status: return
    if status[0] == 1: return await call.answer("🚫 Аккаунт заблокирован.", show_alert=True)
    if status[1] <= 0 and uid != ADMIN_ID:
        return await call.answer("🔋 Лимит исчерпан! Запиши кружок, чтобы смотреть дальше.", show_alert=True)

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, file_id FROM red_content WHERE owner_id != ? ORDER BY RANDOM() LIMIT 1", (uid,)) as cur:
            video_data = await cur.fetchone()
        
        if video_data:
            if uid != ADMIN_ID:
                await db.execute("UPDATE red_users SET quota = quota - 1 WHERE user_id = ?", (uid,))
                await db.commit()
            await call.message.answer_video_note(video_data[1], reply_markup=RedUI.video_controls(video_data[0]))
        else:
            await call.answer("RedVideo: Кружки закончились.", show_alert=True)
    await call.answer()

# ==========================================
# АДМИНИСТРАТИВНЫЙ МОДУЛЬ (ПОЛНЫЙ)
# ==========================================

@dp.message(Command("admin"))
async def admin_main(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer_photo(photo=ADMIN_PIC, caption="🛠 <b>Панель управления RedVideo</b>", reply_markup=RedUI.admin_panel())

@dp.callback_query(F.data == "adm_stats_show")
async def admin_stats(call: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM red_content") as c1: vc = (await c1.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM red_users") as c2: uc = (await c2.fetchone())[0]
    await call.message.answer(f"📊 <b>Статистика RedVideo:</b>\n\nВсего видео: {vc}\nПользователей: {uc}")
    await call.answer()

# --- ЛОГИКА БАНА / РАЗБАНА ---
@dp.callback_query(F.data == "adm_ban_start")
async def ban_start(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Введите username (без @) для блокировки:")
    await state.set_state(RedStates.WAITING_BAN)
    await call.answer()

@dp.message(RedStates.WAITING_BAN)
async def ban_execute(message: Message, state: FSMContext):
    target = message.text.replace("@", "").lower().strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE red_users SET is_banned = 1 WHERE username = ?", (target,))
        await db.commit()
    await message.answer(f"🚫 Пользователь <b>{target}</b> успешно забанен.")
    await state.clear()

@dp.callback_query(F.data == "adm_unban_start")
async def unban_start(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Введите username (без @) для разблокировки:")
    await state.set_state(RedStates.WAITING_UNBAN)
    await call.answer()

@dp.message(RedStates.WAITING_UNBAN)
async def unban_execute(message: Message, state: FSMContext):
    target = message.text.replace("@", "").lower().strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE red_users SET is_banned = 0 WHERE username = ?", (target,))
        await db.commit()
    await message.answer(f"🔓 Пользователь <b>{target}</b> разблокирован.")
    await state.clear()

@dp.callback_query(F.data == "adm_clear_data")
async def admin_purge(call: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM red_content")
        await db.commit()
    await call.answer("💥 База видео полностью очищена!", show_alert=True)

# --- ПЛАТЕЖИ (STARS) ---
@dp.callback_query(F.data == "stars_pay")
async def stars_invoice(call: CallbackQuery):
    await bot.send_invoice(
        call.from_user.id, "Поддержка RedVideo", "Донат 5 звезд", "payload_rv", "XTR", [LabeledPrice("Звезды", 5)]
    )
    await call.answer()

@dp.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)

# ==========================================
# СЕРВИСНЫЙ СЛОЙ
# ==========================================
async def handle_ping(request):
    return web.Response(text="RedVideo Core: Online")

async def run_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()

async def main():
    await db_initialize()
    asyncio.create_task(run_server())
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("RedVideo Engine: Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Система остановлена.")
    
