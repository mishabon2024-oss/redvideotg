import asyncio
import aiosqlite
import logging
import sys
import os
import traceback
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.client.bot import DefaultBotProperties
from aiohttp import web

# --- НАСТРОЙКИ ---
TOKEN = '8725627105:AAFgdBu8u-AYlHRaGtFLUP12uvqGDJRsuco'
ADMIN_ID = 6907295206 
DEV_USERNAME = "@redperr"

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# На Render прокси НЕ нужен
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())

class MyStates(StatesGroup):
    waiting_for_ban = State()
    waiting_for_comment = State()

# --- ВЕБ-СЕРВЕР ДЛЯ ПОДДЕРЖКИ ЖИЗНИ (Anti-Sleep) ---
async def handle_ping(request):
    return web.Response(text="Bring OS Bot is Online!")

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render передает порт через переменную окружения
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ Anti-Sleep сервер запущен на порту {port}")

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ---
async def init_db():
    async with aiosqlite.connect('bot_data.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS videos 
                            (id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT, owner_id INTEGER)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
                            (user_id INTEGER PRIMARY KEY, username TEXT, views_count INTEGER DEFAULT 0, is_blocked INTEGER DEFAULT 0)''')
        await db.commit()
    print("✅ База данных SQLite готова.")

# --- ГЕНЕРАЦИЯ КЛАВИАТУР ---

def get_admin_kb():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats"))
    builder.row(types.InlineKeyboardButton(text="🚫 Бан по @username", callback_data="adm_ban_start"))
    builder.row(types.InlineKeyboardButton(text="🗑 Очистить базу", callback_data="adm_clear"))
    return builder.as_markup()

def get_video_actions(video_id):
    builder = InlineKeyboardBuilder()
    # TikTok-style: лайк и дизлайк просто кидают следующий кружок
    builder.row(
        types.InlineKeyboardButton(text="❤️", callback_data="next_video"),
        types.InlineKeyboardButton(text="❌", callback_data="next_video")
    )
    builder.row(
        types.InlineKeyboardButton(text="💬 Коммент", callback_data=f"add_comm_{video_id}"),
        types.InlineKeyboardButton(text="🚩 Жалоба", callback_data=f"report_{video_id}")
    )
    return builder.as_markup()

# --- ОБРАБОТЧИКИ КОМАНД ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    un = (message.from_user.username or "none").lower()
    async with aiosqlite.connect('bot_data.db') as db:
        await db.execute('''INSERT INTO users (user_id, username) VALUES (?, ?) 
                            ON CONFLICT(user_id) DO UPDATE SET username = excluded.username''', (uid, un))
        await db.commit()
    await message.answer(f"👋 Привет! Это бот обмена кружочками.\nПришли свой кружок — получишь случайный ответ!\n\n<b>Разработчик:</b> {DEV_USERNAME}")

@dp.message(Command("admin"))
async def open_admin(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("🛠 <b>ПАНЕЛЬ УПРАВЛЕНИЯ</b>", reply_markup=get_admin_kb())

# --- ЛОГИКА АДМИНКИ ---

@dp.callback_query(F.data == "adm_stats")
async def adm_stats(callback: types.CallbackQuery):
    async with aiosqlite.connect('bot_data.db') as db:
        async with db.execute("SELECT COUNT(*) FROM videos") as c1: v_count = (await c1.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users") as c2: u_count = (await c2.fetchone())[0]
    await callback.message.edit_text(f"📈 <b>Статистика:</b>\n\nКружков: {v_count}\nЮзеров: {u_count}", reply_markup=get_admin_kb())

@dp.callback_query(F.data == "adm_ban_start")
async def adm_ban_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Пришли @username (без @) для вечного бана:")
    await state.set_state(MyStates.waiting_for_ban)

@dp.message(MyStates.waiting_for_ban)
async def process_ban(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    target = message.text.replace("@", "").strip().lower()
    async with aiosqlite.connect('bot_data.db') as db:
        await db.execute("UPDATE users SET is_blocked = 1 WHERE username = ?", (target,))
        await db.commit()
    await message.answer(f"🚫 Пользователь @{target} успешно забанен!")
    await state.clear()

@dp.callback_query(F.data == "adm_clear")
async def adm_clear(callback: types.CallbackQuery):
    async with aiosqlite.connect('bot_data.db') as db:
        await db.execute("DELETE FROM videos")
        await db.commit()
    await callback.answer("База видео очищена!", show_alert=True)

# --- ЛОГИКА КОММЕНТАРИЕВ ---

@dp.callback_query(F.data.startswith("add_comm_"))
async def start_comm(call: types.CallbackQuery, state: FSMContext):
    video_id = call.data.split("_")[2]
    await state.update_data(v_id=video_id)
    await call.message.answer("Напиши сообщение автору этого кружка:")
    await state.set_state(MyStates.waiting_for_comment)

@dp.message(MyStates.waiting_for_comment)
async def save_comm(message: types.Message, state: FSMContext):
    data = await state.get_data()
    v_id = data.get("v_id")
    async with aiosqlite.connect('bot_data.db') as db:
        async with db.execute("SELECT owner_id FROM videos WHERE id = ?", (v_id,)) as cur:
            row = await cur.fetchone()
            if row:
                try:
                    await bot.send_message(row[0], f"💬 <b>Новый комментарий:</b>\n\n\"{message.text}\"")
                    await message.answer("✅ Комментарий доставлен!")
                except:
                    await message.answer("❌ Автор заблокировал бота.")
    await state.clear()

# --- ЛЕНТА КРУЖКОВ (TikTok Style) ---

@dp.callback_query(F.data == "next_video")
async def next_v(call: types.CallbackQuery):
    uid = call.from_user.id
    async with aiosqlite.connect('bot_data.db') as db:
        async with db.execute("SELECT id, file_id FROM videos WHERE owner_id != ? ORDER BY RANDOM() LIMIT 1", (uid,)) as cur:
            ans = await cur.fetchone()
        if ans:
            await call.message.answer_video_note(ans[1], reply_markup=get_video_actions(ans[0]))
        else:
            await call.answer("Кружков больше нет 😢", show_alert=True)
    await call.answer()

# --- ОСНОВНОЙ ПРИЕМ КРУЖКОВ ---

@dp.message(F.video_note)
async def handle_video(message: types.Message):
    uid = message.from_user.id
    un = (message.from_user.username or "none").lower()
    
    async with aiosqlite.connect('bot_data.db') as db:
        # Обновляем инфу о юзере
        await db.execute("INSERT OR REPLACE INTO users (user_id, username, views_count, is_blocked) VALUES (?, ?, (SELECT views_count FROM users WHERE user_id=?), (SELECT is_blocked FROM users WHERE user_id=?))", (uid, un, uid, uid))
        
        async with db.execute("SELECT is_blocked, views_count FROM users WHERE user_id = ?", (uid,)) as cur:
            res = await cur.fetchone()
            if res and res[0]: return # Бан
            views = res[1] if res else 0

        # Лимит для всех кроме админа
        if views >= 3 and uid != ADMIN_ID:
            return await message.answer("❌ Твой лимит (3 кружка) исчерпан!")

        # Сохраняем видео
        await db.execute("INSERT INTO videos (file_id, owner_id) VALUES (?, ?)", (message.video_note.file_id, uid))
        
        # Выдаем случайное в ответ
        async with db.execute("SELECT id, file_id FROM videos WHERE owner_id != ? ORDER BY RANDOM() LIMIT 1", (uid,)) as cur:
            ans = await cur.fetchone()
        
        if ans:
            await message.answer_video_note(ans[1], reply_markup=get_video_actions(ans[0]))
            await db.execute("UPDATE users SET views_count = views_count + 1 WHERE user_id = ?", (uid,))
        else:
            await message.answer("Ты первый! Ждем новых участников.")
        await db.commit()

# --- СИСТЕМА ЖАЛОБ ---

@dp.callback_query(F.data.startswith("report_"))
async def report(call: types.CallbackQuery):
    vid = call.data.split("_")[1]
    await bot.send_message(ADMIN_ID, f"🚩 <b>ЖАЛОБА</b>\nВидео ID: <code>{vid}</code>")
    await call.answer("Жалоба отправлена админу!", show_alert=True)

# --- ЗАПУСК ---

async def main():
    await init_db()
    # Фоновая задача сервера для Render
    asyncio.create_task(start_webserver())
    await bot.delete_webhook(drop_pending_updates=True)
    print("🚀 БОТ ЗАПУЩЕН НА RENDER!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except:
        logging.error("Shutdown")