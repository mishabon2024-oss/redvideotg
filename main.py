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
from aiogram.types import LabeledPrice, PreCheckoutQuery, InputFile
from aiohttp import web

# --- НАСТРОЙКИ ---
TOKEN = '8725627105:AAFgdBu8u-AYlHRaGtFLUP12uvqGDJRsuco'
ADMIN_ID = 6907295206 
DEV_USERNAME = "@redperr"

# Логирование для Render
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())

# Состояния для FSM
class MyStates(StatesGroup):
    waiting_for_ban = State()
    waiting_for_unban = State()
    waiting_for_comment = State()

# Путь к базе данных на Render Volume
DB_PATH = '/data/bot_data.db' if os.path.exists('/data') else 'bot_data.db'

# ССЫЛКИ НА КАРТИНКИ (Размер 16:9, например 1280x720)
# Залей картинки на Imgur или Telegraph и вставь ссылки ниже
START_PIC = "https://i.postimg.cc/3NbWzvGj/Frame_1187517897.png"  # 🖼 ЗАМЕНИ НА СВОЮ ССЫЛКУ ДЛЯ СТАРТА
ADMIN_PIC = "https://i.postimg.cc/FzK7PZYd/Frame-1187517898.png"  # 🖼 ЗАМЕНИ НА СВОЮ ССЫЛКУ ДЛЯ АДМИНКИ

# --- ВЕБ-СЕРВЕР (Anti-Sleep) ---
async def handle_ping(request):
    return web.Response(text="Bring OS Bot is Online!")

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ---
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS videos 
                            (id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT, owner_id INTEGER)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
                            (user_id INTEGER PRIMARY KEY, username TEXT, views_left INTEGER DEFAULT 0, is_blocked INTEGER DEFAULT 0)''')
        await db.commit()

# --- КЛАВИАТУРЫ ---

# Главное меню
def get_start_kb():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🎁 Поддержать автора (5 ⭐)", callback_data="buy_stars"))
    return builder.as_markup()

# Админ-панель
def get_admin_kb():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats"))
    builder.row(
        types.InlineKeyboardButton(text="🚫 Бан", callback_data="adm_ban_start"),
        types.InlineKeyboardButton(text="✅ Разбан", callback_data="adm_unban_start")
    )
    builder.row(types.InlineKeyboardButton(text="🗑 Очистить базу", callback_data="adm_clear"))
    return builder.as_markup()

# Кнопки под видео
def get_video_actions(video_id):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="❤️", callback_data="next_video"),
        types.InlineKeyboardButton(text="❌", callback_data="next_video")
    )
    builder.row(
        types.InlineKeyboardButton(text="💬 Коммент", callback_data=f"add_comm_{video_id}"),
        types.InlineKeyboardButton(text="🚩 Жалоба", callback_data=f"report_{video_id}")
    )
    return builder.as_markup()

# --- СТАРТОВОЕ СООБЩЕНИЕ (С КАРТИНКОЙ И ДОНАТОМ) ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    un = (message.from_user.username or "none").lower()
    async with aiosqlite.connect(DB_PATH) as db:
        # Добавляем юзера, если его нет,views_left не трогаем если он уже был
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (uid, un))
        await db.commit()
        
    caption = (
        f"👋 <b>Привет, {message.from_user.first_name}!</b>\n\n"
        f"Это бот обмена кружочками 🎬\n\n"
        f"📸 <b>Пришли свой кружок</b> — и я сразу дам тебе случайный кружок от другого человека!\n\n"
        f"⚠️ <i>После записи тебе доступно 3 просмотра.</i>\n\n"
        f"<b>Разработчик:</b> {DEV_USERNAME}"
    )
    
    try:
        await message.answer_photo(photo=START_PIC, caption=caption, reply_markup=get_start_kb())
    except:
        # Если ссылка на картинку битая, отправляем просто текст
        await message.answer(caption, reply_markup=get_start_kb())

# --- ПЛАТЕЖИ (STARS) - ТОЛЬКО ИЗ СТАРТА ---
@dp.callback_query(F.data == "buy_stars")
async def send_invoice(call: types.CallbackQuery):
    await bot.send_invoice(
        chat_id=call.from_user.id,
        title="💳 Поддержка автора",
        description="Донат автору за разработку бота! (5 звёзд)",
        payload="donate_5_stars",
        currency="XTR", # Код для Telegram Stars
        prices=[LabeledPrice(label="Донат", amount=5)] # 5 звезд
    )
    await call.answer()

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    # Одобряем платеж
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def success_pay(message: types.Message):
    # Уведомление об успешной оплате
    await message.answer("🎉 <b>Спасибо огромное за поддержку!</b> Это очень мотивирует развивать бота!")

# --- АДМИН-ПАНЕЛЬ (С КАРТИНКОЙ) ---
@dp.message(Command("admin"))
async def open_admin(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        try:
            await message.answer_photo(photo=ADMIN_PIC, caption="🛠 <b>ПАНЕЛЬ УПРАВЛЕНИЯ</b>", reply_markup=get_admin_kb())
        except:
            await message.answer("🛠 <b>ПАНЕЛЬ УПРАВЛЕНИЯ</b>", reply_markup=get_admin_kb())

# --- ЛОГИКА АДМИНКИ (БАН/РАЗБАН/СТАТС) ---
@dp.callback_query(F.data == "adm_stats")
async def adm_stats(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM videos") as c1: v_count = (await c1.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users") as c2: u_count = (await c2.fetchone())[0]
    await callback.message.edit_caption(caption=f"📈 <b>Статистика:</b>\nКружков: {v_count}\nЮзеров: {u_count}", reply_markup=get_admin_kb())

# Бан
@dp.callback_query(F.data == "adm_ban_start")
async def adm_ban_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.answer("⌨️ Напиши username для бана (без @):")
    await state.set_state(MyStates.waiting_for_ban)

@dp.message(MyStates.waiting_for_ban)
async def process_ban(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    target = message.text.replace("@", "").strip().lower()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_blocked = 1 WHERE username = ?", (target,))
        await db.commit()
    await message.answer(f"🚫 Пользователь <b>@{target}</b> забанен навсегда.")
    await state.clear()

# Разбан
@dp.callback_query(F.data == "adm_unban_start")
async def adm_unban_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.answer("⌨️ Напиши username для РАЗБАНА (без @):")
    await state.set_state(MyStates.waiting_for_unban)

@dp.message(MyStates.waiting_for_unban)
async def process_unban(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    target = message.text.replace("@", "").strip().lower()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_blocked = 0 WHERE username = ?", (target,))
        await db.commit()
    await message.answer(f"✅ Пользователь <b>@{target}</b> разбанен!")
    await state.clear()

@dp.callback_query(F.data == "adm_clear")
async def adm_clear(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM videos")
        await db.commit()
    await callback.answer("База видео очищена!", show_alert=True)

# --- ЛОГИКА КОММЕНТАРИЕВ ---
@dp.callback_query(F.data.startswith("add_comm_"))
async def start_comm(call: types.CallbackQuery, state: FSMContext):
    video_id = call.data.split("_")[2]
    await state.update_data(v_id=video_id)
    await call.message.answer("⌨️ Напиши сообщение автору:")
    await state.set_state(MyStates.waiting_for_comment)

@dp.message(MyStates.waiting_for_comment)
async def save_comm(message: types.Message, state: FSMContext):
    v_id = (await state.get_data()).get("v_id")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT owner_id FROM videos WHERE id = ?", (v_id,)) as cur:
            row = await cur.fetchone()
            if row:
                try:
                    await bot.send_message(row[0], f"💬 <b>Комментарий к твоему кружку:</b>\n\n\"{message.text}\"")
                    await message.answer("✅ Комментарий отправлен!")
                except:
                    await message.answer("❌ Автор заблокировал бота.")
    await state.clear()

# --- ЛЕНТА КРУЖКОВ (TikTok) ---
@dp.callback_query(F.data == "next_video")
async def next_v(call: types.CallbackQuery):
    uid = call.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_blocked, views_left FROM users WHERE user_id = ?", (uid,)) as cur:
            res = await cur.fetchone()
            if res:
                if res[0]: return await call.answer("🚫 Ты забанен.", show_alert=True)
                if res[1] <= 0 and uid != ADMIN_ID:
                    return await call.answer("❌ Запиши свой кружок, чтобы смотреть дальше!", show_alert=True)
        
        # Берем рандомное видео (не своё)
        async with db.execute("SELECT id, file_id FROM videos WHERE owner_id != ? ORDER BY RANDOM() LIMIT 1", (uid,)) as cur:
            ans = await cur.fetchone()
        
        if ans:
            # Снимаем 1 просмотр (если не админ)
            if uid != ADMIN_ID:
                await db.execute("UPDATE users SET views_left = views_left - 1 WHERE user_id = ?", (uid,))
                await db.commit()
            
            try:
                await call.message.answer_video_note(ans[1], reply_markup=get_video_actions(ans[0]))
            except:
                await call.answer("Проблема с отправкой видео.", show_alert=True)
        else:
            await call.answer("Кружков больше нет 😢", show_alert=True)
    await call.answer()

# --- ПРИЕМ КРУЖКОВ (ФИКС ЛИМИТОВ И СОХРАНЕНИЯ) ---
@dp.message(F.video_note)
async def handle_video(message: types.Message):
    uid, un = message.from_user.id, (message.from_user.username or "none").lower()
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_blocked FROM users WHERE user_id = ?", (uid,)) as cur:
            res = await cur.fetchone()
            if res and res[0]: return

        # 1. Сохраняем НОВОЕ видео в базу
        await db.execute("INSERT INTO videos (file_id, owner_id) VALUES (?, ?)", (message.video_note.file_id, uid))
        
        # 2. Даем 3 просмотра (делаем INSERT OR REPLACE, чтобы обновить views_left)
        await db.execute("INSERT OR REPLACE INTO users (user_id, username, views_left, is_blocked) VALUES (?, ?, 3, 0)", (uid, un))
        await db.commit()
        
        # 3. Сразу выдаем один ответный кружок
        async with db.execute("SELECT id, file_id FROM videos WHERE owner_id != ? ORDER BY RANDOM() LIMIT 1", (uid,)) as cur:
            ans = await cur.fetchone()
        
        if ans:
            await message.answer_video_note(ans[1], reply_markup=get_video_actions(ans[0]))
        else:
            await message.answer("✅ Кружок записан! Ты первый в базе, ждем других.")

# Жалобы
@dp.callback_query(F.data.startswith("report_"))
async def report(call: types.CallbackQuery):
    vid = call.data.split("_")[1]
    await bot.send_message(ADMIN_ID, f"🚩 <b>ЖАЛОБА</b>\nВидео ID: <code>{vid}</code>")
    await call.answer("Жалоба отправлена админу!", show_alert=True)

# --- ЗАПУСК ---
async def main():
    await init_db()
    asyncio.create_task(start_webserver())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())