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
# КРИТИЧЕСКИЕ НАСТРОЙКИ СИСТЕМЫ
# ==========================================
TOKEN = '8725627105:AAFgdBu8u-AYlHRaGtFLUP12uvqGDJRsuco'
ADMIN_ID = 6907295206 
DEV_USERNAME = "@redperr"

# Ресурсы (Размеры картинок: 1280x720)
START_PIC = "https://i.postimg.cc/3NbWzvGj/Frame_1187517897.png"
ADMIN_PIC = "https://i.postimg.cc/FzK7PZYd/Frame-1187517898.png"

# База данных
DB_PATH = '/data/bot_data.db' if os.path.exists('/data') else 'bot_data.db'

# Настройка логирования "Industrial Standard"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("BringOS_Engine")

# Инициализация ядра
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())

class SystemStates(StatesGroup):
    WAITING_BAN = State()
    WAITING_UNBAN = State()
    WAITING_REPLY = State()

# ==========================================
# СЛОЙ РАБОТЫ С ДАННЫМИ (DB LAYER)
# ==========================================
async def db_initialize():
    """Инициализация таблиц с расширенными полями"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица видео
        await db.execute('''CREATE TABLE IF NOT EXISTS content_archive 
                            (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                             file_id TEXT NOT NULL, 
                             owner_id INTEGER NOT NULL, 
                             created_at DATETIME)''')
        # Таблица пользователей
        await db.execute('''CREATE TABLE IF NOT EXISTS user_registry 
                            (user_id INTEGER PRIMARY KEY, 
                             username TEXT, 
                             views_quota INTEGER DEFAULT 0, 
                             is_restricted INTEGER DEFAULT 0,
                             total_contributions INTEGER DEFAULT 0)''')
        await db.commit()
    logger.info("Database Engine: Connection established and tables verified.")

async def get_user_status(user_id: int):
    """Возвращает статус блокировки и остаток просмотров"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_restricted, views_quota FROM user_registry WHERE user_id = ?", (user_id,)) as cur:
            return await cur.fetchone()

# ==========================================
# ИНТЕРФЕЙСЫ (UI GENERATORS)
# ==========================================
class UI:
    @staticmethod
    def main_menu():
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="💎 Поддержать автора (5 ⭐)", callback_data="stars_donate"))
        return builder.as_markup()

    @staticmethod
    def admin_panel():
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="📊 Метрики", callback_data="adm_metrics"))
        builder.row(
            types.InlineKeyboardButton(text="🚫 Блокировка", callback_data="adm_ban_init"),
            types.InlineKeyboardButton(text="🔓 Разблокировка", callback_data="adm_unban_init")
        )
        builder.row(types.InlineKeyboardButton(text="🧹 Полная очистка БД", callback_data="adm_wipe"))
        return builder.as_markup()

    @staticmethod
    def video_controls(v_id: int):
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(text="🔥", callback_data="feed_next"),
            types.InlineKeyboardButton(text="👎", callback_data="feed_next")
        )
        builder.row(
            types.InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply_{v_id}"),
            types.InlineKeyboardButton(text="🚩 Жалоба", callback_data=f"report_{v_id}")
        )
        return builder.as_markup()

# ==========================================
# ОСНОВНАЯ ЛОГИКА (CORE HANDLERS)
# ==========================================

@dp.message(Command("start"))
async def handler_start(message: Message):
    uid, uname = message.from_user.id, (message.from_user.username or "none").lower()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO user_registry (user_id, username) VALUES (?, ?)", (uid, uname))
        await db.commit()
    
    welcome_text = (
        f"🚀 <b>Система Bring OS: Видео-Хаб</b>\n\n"
        f"Приветствуем, <b>{message.from_user.first_name}</b>!\n\n"
        f"Это профессиональная платформа для обмена видео-сообщениями.\n\n"
        f"<b>Правила:</b>\n"
        f"└ 1 кружок = 3 просмотра других авторов\n"
        f"└ Запрещен спам и оскорбления\n\n"
        f"⚙️ <i>Разработка: {DEV_USERNAME}</i>"
    )
    try:
        await message.answer_photo(photo=START_PIC, caption=welcome_text, reply_markup=UI.main_menu())
    except Exception as e:
        logger.error(f"UI Error: {e}")
        await message.answer(welcome_text, reply_markup=UI.main_menu())

# --- ОБРАБОТКА ПЛАТЕЖЕЙ ---
@dp.callback_query(F.data == "stars_donate")
async def process_stars_invoice(call: CallbackQuery):
    await bot.send_invoice(
        chat_id=call.from_user.id,
        title="⭐ Поддержка Bring OS",
        description="Добровольное пожертвование на развитие системы (5 звезд)",
        payload="don_5",
        currency="XTR",
        prices=[LabeledPrice(label="Звезды", amount=5)]
    )
    await call.answer()

@dp.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def on_success_payment(message: Message):
    await message.answer("🎆 <b>Огромное спасибо!</b> Ваша поддержка помогает делать Bring OS лучше.")

# --- МЕХАНИКА КРУЖКОВ (ENGINE) ---
@dp.message(F.video_note)
async def engine_process_video(message: Message):
    uid, uname = message.from_user.id, (message.from_user.username or "none").lower()
    
    # Глубокая проверка доступа
    status = await get_user_status(uid)
    if status and status[0] == 1:
        return await message.answer("🚫 <b>Доступ ограничен.</b> Ваш аккаунт заблокирован администратором.")

    async with aiosqlite.connect(DB_PATH) as db:
        # Сохранение видео
        await db.execute("INSERT INTO content_archive (file_id, owner_id, created_at) VALUES (?, ?, ?)", 
                         (message.video_note.file_id, uid, datetime.now()))
        # Начисление квоты
        await db.execute("UPDATE user_registry SET views_quota = 3, total_contributions = total_contributions + 1 WHERE user_id = ?", (uid,))
        await db.commit()
        
        # Получение случайного видео в ответ (сложный запрос с исключением себя)
        async with db.execute("SELECT id, file_id FROM content_archive WHERE owner_id != ? ORDER BY RANDOM() LIMIT 1", (uid,)) as cur:
            video_data = await cur.fetchone()
        
        if video_data:
            await message.answer_video_note(video_data[1], reply_markup=UI.video_controls(video_data[0]))
        else:
            await message.answer("✅ <b>Кружок принят!</b> Вы первым вошли в базу. Как только появятся другие видео, я их вам пришлю.")

@dp.callback_query(F.data == "feed_next")
async def engine_feed_iterator(call: CallbackQuery):
    uid = call.from_user.id
    status = await get_user_status(uid)
    
    if status:
        if status[0] == 1:
            return await call.answer("🚫 Аккаунт заблокирован.", show_alert=True)
        if status[1] <= 0 and uid != ADMIN_ID:
            return await call.answer("🔋 Лимит исчерпан! Запишите кружок, чтобы получить еще 3 просмотра.", show_alert=True)

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, file_id FROM content_archive WHERE owner_id != ? ORDER BY RANDOM() LIMIT 1", (uid,)) as cur:
            video_data = await cur.fetchone()
        
        if video_data:
            if uid != ADMIN_ID:
                await db.execute("UPDATE user_registry SET views_quota = views_quota - 1 WHERE user_id = ?", (uid,))
                await db.commit()
            await call.message.answer_video_note(video_data[1], reply_markup=UI.video_controls(video_data[0]))
        else:
            await call.answer("🎬 Видео в базе закончились. Попробуйте позже!", show_alert=True)
    await call.answer()

# --- АДМИНИСТРАТИВНЫЙ БЛОК ---
@dp.message(Command("admin"))
async def admin_access_point(message: Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("⚠️ <b>Отказ в доступе.</b> Команда только для персонала.")
    
    try:
        await message.answer_photo(photo=ADMIN_PIC, caption="🛠 <b>Терминал Администратора</b>\nВыберите действие:", reply_markup=UI.admin_panel())
    except:
        await message.answer("🛠 <b>Терминал Администратора</b>", reply_markup=UI.admin_panel())

@dp.callback_query(F.data == "adm_metrics")
async def admin_metrics(call: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM content_archive") as c1: v_all = (await c1.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM user_registry") as c2: u_all = (await c2.fetchone())[0]
    
    text = f"📊 <b>Системные показатели:</b>\n\nВсего видео в базе: {v_all}\nЗарегистрировано юзеров: {u_all}"
    await call.message.answer(text)
    await call.answer()

@dp.callback_query(F.data == "adm_ban_init")
async def admin_ban_start(call: CallbackQuery, state: FSMContext):
    await call.message.answer("⌨️ Введите @username (или текст без @) для блокировки:")
    await state.set_state(SystemStates.WAITING_BAN)
    await call.answer()

@dp.message(SystemStates.WAITING_BAN)
async def admin_ban_execute(message: Message, state: FSMContext):
    target = message.text.replace("@", "").strip().lower()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE user_registry SET is_restricted = 1 WHERE username = ?", (target,))
        await db.commit()
    await message.answer(f"🚫 Объект <b>@{target}</b> успешно заблокирован в системе.")
    await state.clear()

@dp.callback_query(F.data == "adm_unban_init")
async def admin_unban_start(call: CallbackQuery, state: FSMContext):
    await call.message.answer("⌨️ Введите @username для разблокировки:")
    await state.set_state(SystemStates.WAITING_UNBAN)
    await call.answer()

@dp.message(SystemStates.WAITING_UNBAN)
async def admin_unban_execute(message: Message, state: FSMContext):
    target = message.text.replace("@", "").strip().lower()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE user_registry SET is_restricted = 0 WHERE username = ?", (target,))
        await db.commit()
    await message.answer(f"🔓 Доступ для <b>@{target}</b> восстановлен.")
    await state.clear()

@dp.callback_query(F.data == "adm_wipe")
async def admin_wipe_db(call: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM content_archive")
        await db.commit()
    await call.answer("💥 Весь архив видео полностью удален!", show_alert=True)

# ==========================================
# СЕРВИСНЫЙ СЛОЙ (WEB & RUNTIME)
# ==========================================
async def handle_ping(request):
    return web.Response(text="BringOS Core: Online")

async def run_anti_sleep():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logger.info(f"Anti-Sleep server active on port {port}")

async def entry_point():
    await db_initialize()
    asyncio.create_task(run_anti_sleep())
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Polling sequence initiated.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(entry_point())
    except (KeyboardInterrupt, SystemExit):
        logger.info("System forced to shutdown.")
        
