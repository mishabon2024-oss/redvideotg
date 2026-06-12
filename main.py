import asyncio
import logging
import random
import time
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# --- КОНФИГУРАЦИЯ ---
API_TOKEN = "8661823879:AAEu2iKk00Hk499ga8mDGYN3jnIvdKua2Rc"
DB_NAME = "criptynum.db"

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- СОСТОЯНИЯ (FSM) ---
class WalletStates(StatesGroup):
    waiting_for_transfer_recipient = State()
    waiting_for_transfer_amount = State()
    waiting_for_deposit_amount = State()

# --- КЛАВИАТУРЫ ---
def get_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Баланс / Кошелек", callback_data="wallet")],
        [InlineKeyboardButton(text="🎁 Открыть кейс", callback_data="cases")],
        [InlineKeyboardButton(text="⚡️ Ежедневный бонус", callback_data="daily")],
        [InlineKeyboardButton(text="💸 Перевести", callback_data="transfer")],
        [InlineKeyboardButton(text="💳 Пополнить", callback_data="deposit")],
        [InlineKeyboardButton(text="📱 Mini-App", web_app=WebAppInfo(url="https://example.com"))]
    ])

def get_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="main_menu")]
    ])

# --- БАЗА ДАННЫХ И ХЕЛПЕРЫ ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 100.0,
                last_daily INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                type TEXT,
                timestamp DATETIME
            )
        """)
        await db.commit()

async def get_user(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT balance, last_daily FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        if not row:
            await db.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
            await db.commit()
            return 100.0, 0
        return row

async def update_balance(user_id, amount, operation="add"):
    async with aiosqlite.connect(DB_NAME) as db:
        if operation == "add":
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        else:
            await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    await get_user(message.from_user.id)
    text = (
        f"Приветствуем, {message.from_user.full_name}\n"
        f"Вы попали в крипто-кошелёк Criptynum\n"
        f"Что сегодня желаете сделать?"
    )
    await message.answer(text, reply_markup=get_main_kb())

@dp.callback_query(F.data == "main_menu")
async def main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Главное меню:", reply_markup=get_main_kb())

@dp.callback_query(F.data == "wallet")
async def show_wallet(callback: types.CallbackQuery):
    balance, _ = await get_user(callback.from_user.id)
    await callback.message.edit_text(
        f"💳 Ваш баланс: {balance:.2f} монет.\n\n"
        f"Статус: Активен.",
        reply_markup=get_back_kb()
    )

@dp.callback_query(F.data == "daily")
async def daily_bonus(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    balance, last_daily = await get_user(user_id)
    
    current_time = int(time.time())
    if current_time - last_daily < 86400:
        remaining = 86400 - (current_time - last_daily)
        await callback.answer(f"Бонус можно получить через {remaining//3600} ч.", show_alert=True)
        return

    bonus = random.randint(50, 200)
    await update_balance(user_id, bonus, "add")
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET last_daily = ? WHERE user_id = ?", (current_time, user_id))
        await db.commit()
    
    await callback.message.edit_text(f"Вы получили ежедневный бонус: {bonus} монет!", reply_markup=get_back_kb())

@dp.callback_query(F.data == "cases")
async def open_case(callback: types.CallbackQuery):
    balance, _ = await get_user(callback.from_user.id)
    cost = 50
    if balance < cost:
        await callback.answer("Недостаточно средств (кейс стоит 50).", show_alert=True)
        return
    
    win = random.randint(0, 150)
    await update_balance(callback.from_user.id, cost - win, "add") # Если win < cost, баланс уменьшится
    await callback.message.edit_text(f"Кейс открыт. Ваш выигрыш: {win} монет.", reply_markup=get_back_kb())

@dp.callback_query(F.data == "transfer")
async def transfer_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите ID получателя (число):", reply_markup=get_back_kb())
    await state.set_state(WalletStates.waiting_for_transfer_recipient)

@dp.message(WalletStates.waiting_for_transfer_recipient)
async def process_transfer_recipient(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("ID должен быть числом.")
        return
    await state.update_data(recipient=int(message.text))
    await message.answer("Введите сумму для перевода:", reply_markup=get_back_kb())
    await state.set_state(WalletStates.waiting_for_transfer_amount)

@dp.message(WalletStates.waiting_for_transfer_amount)
async def process_transfer_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)
        data = await state.get_data()
        recipient = data['recipient']
        
        balance, _ = await get_user(message.from_user.id)
        if amount > balance:
            await message.answer("Недостаточно средств.")
        else:
            await update_balance(message.from_user.id, amount, "sub")
            await update_balance(recipient, amount, "add")
            await message.answer(f"Успешно переведено {amount} монет пользователю {recipient}.")
        await state.clear()
        await message.answer("Возврат в главное меню:", reply_markup=get_main_kb())
    except ValueError:
        await message.answer("Ошибка: сумма должна быть числом.")

# --- ЗАПУСК ---
async def main():
    await init_db()
    logging.info("Criptynum запущен и готов к работе.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.error(f"Ошибка при запуске: {e}")
        
