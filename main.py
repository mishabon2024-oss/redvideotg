import asyncio
import logging
import random
import time
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, 
    LabeledPrice, Message, CallbackQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# --- КОНФИГУРАЦИЯ ---
API_TOKEN = "8661823879:AAEu2iKk00Hk499ga8mDGYN3jnIvdKua2Rc"
DB_NAME = "criptynum.db"
PHOTO_URL = "https://i.ibb.co/4R8pgL5J/Picsart-26-06-12-14-38-12-376.jpg"
STAR_TO_USDT_RATE = 400

# Настройка кейсов: {название: (стоимость, мин_выигрыш, макс_выигрыш)}
CASES = {
    "Бронзовый": (20, 5, 40),
    "Серебряный": (100, 50, 200),
    "Золотой": (500, 300, 1500)
}

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- СОСТОЯНИЯ ---
class WalletStates(StatesGroup):
    waiting_for_transfer_recipient = State()
    waiting_for_transfer_amount = State()

# --- БД И ХЕЛПЕРЫ ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 10.0,
                last_daily INTEGER DEFAULT 0
            )
        """)
        await db.commit()

async def get_user(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT balance, last_daily FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        if not row:
            await db.execute("INSERT INTO users (user_id, balance) VALUES (?, 10.0)", (user_id,))
            await db.commit()
            return 10.0, 0
        return row

async def update_balance(user_id, amount):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

# --- КЛАВИАТУРЫ ---
def get_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Кошелек", callback_data="wallet")],
        [InlineKeyboardButton(text="🎁 Кейсы", callback_data="cases_menu")],
        [InlineKeyboardButton(text="⚡️ Бонус (24ч)", callback_data="daily")],
        [InlineKeyboardButton(text="⭐ Купить USDT", callback_data="buy_usdt")]
    ])

def get_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")]
    ])

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("start"))
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()
    await get_user(message.from_user.id)
    text = (
        f"Приветствуем, {message.from_user.full_name}!\n"
        f"Вы попали в крипто-кошелёк Criptynum\n"
        f"Что сегодня желаете сделать?"
    )
    await message.answer_photo(
        photo=PHOTO_URL,
        caption=text,
        reply_markup=get_main_kb()
    )

@dp.callback_query(F.data == "main")
async def go_main(callback: CallbackQuery):
    text = "Главное меню Criptynum:"
    await callback.message.edit_caption(caption=text, reply_markup=get_main_kb())

@dp.callback_query(F.data == "wallet")
async def show_wallet(callback: CallbackQuery):
    balance, _ = await get_user(callback.from_user.id)
    await callback.message.edit_caption(
        caption=f"💳 Ваш баланс: {balance:.2f} USDT.", 
        reply_markup=get_back_kb()
    )

@dp.callback_query(F.data == "daily")
async def daily_bonus(callback: CallbackQuery):
    user_id = callback.from_user.id
    _, last_daily = await get_user(user_id)
    if time.time() - last_daily < 86400:
        await callback.answer("Бонус доступен раз в 24 часа.", show_alert=True)
        return
    
    reward = random.randint(5, 20)
    await update_balance(user_id, reward)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET last_daily = ? WHERE user_id = ?", (int(time.time()), user_id))
        await db.commit()
    await callback.answer(f"Бонус получен: +{reward} USDT!", show_alert=True)

@dp.callback_query(F.data == "cases_menu")
async def cases_menu(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{name} ({cost} USDT)", callback_data=f"case_{name}")] 
        for name, (cost, _, _) in CASES.items()
    ] + [[InlineKeyboardButton(text="⬅️ Назад", callback_data="main")]])
    await callback.message.edit_caption(caption="Выберите кейс:", reply_markup=kb)

@dp.callback_query(F.data.startswith("case_"))
async def open_case(callback: CallbackQuery):
    name = callback.data.split("_")[1]
    cost, min_p, max_p = CASES[name]
    balance, _ = await get_user(callback.from_user.id)
    
    if balance < cost:
        await callback.answer("Недостаточно средств!")
        return
    
    win = random.randint(min_p, max_p)
    await update_balance(callback.from_user.id, win - cost)
    await callback.answer(f"Вы открыли {name}! Выигрыш: {win} USDT.", show_alert=True)

@dp.callback_query(F.data == "buy_usdt")
async def buy_usdt(callback: CallbackQuery):
    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title="Пополнение USDT",
        description="Купить USDT за звезды (1 звезда = 400 USDT)",
        payload="buy_stars_payload",
        currency="XTR",
        prices=[LabeledPrice(label="1 Star", amount=1)],
        provider_token=""
    )

@dp.pre_checkout_query()
async def on_pre_checkout_query(query: types.PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def on_successful_payment(message: Message):
    stars_count = message.successful_payment.total_amount
    usdt_received = stars_count * STAR_TO_USDT_RATE
    await update_balance(message.from_user.id, usdt_received)
    await message.answer(f"Успешно! Баланс пополнен на {usdt_received} USDT.")

async def main():
    await init_db()
    logging.info("Criptynum запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
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
        
