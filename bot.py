import asyncio
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError

# Токен бота
BOT_TOKEN = "8819755559:AAEIirNZ4qessdkp3XGlrWx1WAY-r7CtmDg"[cite: 1]

# ID Администратора
ADMIN_ID = 8037758285[cite: 1]

# Юзернейм админа для связи
ADMIN_USERNAME = "@buhovi"[cite: 1]

# Глобальный статус бота (True = включен, False = выключен)
BOT_ENABLED = True[cite: 1]

# ID канала для проверки подписки
CHANNEL_ID = -1004414833916[cite: 1]
CHANNEL_LINK = "https://t.me/basuyi"[cite: 1]

# Запрещенный список для записи в базу данных
BLOCKED_INPUTS = {[cite: 1]
    "@buhovi", "buhovi",[cite: 1]
    "8037758285",[cite: 1]
    "8215610247",[cite: 1]
    "@buwixo", "buwixo",[cite: 1]
    "6187980888",[cite: 1]
    "6489694723",[cite: 1]
    "8792534896"[cite: 1]
}

# --- РАБОТА С БАЗОЙ ДАННЫХ ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))[cite: 1]
DB_NAME = os.path.join(BASE_DIR, "bot_data.db")[cite: 1]

def escape_markdown(text: str) -> str:[cite: 1]
    """Вспомогательная функция для экранирования спецсимволов Markdown"""
    if not text:[cite: 1]
        return ""[cite: 1]
    return text.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")[cite: 1]

def init_db():[cite: 1]
    conn = sqlite3.connect(DB_NAME)[cite: 1]
    cursor = conn.cursor()[cite: 1]
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            sender_username TEXT,
            target_input TEXT,
            timestamp TEXT
        )
    ''')[cite: 1]
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_users_stats (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            transfers_count INTEGER DEFAULT 0,
            joined_at TEXT,
            subscription_until TEXT
        )
    ''')[cite: 1]

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id INTEGER,
            referred_id INTEGER PRIMARY KEY,
            rewarded INTEGER DEFAULT 0,
            created_at TEXT
        )
    ''')[cite: 1]
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_text TEXT,
            created_at TEXT
        )
    ''')[cite: 1]
    conn.commit()[cite: 1]
    conn.close()[cite: 1]

def register_or_update_user(user_id: int, username: str):[cite: 1]
    conn = sqlite3.connect(DB_NAME)[cite: 1]
    cursor = conn.cursor()[cite: 1]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")[cite: 1]
    
    cursor.execute('SELECT user_id FROM bot_users_stats WHERE user_id = ?', (user_id,))[cite: 1]
    row = cursor.fetchone()[cite: 1]
    
    if not row:[cite: 1]
        cursor.execute('''
            INSERT INTO bot_users_stats (user_id, username, transfers_count, joined_at, subscription_until)
            VALUES (?, ?, 0, ?, NULL)
        ''', (user_id, username or "", now))[cite: 1]
    else:
        cursor.execute('''
            UPDATE bot_users_stats SET username = ? WHERE user_id = ?
        ''', (username or "", user_id))[cite: 1]
        
    conn.commit()[cite: 1]
    conn.close()[cite: 1]

def add_referral_link(referrer_id: int, referred_id: int):[cite: 1]
    if referrer_id == referred_id:[cite: 1]
        return[cite: 1]
        
    conn = sqlite3.connect(DB_NAME)[cite: 1]
    cursor = conn.cursor()[cite: 1]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")[cite: 1]
    
    cursor.execute('SELECT referred_id FROM referrals WHERE referred_id = ?', (referred_id,))[cite: 1]
    if not cursor.fetchone():[cite: 1]
        cursor.execute('''
            INSERT INTO referrals (referrer_id, referred_id, rewarded, created_at)
            VALUES (?, ?, 0, ?)
        ''', (referrer_id, referred_id, now))[cite: 1]
        conn.commit()[cite: 1]
    conn.close()[cite: 1]

def process_referral_reward(referred_id: int) -> int | None:[cite: 1]
    conn = sqlite3.connect(DB_NAME)[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute('SELECT referrer_id, rewarded FROM referrals WHERE referred_id = ?', (referred_id,))[cite: 1]
    row = cursor.fetchone()[cite: 1]
    
    if row and row[1] == 0:[cite: 1]
        referrer_id = row[0][cite: 1]
        cursor.execute('UPDATE referrals SET rewarded = 1 WHERE referred_id = ?', (referred_id,))[cite: 1]
        conn.commit()[cite: 1]
        conn.close()[cite: 1]
        
        add_user_subscription(referrer_id, timedelta(hours=1))[cite: 1]
        return referrer_id[cite: 1]
        
    conn.close()[cite: 1]
    return None[cite: 1]

def increment_user_transfers(user_id: int, username: str):[cite: 1]
    conn = sqlite3.connect(DB_NAME)[cite: 1]
    cursor = conn.cursor()[cite: 1]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")[cite: 1]
    cursor.execute('''
        INSERT INTO bot_users_stats (user_id, username, transfers_count, joined_at)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(user_id) DO UPDATE SET 
            username = excluded.username,
            transfers_count = transfers_count + 1
    ''', (user_id, username or "", now))[cite: 1]
    conn.commit()[cite: 1]
    conn.close()[cite: 1]

def add_user_subscription(user_id: int, duration: timedelta) -> datetime:[cite: 1]
    conn = sqlite3.connect(DB_NAME)[cite: 1]
    cursor = conn.cursor()[cite: 1]
    current_sub = get_user_subscription(user_id)[cite: 1]
    now = datetime.now()[cite: 1]
    
    if current_sub and current_sub != "INFINITE" and isinstance(current_sub, datetime) and current_sub > now:[cite: 1]
        new_expires = current_sub + duration[cite: 1]
    else:
        new_expires = now + duration[cite: 1]
        
    exp_str = new_expires.strftime("%Y-%m-%d %H:%M:%S")[cite: 1]
    cursor.execute('UPDATE bot_users_stats SET subscription_until = ? WHERE user_id = ?', (exp_str, user_id))[cite: 1]
    conn.commit()[cite: 1]
    conn.close()[cite: 1]
    return new_expires[cite: 1]

def set_user_subscription_infinite(user_id: int):[cite: 1]
    conn = sqlite3.connect(DB_NAME)[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute('UPDATE bot_users_stats SET subscription_until = "INFINITE" WHERE user_id = ?', (user_id,))[cite: 1]
    conn.commit()[cite: 1]
    conn.close()[cite: 1]

def get_user_subscription(user_id: int) -> datetime | str | None:[cite: 1]
    conn = sqlite3.connect(DB_NAME)[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute('SELECT subscription_until FROM bot_users_stats WHERE user_id = ?', (user_id,))[cite: 1]
    row = cursor.fetchone()[cite: 1]
    conn.close()[cite: 1]
    if row and row[0]:[cite: 1]
        if row[0] == "INFINITE":[cite: 1]
            return "INFINITE"[cite: 1]
        try:
            return datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")[cite: 1]
        except ValueError:
            return None[cite: 1]
    return None[cite: 1]

def is_subscription_active(user_id: int) -> bool:[cite: 1]
    if user_id == ADMIN_ID:[cite: 1]
        return True[cite: 1]
    sub = get_user_subscription(user_id)[cite: 1]
    if sub == "INFINITE":[cite: 1]
        return True[cite: 1]
    if isinstance(sub, datetime) and sub > datetime.now():[cite: 1]
        return True[cite: 1]
    return False[cite: 1]

def save_to_db(sender_id: int, sender_username: str, target_input: str) -> int | bool | None:[cite: 1]
    clean_input = target_input.strip().lower()[cite: 1]
    for item in BLOCKED_INPUTS:[cite: 1]
        if item in clean_input:[cite: 1]
            print(f"[БЛОКИРОВКА БД] Запись '{target_input}' отклонена.")[cite: 1]
            return False[cite: 1]

    conn = sqlite3.connect(DB_NAME)[cite: 1]
    cursor = conn.cursor()[cite: 1]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")[cite: 1]
    cursor.execute('''
        INSERT INTO transfers (sender_id, sender_username, target_input, timestamp)
        VALUES (?, ?, ?, ?)
    ''', (sender_id, sender_username, target_input, now))[cite: 1]
    record_id = cursor.lastrowid[cite: 1]
    conn.commit()[cite: 1]
    conn.close()[cite: 1]

    increment_user_transfers(sender_id, sender_username)[cite: 1]
    return record_id[cite: 1]

def check_record_status(record_id: int) -> tuple[bool, int]:[cite: 1]
    conn = sqlite3.connect(DB_NAME)[cite: 1]
    cursor = conn.cursor()[cite: 1]
    try:
        cursor.execute('SELECT reports_count FROM transfers WHERE id = ?', (record_id,))[cite: 1]
        row = cursor.fetchone()[cite: 1]
        conn.close()[cite: 1]
        if row:[cite: 1]
            return True, row[0] or 0[cite: 1]
        return False, 0[cite: 1]
    except sqlite3.OperationalError:
        cursor.execute('SELECT 1 FROM transfers WHERE id = ?', (record_id,))[cite: 1]
        row = cursor.fetchone()[cite: 1]
        conn.close()[cite: 1]
        return row is not None, 0[cite: 1]

def get_all_users_ids() -> list[int]:[cite: 1]
    conn = sqlite3.connect(DB_NAME)[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute('SELECT user_id FROM bot_users_stats')[cite: 1]
    rows = cursor.fetchall()[cite: 1]
    conn.close()[cite: 1]
    return [row[0] for row in rows if row[0]][cite: 1]

def get_users_list_from_db() -> list[tuple[int, str, int, str]]:[cite: 1]
    conn = sqlite3.connect(DB_NAME)[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute('''
        SELECT user_id, username, transfers_count, subscription_until
        FROM bot_users_stats
        ORDER BY transfers_count DESC
    ''')[cite: 1]
    rows = cursor.fetchall()[cite: 1]
    conn.close()[cite: 1]
    return rows[cite: 1]

def save_pending_broadcast(text: str):[cite: 1]
    conn = sqlite3.connect(DB_NAME)[cite: 1]
    cursor = conn.cursor()[cite: 1]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")[cite: 1]
    cursor.execute('INSERT INTO pending_broadcasts (message_text, created_at) VALUES (?, ?)', (text, now))[cite: 1]
    conn.commit()[cite: 1]
    conn.close()[cite: 1]

def get_and_clear_pending_broadcasts() -> list[str]:[cite: 1]
    conn = sqlite3.connect(DB_NAME)[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute('SELECT message_text FROM pending_broadcasts ORDER BY id ASC')[cite: 1]
    rows = cursor.fetchall()[cite: 1]
    cursor.execute('DELETE FROM pending_broadcasts')[cite: 1]
    conn.commit()[cite: 1]
    conn.close()[cite: 1]
    return [row[0] for row in rows][cite: 1]

def parse_time_duration(time_str: str) -> timedelta | None:[cite: 1]
    time_str = time_str.lower().strip()[cite: 1]
    pattern = r'(?:(\d+)\s*д)?\s*(?:(\d+)\s*ч)?\s*(?:(\d+)\s*м)?'[cite: 1]
    match = re.fullmatch(pattern, time_str)[cite: 1]
    
    if not match or not any(match.groups()):[cite: 1]
        return None[cite: 1]
        
    days = int(match.group(1) or 0)[cite: 1]
    hours = int(match.group(2) or 0)[cite: 1]
    minutes = int(match.group(3) or 0)[cite: 1]
    
    if days == 0 and hours == 0 and minutes == 0:[cite: 1]
        return None[cite: 1]
        
    return timedelta(days=days, hours=hours, minutes=minutes)[cite: 1]

# -----------------------------

bot = Bot(token=BOT_TOKEN)[cite: 1]
dp = Dispatcher(storage=MemoryStorage())[cite: 1]

class TransferState(StatesGroup):[cite: 1]
    waiting_for_target = State()[cite: 1]

class AdminState(StatesGroup):[cite: 1]
    waiting_for_broadcast_text = State()[cite: 1]
    waiting_for_grant_sub = State()[cite: 1]

@dp.message.outer_middleware()[cite: 1]
@dp.callback_query.outer_middleware()[cite: 1]
async def bot_status_middleware(handler, event, data):[cite: 1]
    user = getattr(event, "from_user", None)[cite: 1]
    if user:[cite: 1]
        register_or_update_user(user.id, user.username)[cite: 1]

    if user and not BOT_ENABLED and user.id != ADMIN_ID:[cite: 1]
        if isinstance(event, CallbackQuery):[cite: 1]
            await event.answer("⚠️ Бот временно отключен на техническое обслуживание.", show_alert=True)[cite: 1]
        return[cite: 1]
    return await handler(event, data)[cite: 1]

def log_action(user, text: str):[cite: 1]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")[cite: 1]
    username_part = f" @{user.username}" if user.username else ""[cite: 1]
    print(f"[{now}]{username_part} id:{user.id} text:{text}")[cite: 1]

async def execute_broadcast(broadcast_msg: str) -> tuple[int, int]:[cite: 1]
    users = get_all_users_ids()[cite: 1]
    success_count = 0[cite: 1]
    fail_count = 0[cite: 1]
    for user_id in users:[cite: 1]
        try:
            await bot.send_message(chat_id=user_id, text=f"📢 **ОБЪЯВЛЕНИЕ:**\n\n{broadcast_msg}", parse_mode="Markdown")[cite: 1]
            success_count += 1[cite: 1]
            await asyncio.sleep(0.05)[cite: 1]
        except TelegramAPIError:
            fail_count += 1[cite: 1]
    return success_count, fail_count[cite: 1]

def get_subscribe_keyboard():[cite: 1]
    return InlineKeyboardMarkup([cite: 1]
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться на канал", url=CHANNEL_LINK)],[cite: 1]
            [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")][cite: 1]
        ]
    )

def get_no_access_keyboard():[cite: 1]
    return InlineKeyboardMarkup([cite: 1]
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Получить бесплатно", callback_data="sub_free_menu")],[cite: 1]
            [InlineKeyboardButton(text="⭐ Купить подписку", callback_data="sub_buy")][cite: 1]
        ]
    )

def get_free_menu_keyboard():[cite: 1]
    return InlineKeyboardMarkup([cite: 1]
        inline_keyboard=[
            [InlineKeyboardButton(text="📧 Google аккаунт (12 часов)", callback_data="free_google")],[cite: 1]
            [InlineKeyboardButton(text="👥 Пригласить реферала (+1 час)", callback_data="free_referral")],[cite: 1]
            [InlineKeyboardButton(text="◀️ Назад", callback_data="sub_back")][cite: 1]
        ]
    )

def get_main_menu(user_id: int):[cite: 1]
    keyboard = [[cite: 1]
        [InlineKeyboardButton(text="💥 Снести аккаунт", callback_data="start_transfer")][cite: 1]
    ]
    if user_id == ADMIN_ID:[cite: 1]
        keyboard.append([InlineKeyboardButton(text="⚙️ Админ панель", callback_data="admin_panel")])[cite: 1]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)[cite: 1]

def get_admin_keyboard():[cite: 1]
    toggle_button = ([cite: 1]
        InlineKeyboardButton(text="⛔ Выключить бота", callback_data="admin_toggle_bot")[cite: 1]
        if BOT_ENABLED else[cite: 1]
        InlineKeyboardButton(text="✅ Включить бота", callback_data="admin_toggle_bot")[cite: 1]
    )
    return InlineKeyboardMarkup([cite: 1]
        inline_keyboard=[
            [InlineKeyboardButton(text="🔑 Выдать подписку", callback_data="admin_grant_sub")],[cite: 1]
            [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_users_list")],[cite: 1]
            [InlineKeyboardButton(text="📢 Объявление", callback_data="admin_broadcast")],[cite: 1]
            [toggle_button],[cite: 1]
            [InlineKeyboardButton(text="🔄 Перезагрузить бота", callback_data="admin_restart")],[cite: 1]
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")][cite: 1]
        ]
    )

def get_admin_text():[cite: 1]
    status = "🟢 Включен" if BOT_ENABLED else "🔴 Выключен (доступен только вам)"[cite: 1]
    return f"👑 **Административная панель**\n\nСтатус бота: `{status}`"[cite: 1]

async def check_user_subscribed(user_id: int) -> bool:[cite: 1]
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)[cite: 1]
        return member.status in ["creator", "administrator", "member"][cite: 1]
    except TelegramBadRequest:
        return False[cite: 1]

def validate_user_and_id(text: str) -> bool:[cite: 1]
    has_username = bool(re.search(r'@[a-zA-Z0-9_]{4,}', text))[cite: 1]
    has_id = bool(re.search(r'\b\d{6,12}\b', text))[cite: 1]
    return has_username and has_id[cite: 1]

# --- АДМИН ПАНЕЛЬ ---

@dp.message(Command("admin"))[cite: 1]
async def cmd_admin(message: Message, state: FSMContext):[cite: 1]
    await state.clear()[cite: 1]
    if message.from_user.id != ADMIN_ID:[cite: 1]
        return[cite: 1]
    await message.answer(get_admin_text(), reply_markup=get_admin_keyboard(), parse_mode="Markdown")[cite: 1]

@dp.callback_query(F.data == "admin_panel")[cite: 1]
async def process_admin_panel(callback: CallbackQuery, state: FSMContext):[cite: 1]
    await state.clear()[cite: 1]
    if callback.from_user.id != ADMIN_ID:[cite: 1]
        await callback.answer("⛔ Доступ запрещен!", show_alert=True)[cite: 1]
        return[cite: 1]
    await callback.message.edit_text(get_admin_text(), reply_markup=get_admin_keyboard(), parse_mode="Markdown")[cite: 1]

@dp.callback_query(F.data == "admin_back")[cite: 1]
async def process_admin_back(callback: CallbackQuery, state: FSMContext):[cite: 1]
    await state.clear()[cite: 1]
    await callback.message.edit_text([cite: 1]
        "Вы вернулись в главное меню:",[cite: 1]
        reply_markup=get_main_menu(callback.from_user.id)[cite: 1]
    )

@dp.callback_query(F.data == "admin_grant_sub")[cite: 1]
async def process_admin_grant_sub(callback: CallbackQuery, state: FSMContext):[cite: 1]
    if callback.from_user.id != ADMIN_ID:[cite: 1]
        return[cite: 1]
    await state.set_state(AdminState.waiting_for_grant_sub)[cite: 1]
    
    text = ([cite: 1]
        "🔑 **Выдача подписки**\n\n"[cite: 1]
        "Отправьте ID пользователя и время подписки через пробел.\n\n"[cite: 1]
        "**Примеры:**\n"[cite: 1]
        "`11111111111 1д` — выдаст подписку на 1 день\n"[cite: 1]
        "`11111111111 12ч` — выдаст подписку на 12 часов\n"[cite: 1]
        "`11111111111 бесконечно` — выдаст **бесконечную** подписку"[cite: 1]
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[cite: 1]
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_panel")][cite: 1]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")[cite: 1]
    await callback.answer()[cite: 1]

@dp.message(AdminState.waiting_for_grant_sub)[cite: 1]
async def process_grant_sub_input(message: Message, state: FSMContext):[cite: 1]
    if message.from_user.id != ADMIN_ID:[cite: 1]
        return[cite: 1]

    if message.text and message.text.startswith("/"):[cite: 1]
        return[cite: 1]

    parts = message.text.strip().split()[cite: 1]
    if len(parts) != 2 or not parts[0].isdigit():[cite: 1]
        await message.answer("❌ **Ошибка формата!** Отправьте ID и время/режим через пробел.\nПример: `11111111111 бесконечно` или `11111111111 1д`", parse_mode="Markdown")[cite: 1]
        return[cite: 1]

    target_id = int(parts[0])[cite: 1]
    time_str = parts[1].lower()[cite: 1]

    if time_str in ["бесконечно", "навсегда", "inf", "infinite"]:[cite: 1]
        set_user_subscription_infinite(target_id)[cite: 1]
        await state.clear()[cite: 1]
        
        await message.answer([cite: 1]
            f"✅ **Выдана бесконечная подписка!**\n\n"[cite: 1]
            f"👤 ID: `{target_id}`\n"[cite: 1]
            f"⏳ Срок: `Бесконечно`",[cite: 1]
            reply_markup=get_admin_keyboard(),[cite: 1]
            parse_mode="Markdown"[cite: 1]
        )
        try:
            await bot.send_message([cite: 1]
                chat_id=target_id,[cite: 1]
                text="🎉 **Вам выдана БЕСКОНЕЧНАЯ подписка!**\n\nТеперь вам навсегда доступны все функции бота.",[cite: 1]
                reply_markup=get_main_menu(target_id),[cite: 1]
                parse_mode="Markdown"[cite: 1]
            )
        except TelegramAPIError:
            await message.answer("⚠️ Подписка сохранена, но не удалось отправить сообщение пользователю.")[cite: 1]
        return[cite: 1]

    duration = parse_time_duration(time_str)[cite: 1]
    if not duration:[cite: 1]
        await message.answer("❌ **Неверный формат времени!** Используйте комбинации `д`, `ч`, `м` (например: `1д`, `12ч`) или напишите `бесконечно`.", parse_mode="Markdown")[cite: 1]
        return[cite: 1]

    new_expires = add_user_subscription(target_id, duration)[cite: 1]
    await state.clear()[cite: 1]

    formatted_exp = new_expires.strftime("%d.%m.%Y %H:%M")[cite: 1]
    await message.answer([cite: 1]
        f"✅ **Подписка успешно выдана!**\n\n"[cite: 1]
        f"👤 ID: `{target_id}`\n"[cite: 1]
        f"⏳ Действует до: `{formatted_exp}`",[cite: 1]
        reply_markup=get_admin_keyboard(),[cite: 1]
        parse_mode="Markdown"[cite: 1]
    )

    try:
        await bot.send_message([cite: 1]
            chat_id=target_id,[cite: 1]
            text=f"🎉 **Вам выдана подписка!**\n\nДействительна до: `{formatted_exp}`\nТеперь вам доступны все функции бота.",[cite: 1]
            reply_markup=get_main_menu(target_id),[cite: 1]
            parse_mode="Markdown"[cite: 1]
        )
    except TelegramAPIError:
        await message.answer("⚠️ Подписка сохранена, но не удалось отправить сообщение пользователю.")[cite: 1]

@dp.callback_query(F.data == "admin_users_list")[cite: 1]
async def process_admin_users_list(callback: CallbackQuery):[cite: 1]
    if callback.from_user.id != ADMIN_ID:[cite: 1]
        return[cite: 1]
    
    users = get_users_list_from_db()[cite: 1]
    if not users:[cite: 1]
        await callback.message.edit_text("👥 В базе данных пока нет сохранённых пользователей.", reply_markup=get_admin_keyboard())[cite: 1]
        await callback.answer()[cite: 1]
        return[cite: 1]

    text_lines = ["📋 **Список всех пользователей бота:**\n"][cite: 1]
    now = datetime.now()[cite: 1]
    for user_id, username, count, sub_until in users:[cite: 1]
        user_mention = f"@{escape_markdown(username)}" if username else "[без юзернейма]"[cite: 1]
        sub_status = "❌ Нет"[cite: 1]
        if user_id == ADMIN_ID:[cite: 1]
            sub_status = "👑 Навсегда (Админ)"[cite: 1]
        elif sub_until == "INFINITE":[cite: 1]
            sub_status = "♾️ Бесконечно"[cite: 1]
        elif sub_until:[cite: 1]
            try:
                sub_date = datetime.strptime(sub_until, "%Y-%m-%d %H:%M:%S")[cite: 1]
                if sub_date > now:[cite: 1]
                    sub_status = f"✅ До {sub_date.strftime('%d.%m %H:%M')}"[cite: 1]
                else:
                    sub_status = "❌ Истекла"[cite: 1]
            except ValueError:
                pass[cite: 1]

        text_lines.append(f"{user_mention} id : `{user_id}` ({count}) | Подписка: {sub_status}")[cite: 1]

    full_text = "\n".join(text_lines)[cite: 1]
    
    try:
        if len(full_text) > 3500:[cite: 1]
            chunk = text_lines[0] + "\n"[cite: 1]
            for line in text_lines[1:]:[cite: 1]
                if len(chunk) + len(line) + 1 > 3500:[cite: 1]
                    await callback.message.answer(chunk, parse_mode="Markdown")[cite: 1]
                    chunk = ""[cite: 1]
                chunk += line + "\n"[cite: 1]
            if chunk:[cite: 1]
                await callback.message.answer(chunk, reply_markup=get_admin_keyboard(), parse_mode="Markdown")[cite: 1]
        else:
            await callback.message.edit_text(full_text, reply_markup=get_admin_keyboard(), parse_mode="Markdown")[cite: 1]
    except TelegramBadRequest as e:
        await callback.message.answer(f"❌ Ошибка разметки сообщения: {e.message}")[cite: 1]
        
    await callback.answer()[cite: 1]

@dp.callback_query(F.data == "admin_toggle_bot")[cite: 1]
async def process_admin_toggle_bot(callback: CallbackQuery):[cite: 1]
    global BOT_ENABLED[cite: 1]
    if callback.from_user.id != ADMIN_ID:[cite: 1]
        return[cite: 1]
    
    BOT_ENABLED = not BOT_ENABLED[cite: 1]
    status_msg = "включен" if BOT_ENABLED else "выключен для пользователей"[cite: 1]
    log_action(callback.from_user, f"[АДМИН] Бот был {status_msg}")[cite: 1]
    
    await callback.answer(f"Бот {status_msg}!", show_alert=True)[cite: 1]
    await callback.message.edit_text(get_admin_text(), reply_markup=get_admin_keyboard(), parse_mode="Markdown")[cite: 1]

    if BOT_ENABLED:[cite: 1]
        pending_broadcasts = get_and_clear_pending_broadcasts()[cite: 1]
        if pending_broadcasts:[cite: 1]
            await callback.message.answer(f"🔄 **Бот включен.** Начинаю отправку отложенных объявлений ({len(pending_broadcasts)} шт.)...", parse_mode="Markdown")[cite: 1]
            for msg in pending_broadcasts:[cite: 1]
                succ, fail = await execute_broadcast(msg)[cite: 1]
                await callback.message.answer([cite: 1]
                    f"✅ **Отложенное объявление отправлено!**\n\n"[cite: 1]
                    f"Доставлено: `{succ}`\n"[cite: 1]
                    f"Не доставлено: `{fail}`",[cite: 1]
                    parse_mode="Markdown"[cite: 1]
                )

@dp.callback_query(F.data == "admin_broadcast")[cite: 1]
async def process_admin_broadcast(callback: CallbackQuery, state: FSMContext):[cite: 1]
    if callback.from_user.id != ADMIN_ID:[cite: 1]
        return[cite: 1]
    await state.set_state(AdminState.waiting_for_broadcast_text)[cite: 1]
    kb = InlineKeyboardMarkup(inline_keyboard=[[cite: 1]
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_panel")][cite: 1]
    ])
    await callback.message.edit_text("📝 Отправьте текст объявления, которое получат все пользователи бота:", reply_markup=kb)[cite: 1]
    await callback.answer()[cite: 1]

@dp.message(AdminState.waiting_for_broadcast_text)[cite: 1]
async def process_broadcast_text(message: Message, state: FSMContext):[cite: 1]
    if message.from_user.id != ADMIN_ID:[cite: 1]
        return[cite: 1]

    if message.text and message.text.startswith("/"):[cite: 1]
        return[cite: 1]

    broadcast_msg = message.text[cite: 1]

    if not BOT_ENABLED:[cite: 1]
        save_pending_broadcast(broadcast_msg)[cite: 1]
        await message.answer([cite: 1]
            "⏳ **Бот сейчас выключен.**\n\nОбъявление сохранено в очередь и будет **автоматически отправлено** сразу после того, как вы включите бота!",[cite: 1]
            reply_markup=get_admin_keyboard(),[cite: 1]
            parse_mode="Markdown"[cite: 1]
        )
        await state.clear()[cite: 1]
        return[cite: 1]

    users = get_all_users_ids()[cite: 1]
    if not users:[cite: 1]
        await message.answer("❌ В базе данных пока нет пользователей для рассылки.", reply_markup=get_admin_keyboard())[cite: 1]
        await state.clear()[cite: 1]
        return[cite: 1]

    await message.answer(f"⏳ Начинаю рассылку для {len(users)} пользователей...")[cite: 1]
    success_count, fail_count = await execute_broadcast(broadcast_msg)[cite: 1]

    await message.answer([cite: 1]
        f"✅ **Рассылка завершена!**\n\n"[cite: 1]
        f"Успешно доставлено: `{success_count}`\n"[cite: 1]
        f"Не доставлено (заблокировали бота): `{fail_count}`",[cite: 1]
        reply_markup=get_admin_keyboard(),[cite: 1]
        parse_mode="Markdown"[cite: 1]
    )
    await state.clear()[cite: 1]

@dp.callback_query(F.data == "admin_restart")[cite: 1]
async def process_admin_restart(callback: CallbackQuery):[cite: 1]
    if callback.from_user.id != ADMIN_ID:[cite: 1]
        return[cite: 1]
    await callback.message.edit_text("🔄 **Перезагрузка бота...**", parse_mode="Markdown")[cite: 1]
    log_action(callback.from_user, "[АДМИН] Запросил перезагрузку бота")[cite: 1]
    
    os.execl(sys.executable, sys.executable, *sys.argv)

# --- РАЗВИЛКА БЕСПЛАТНОЙ ПОДПИСКИ ---

@dp.callback_query(F.data == "sub_free_menu")[cite: 1]
async def process_sub_free_menu(callback: CallbackQuery):[cite: 1]
    text = ([cite: 1]
        "🎁 **Получение бесплатного доступа**\n\n"[cite: 1]
        "Выберите удобный вариант получения подписки:"[cite: 1]
    )
    await callback.message.edit_text(text, reply_markup=get_free_menu_keyboard(), parse_mode="Markdown")[cite: 1]

@dp.callback_query(F.data == "free_google")[cite: 1]
async def process_free_google(callback: CallbackQuery):[cite: 1]
    text = ([cite: 1]
        "📧 **Бесплатная подписка на 12 часов (полдня) за Google аккаунт**\n\n"[cite: 1]
        "Чтобы получить подписку на 12 часов бесплатно, вам нужно создать **новый Google аккаунт** и прислать логин (почту) и пароль администратору.\n\n"[cite: 1]
        f"📩 Отправьте данные администратору: {ADMIN_USERNAME}\n\n"[cite: 1]
        "После проверки данных вам будет зачислена подписка!"[cite: 1]
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[cite: 1]
        [InlineKeyboardButton(text="💬 Написать админу", url="https://t.me/buhovi")],[cite: 1]
        [InlineKeyboardButton(text="◀️ Назад", callback_data="sub_free_menu")][cite: 1]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")[cite: 1]

@dp.callback_query(F.data == "free_referral")[cite: 1]
async def process_free_referral(callback: CallbackQuery):[cite: 1]
    bot_info = await bot.get_me()[cite: 1]
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{callback.from_user.id}"[cite: 1]
    
    text = ([cite: 1]
        "👥 **Реферальная система (+1 час за каждого реферала)**\n\n"[cite: 1]
        "За **каждого** приглашенного пользователя вы получаете **+1 час подписки**.\n\n"[cite: 1]
        "⚠️ **Условие:** Ваш реферал должен перейти по ссылке и **обязательно подписаться на канал**.\n\n"[cite: 1]
        f"🔗 **Ваша персональная реферальная ссылка:**\n`{ref_link}`"[cite: 1]
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[cite: 1]
        [InlineKeyboardButton(text="◀️ Назад", callback_data="sub_free_menu")][cite: 1]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")[cite: 1]

@dp.callback_query(F.data == "sub_buy")[cite: 1]
async def process_sub_buy(callback: CallbackQuery):[cite: 1]
    text = ([cite: 1]
        "⭐ **Расценки на подписку (в Telegram Stars):**\n\n"[cite: 1]
        "• **1 день** — 25 звезд ⭐\n"[cite: 1]
        "• **3 дня** — 40 звезд ⭐\n"[cite: 1]
        "• **7 дней** — 65 звезд ⭐\n\n"[cite: 1]
        f"Для покупки выберите нужный тариф, отправьте звезды администратору {ADMIN_USERNAME} и напишите ему свой ID.\n\n"[cite: 1]
        f"Ваш ID: `{callback.from_user.id}`"[cite: 1]
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[cite: 1]
        [InlineKeyboardButton(text="💬 Оплатить и написать админу", url="https://t.me/buhovi")],[cite: 1]
        [InlineKeyboardButton(text="◀️ Назад", callback_data="sub_back")][cite: 1]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")[cite: 1]

@dp.callback_query(F.data == "sub_back")[cite: 1]
async def process_sub_back(callback: CallbackQuery):[cite: 1]
    await callback.message.edit_text([cite: 1]
        "⛔ **Доступ ограничен!**\n\nУ вас нет активной подписки. Выберите способ получения доступа ниже:",[cite: 1]
        reply_markup=get_no_access_keyboard(),[cite: 1]
        parse_mode="Markdown"[cite: 1]
    )

# --- ОСНОВНАЯ ЛОГИКА ---

@dp.message(CommandStart())[cite: 1]
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):[cite: 1]
    await state.clear()[cite: 1]
    log_action(message.from_user, message.text or "[без текста]")[cite: 1]
    
    register_or_update_user(message.from_user.id, message.from_user.username)[cite: 1]
    
    if command.args and command.args.startswith("ref_"):[cite: 1]
        ref_str = command.args.replace("ref_", "")[cite: 1]
        if ref_str.isdigit():[cite: 1]
            referrer_id = int(ref_str)[cite: 1]
            add_referral_link(referrer_id, message.from_user.id)[cite: 1]

    is_subscribed = await check_user_subscribed(message.from_user.id)[cite: 1]
    if not is_subscribed:[cite: 1]
        await message.answer([cite: 1]
            "👋 Для использования бота необходимо подписаться на наш канал!",[cite: 1]
            reply_markup=get_subscribe_keyboard()[cite: 1]
        )
        return[cite: 1]

    rewarded_ref_id = process_referral_reward(message.from_user.id)[cite: 1]
    if rewarded_ref_id:[cite: 1]
        try:
            ref_sub_date = get_user_subscription(rewarded_ref_id)[cite: 1]
            exp_str = "Бесконечно" if ref_sub_date == "INFINITE" else (ref_sub_date.strftime("%d.%m.%Y %H:%M") if ref_sub_date else "")[cite: 1]
            await bot.send_message([cite: 1]
                chat_id=rewarded_ref_id,[cite: 1]
                text=f"🎉 **Ваш реферал зарегистрировался и подписался на канал!**\n\nВам начислено **+1 час подписки**.\nНовый срок: `{exp_str}`",[cite: 1]
                parse_mode="Markdown"[cite: 1]
            )
        except TelegramAPIError:
            pass[cite: 1]

    if not is_subscription_active(message.from_user.id):[cite: 1]
        await message.answer([cite: 1]
            "⛔ **Доступ ограничен!**\n\nУ вас нет активной подписки. Выберите способ получения доступа ниже:",[cite: 1]
            reply_markup=get_no_access_keyboard(),[cite: 1]
            parse_mode="Markdown"[cite: 1]
        )
        return[cite: 1]

    exp_date = get_user_subscription(message.from_user.id)[cite: 1]
    if message.from_user.id == ADMIN_ID:[cite: 1]
        sub_text = "👑 Бесконечная (Администратор)"[cite: 1]
    elif exp_date == "INFINITE":[cite: 1]
        sub_text = "♾️ Бесконечная"[cite: 1]
    else:
        sub_text = f"до {exp_date.strftime('%d.%m.%Y %H:%M')}"[cite: 1]

    await message.answer([cite: 1]
        f"Добро пожаловать!\nВаша подписка активна: `{sub_text}`\n\nВыберите действие из меню ниже:",[cite: 1]
        reply_markup=get_main_menu(message.from_user.id),[cite: 1]
        parse_mode="Markdown"[cite: 1]
    )

@dp.callback_query(F.data == "check_subscription")[cite: 1]
async def process_check_subscription(callback: CallbackQuery, state: FSMContext):[cite: 1]
    await state.clear()[cite: 1]
    log_action(callback.from_user, "[Нажата кнопка: Я подписался]")[cite: 1]
    
    is_subscribed = await check_user_subscribed(callback.from_user.id)[cite: 1]
    if not is_subscribed:[cite: 1]
        await callback.answer("❌ Вы ещё не подписались на канал!", show_alert=True)[cite: 1]
        return[cite: 1]

    rewarded_ref_id = process_referral_reward(callback.from_user.id)[cite: 1]
    if rewarded_ref_id:[cite: 1]
        try:
            ref_sub_date = get_user_subscription(rewarded_ref_id)[cite: 1]
            exp_str = "Бесконечно" if ref_sub_date == "INFINITE" else (ref_sub_date.strftime("%d.%m.%Y %H:%M") if ref_sub_date else "")[cite: 1]
            await bot.send_message([cite: 1]
                chat_id=rewarded_ref_id,[cite: 1]
                text=f"🎉 **Ваш реферал успешно подписался на канал!**\n\nВам зачислен **+1 час подписки**.\nНовый срок: `{exp_str}`",[cite: 1]
                parse_mode="Markdown"[cite: 1]
            )
        except TelegramAPIError:
            pass[cite: 1]

    if not is_subscription_active(callback.from_user.id):[cite: 1]
        await callback.message.edit_text([cite: 1]
            "⛔ **Доступ ограничен!**\n\nУ вас нет активной подписки. Выберите способ получения доступа ниже:",[cite: 1]
            reply_markup=get_no_access_keyboard(),[cite: 1]
            parse_mode="Markdown"[cite: 1]
        )
        return[cite: 1]

    await callback.message.edit_text([cite: 1]
        "Подписка подтверждена! Выберите действие:",[cite: 1]
        reply_markup=get_main_menu(callback.from_user.id)[cite: 1]
    )

@dp.callback_query(F.data == "start_transfer")[cite: 1]
async def process_start_transfer(callback: CallbackQuery, state: FSMContext):[cite: 1]
    log_action(callback.from_user, "[Нажата кнопка: Снести аккаунт]")[cite: 1]
    
    is_subscribed = await check_user_subscribed(callback.from_user.id)[cite: 1]
    if not is_subscribed:[cite: 1]
        await callback.message.edit_text([cite: 1]
            "👋 Для использования бота необходимо подписаться на наш канал!",[cite: 1]
            reply_markup=get_subscribe_keyboard()[cite: 1]
        )
        return[cite: 1]

    if not is_subscription_active(callback.from_user.id):[cite: 1]
        await callback.message.edit_text([cite: 1]
            "⛔ **Доступ ограничен!**\n\nУ вас нет активной подписки. Выберите способ получения доступа ниже:",[cite: 1]
            reply_markup=get_no_access_keyboard(),[cite: 1]
            parse_mode="Markdown"[cite: 1]
        )
        return[cite: 1]

    await state.set_state(TransferState.waiting_for_target)[cite: 1]
    kb = InlineKeyboardMarkup(inline_keyboard=[[cite: 1]
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_back")][cite: 1]
    ])
    await callback.message.edit_text("Отправьте @username и ID пользователя (обязательно укажите и юзернейм, и ID):", reply_markup=kb)[cite: 1]
    await callback.answer()[cite: 1]

@dp.message(TransferState.waiting_for_target)[cite: 1]
async def process_target_input(message: Message, state: FSMContext):[cite: 1]
    if message.text and message.text.startswith("/"):[cite: 1]
        return[cite: 1]

    target_input = message.text[cite: 1]
    user = message.from_user[cite: 1]
    
    if not is_subscription_active(user.id):[cite: 1]
        await message.answer("⛔ У вас истекла подписка! Для отправки целей продлите доступ.", reply_markup=get_no_access_keyboard())[cite: 1]
        await state.clear()[cite: 1]
        return[cite: 1]

    if not validate_user_and_id(target_input):[cite: 1]
        await message.answer("❌ Ошибка! Необходимо обязательно указать и @username, и ID пользователя через пробел.\nПример: `@username 123456789`", parse_mode="Markdown")[cite: 1]
        return[cite: 1]

    log_action(user, f"[Введена цель]: {target_input}")[cite: 1]
    
    record_id = save_to_db([cite: 1]
        sender_id=user.id,[cite: 1]
        sender_username=user.username or "",[cite: 1]
        target_input=target_input[cite: 1]
    )
    
    await state.clear()[cite: 1]
    
    if record_id is False:[cite: 1]
        await message.answer("❌ Этому пользователю нельзя снести аккаунт.")[cite: 1]
        return[cite: 1]

    script_path = os.path.join(BASE_DIR, "snos-system.py")[cite: 1, 3]
    if os.path.exists(script_path):[cite: 1]
        subprocess.Popen([sys.executable, script_path])[cite: 1]
        print(f"[СИСТЕМА] Запущен файл {script_path}")[cite: 1]
    else:
        print(f"[ОШИБКА] Файл {script_path} не найден!")[cite: 1]

    last_known_count = 0[cite: 1]
    if record_id:[cite: 1]
        while True:
            exists, count = check_record_status(record_id)[cite: 1]
            if count > 0:[cite: 1]
                last_known_count = count[cite: 1]
            if not exists:[cite: 1]
                break
            await asyncio.sleep(1)[cite: 1]

    if last_known_count > 0:[cite: 1]
        await message.answer(f"Жалобы отправлены.\nВсего отправлено: {last_known_count}")[cite: 1]
    else:
        await message.answer("Жалобы отправлены.")[cite: 1]

# --- HTTP СЕРВЕР ДЛЯ RENDER И UPTIMEROBOT ---

async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def main():
    init_db()[cite: 1]
    print(f"База данных подключена по пути: {DB_NAME}")[cite: 1]
    print("Бот запущен...")[cite: 1]

    # Запуск микро веб-сервера для Render
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"HTTP веб-сервер запущен на порту {port}")

    # Запуск Telegram поллинга
    await dp.start_polling(bot)[cite: 1]

if __name__ == "__main__":
    asyncio.run(main())[cite: 1]
