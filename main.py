import asyncio
import logging
import random
import time
import aiosqlite
from typing import Tuple

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    LabeledPrice, 
    Message, 
    CallbackQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# --- НАСТРОЙКИ И КОНФИГУРАЦИЯ ---
# Токен бота
API_TOKEN = "8661823879:AAE-YUL5xOxmrzM6merb2oqm5cIKR8JtTD4"

# Имя файла базы данных
DB_NAME = "criptynum.db"

# Ссылка на приветственное фото
PHOTO_URL = "https://i.ibb.co/4R8pgL5J/Picsart-26-06-12-14-38-12-376.jpg"

# Курс конвертации
STAR_TO_USDT_RATE = 400

# Конфигурация кейсов (Название: [Цена, Мин. выигрыш, Макс. выигрыш])
CASES_CONFIG = {
    "Бронзовый": [20, 5, 40],
    "Серебряный": [100, 50, 200],
    "Золотой": [500, 300, 1500]
}

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s'
)

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- УПРАВЛЕНИЕ БАЗОЙ ДАННЫХ ---

async def initialize_database():
    """
    Создает таблицы в базе данных, если они отсутствуют.
    Вызывается при старте бота.
    """
    logging.info("Инициализация базы данных...")
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 10.0,
                last_daily INTEGER DEFAULT 0
            )
        """)
        await db.commit()
    logging.info("База данных готова к работе.")

async def get_user_profile(user_id: int) -> Tuple[float, int]:
    """
    Получает профиль пользователя из БД. 
    Если пользователя нет — создает запись с начальным балансом 10 USDT.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT balance, last_daily FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row is None:
                await db.execute("INSERT INTO users (user_id, balance) VALUES (?, 10.0)", (user_id,))
                await db.commit()
                return 10.0, 0
            return row[0], row[1]

async def update_user_balance(user_id: int, amount_delta: float):
    """
    Обновляет баланс пользователя в базе данных.
    amount_delta может быть как положительным (начисление), так и отрицательным (списание).
    """
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount_delta, user_id))
        await db.commit()
        logging.info(f"Баланс пользователя {user_id} изменен на {amount_delta}")

async def set_last_daily_bonus(user_id: int, timestamp: int):
    """Обновляет время последнего получения ежедневного бонуса."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET last_daily = ? WHERE user_id = ?", (timestamp, user_id))
        await db.commit()

# --- ФУНКЦИИ КЛАВИАТУР ---

def generate_main_keyboard() -> InlineKeyboardMarkup:
    """Генерирует главное меню бота."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Кошелек", callback_data="wallet")],
        [InlineKeyboardButton(text="Кейсы", callback_data="cases_menu")],
        [InlineKeyboardButton(text="Бонус (24ч)", callback_data="daily")],
        [InlineKeyboardButton(text="Купить USDT", callback_data="buy_usdt")]
    ])

def generate_back_keyboard() -> InlineKeyboardMarkup:
    """Генерирует кнопку возврата в главное меню."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="main")]
    ])

# --- ОБРАБОТЧИКИ КОМАНД И КНОПОК ---

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработка команды /start."""
    await state.clear()
    await get_user_profile(message.from_user.id)
    
    text = (
        f"Приветствуем, {message.from_user.full_name}.\n"
        f"Вы находитесь в крипто-кошельке Criptynum.\n"
        f"Что вы хотите сделать сегодня?"
    )
    
    await message.answer_photo(
        photo=PHOTO_URL,
        caption=text,
        reply_markup=generate_main_keyboard()
    )

@dp.callback_query(F.data == "main")
async def callback_back_to_main(callback: CallbackQuery):
    """Возврат в главное меню через callback."""
    await callback.message.edit_caption(
        caption="Главное меню.", 
        reply_markup=generate_main_keyboard()
    )

@dp.callback_query(F.data == "wallet")
async def callback_show_wallet(callback: CallbackQuery):
    """Отображение баланса пользователя."""
    balance, _ = await get_user_profile(callback.from_user.id)
    await callback.message.edit_caption(
        caption=f"Ваш баланс: {balance:.2f} USDT.", 
        reply_markup=generate_back_keyboard()
    )

@dp.callback_query(F.data == "daily")
async def callback_give_bonus(callback: CallbackQuery):
    """Логика выдачи ежедневного бонуса."""
    user_id = callback.from_user.id
    _, last_daily = await get_user_profile(user_id)
    
    current_time = int(time.time())
    if current_time - last_daily < 86400:
        await callback.answer("Бонус доступен раз в 24 часа.", show_alert=True)
        return
    
    reward = random.randint(5, 20)
    await update_user_balance(user_id, float(reward))
    await set_last_daily_bonus(user_id, current_time)
    
    await callback.answer(f"Бонус получен: +{reward} USDT!", show_alert=True)

@dp.callback_query(F.data == "cases_menu")
async def callback_show_cases(callback: CallbackQuery):
    """Меню выбора кейсов."""
    keyboard_buttons = []
    for name, config in CASES_CONFIG.items():
        cost = config[0]
        keyboard_buttons.append([InlineKeyboardButton(text=f"{name} ({cost} USDT)", callback_data=f"case_{name}")])
    keyboard_buttons.append([InlineKeyboardButton(text="Назад", callback_data="main")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await callback.message.edit_caption(caption="Выберите кейс:", reply_markup=kb)

@dp.callback_query(F.data.startswith("case_"))
async def callback_open_case(callback: CallbackQuery):
    """Логика открытия кейса."""
    case_name = callback.data.split("_")[1]
    case_data = CASES_CONFIG[case_name]
    cost, min_win, max_win = case_data
    
    balance, _ = await get_user_profile(callback.from_user.id)
    
    if balance < cost:
        await callback.answer("Недостаточно средств!")
        return
    
    win = random.randint(min_win, max_win)
    profit = win - cost
    
    await update_user_balance(callback.from_user.id, float(profit))
    await callback.answer(f"Вы открыли {case_name}! Выигрыш: {win} USDT.", show_alert=True)

@dp.callback_query(F.data == "buy_usdt")
async def callback_buy_usdt(callback: CallbackQuery):
    """Инициализация процесса оплаты через Telegram Stars."""
    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title="Пополнение баланса",
        description="Купить USDT за звезды (1 звезда = 400 USDT)",
        payload="buy_stars_payload",
        currency="XTR",
        prices=[LabeledPrice(label="Пополнение баланса", amount=1)],
        provider_token=""
    )

@dp.pre_checkout_query()
async def process_pre_checkout(query: types.PreCheckoutQuery):
    """Подтверждение готовности к оплате."""
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: Message):
    """Обработка успешной оплаты."""
    stars_count = message.successful_payment.total_amount
    usdt_received = stars_count * STAR_TO_USDT_RATE
    
    await update_user_balance(message.from_user.id, float(usdt_received))
    await message.answer(f"Оплата прошла успешно! Баланс пополнен на {usdt_received} USDT.")

# --- ТОЧКА ВХОДА ---

async def main():
    """Основная функция запуска бота."""
    await initialize_database()
    logging.info("Бот Criptynum запущен и ожидает сообщений.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.error(f"Критическая ошибка: {e}")
        # --- ДОБАВЬ ЭТОТ БЛОК В САМЫЙ КОНЕЦ ФАЙЛА К БОТУ ---
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()

# Разрешаем сайту брать данные из бота
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Строчка (эндпоинт), по которой сайт будет запрашивать баланс
@app.get("/api/get_balance/{user_id}")
async def api_get_balance(user_id: int):
    balance, _ = await get_user_profile(user_id)
    return {"balance": balance}

async def main():
    await initialize_database()
    
    # Запуск веб-части параллельно с ботом на порту 8000
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, loop="asyncio")
    server = uvicorn.Server(config)
    
    logging.info("Бот и веб-синхронизация запущены!")
    await asyncio.gather(
        dp.start_polling(bot),
        server.serve()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.error(f"Критическая ошибка: {e}")
        
        
