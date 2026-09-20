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
BOT_TOKEN = "8819755559:AAEIirNZ4qessdkp3XGlrWx1WAY-r7CtmDg"

# ID Администратора
ADMIN_ID = 8037758285

# Юзернейм админа для связи
ADMIN_USERNAME = "@buhovi"

# Глобальный статус бота (True = включен, False = выключен)
BOT_ENABLED = True

# ID канала для проверки подписки
CHANNEL_ID = -1004414833916
CHANNEL_LINK = "https://t.me/basuyi"

# Запрещенный список для записи в базу данных
BLOCKED_INPUTS = {
    "@buhovi", "buhovi",
    "8037758285",
    "8215610247",
    "@buwixo", "buwixo",
    "6187980888",
    "6489694723",
    "8792534896"
}

# --- РАБОТА С БАЗОЙ ДАННЫХ ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "bot_data.db")

def escape_markdown(text: str) -> str:
    """Вспомогательная функция для экранирования спецсимволов Markdown"""
    if not text:
        return ""
    return text.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            sender_username TEXT,
            target_input TEXT,
            timestamp TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_users_stats (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            transfers_count INTEGER DEFAULT 0,
            joined_at TEXT,
            subscription_until TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id INTEGER,
            referred_id INTEGER PRIMARY KEY,
            rewarded INTEGER DEFAULT 0,
            created_at TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_text TEXT,
            created_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

def register_or_update_user(user_id: int, username: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute('SELECT user_id FROM bot_users_stats WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    
    if not row:
        cursor.execute('''
            INSERT INTO bot_users_stats (user_id, username, transfers_count, joined_at, subscription_until)
            VALUES (?, ?, 0, ?, NULL)
        ''', (user_id, username or "", now))
    else:
        cursor.execute('''
            UPDATE bot_users_stats SET username = ? WHERE user_id = ?
        ''', (username or "", user_id))
        
    conn.commit()
    conn.close()

def add_referral_link(referrer_id: int, referred_id: int):
    if referrer_id == referred_id:
        return
        
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute('SELECT referred_id FROM referrals WHERE referred_id = ?', (referred_id,))
    if not cursor.fetchone():
        cursor.execute('''
            INSERT INTO referrals (referrer_id, referred_id, rewarded, created_at)
            VALUES (?, ?, 0, ?)
        ''', (referrer_id, referred_id, now))
        conn.commit()
    conn.close()

def process_referral_reward(referred_id: int) -> int | None:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT referrer_id, rewarded FROM referrals WHERE referred_id = ?', (referred_id,))
    row = cursor.fetchone()
    
    if row and row[1] == 0:
        referrer_id = row[0]
        cursor.execute('UPDATE referrals SET rewarded = 1 WHERE referred_id = ?', (referred_id,))
        conn.commit()
        conn.close()
        
        add_user_subscription(referrer_id, timedelta(hours=1))
        return referrer_id
        
    conn.close()
    return None

def increment_user_transfers(user_id: int, username: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        INSERT INTO bot_users_stats (user_id, username, transfers_count, joined_at)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(user_id) DO UPDATE SET 
            username = excluded.username,
            transfers_count = transfers_count + 1
    ''', (user_id, username or "", now))
    conn.commit()
    conn.close()

def add_user_subscription(user_id: int, duration: timedelta) -> datetime:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    current_sub = get_user_subscription(user_id)
    now = datetime.now()
    
    if current_sub and current_sub != "INFINITE" and isinstance(current_sub, datetime) and current_sub > now:
        new_expires = current_sub + duration
    else:
        new_expires = now + duration
        
    exp_str = new_expires.strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('UPDATE bot_users_stats SET subscription_until = ? WHERE user_id = ?', (exp_str, user_id))
    conn.commit()
    conn.close()
    return new_expires

def set_user_subscription_infinite(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE bot_users_stats SET subscription_until = "INFINITE" WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def get_user_subscription(user_id: int) -> datetime | str | None:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT subscription_until FROM bot_users_stats WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row and row[0]:
        if row[0] == "INFINITE":
            return "INFINITE"
        try:
            return datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    return None

def is_subscription_active(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    sub = get_user_subscription(user_id)
    if sub == "INFINITE":
        return True
    if isinstance(sub, datetime) and sub > datetime.now():
        return True
    return False

def save_to_db(sender_id: int, sender_username: str, target_input: str) -> int | bool | None:
    clean_input = target_input.strip().lower()
    for item in BLOCKED_INPUTS:
        if item in clean_input:
            print(f"[БЛОКИРОВКА БД] Запись '{target_input}' отклонена.")
            return False

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        INSERT INTO transfers (sender_id, sender_username, target_input, timestamp)
        VALUES (?, ?, ?, ?)
    ''', (sender_id, sender_username, target_input, now))
    record_id = cursor.lastrowid
    conn.commit()
    conn.close()

    increment_user_transfers(sender_id, sender_username)
    return record_id

def check_record_status(record_id: int) -> tuple[bool, int]:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM transfers WHERE id = ?', (record_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None, 0

def get_all_users_ids() -> list[int]:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM bot_users_stats')
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows if row[0]]

def get_users_list_from_db() -> list[tuple[int, str, int, str]]:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, transfers_count, subscription_until
        FROM bot_users_stats
        ORDER BY transfers_count DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    return rows

def save_pending_broadcast(text: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('INSERT INTO pending_broadcasts (message_text, created_at) VALUES (?, ?)', (text, now))
    conn.commit()
    conn.close()

def get_and_clear_pending_broadcasts() -> list[str]:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT message_text FROM pending_broadcasts ORDER BY id ASC')
    rows = cursor.fetchall()
    cursor.execute('DELETE FROM pending_broadcasts')
    conn.commit()
    conn.close()
    return [row[0] for row in rows]

def parse_time_duration(time_str: str) -> timedelta | None:
    time_str = time_str.lower().strip()
    pattern = r'(?:(\d+)\s*д)?\s*(?:(\d+)\s*ч)?\s*(?:(\d+)\s*м)?'
    match = re.fullmatch(pattern, time_str)
    
    if not match or not any(match.groups()):
        return None
        
    days = int(match.group(1) or 0)
    hours = int(match.group(2) or 0)
    minutes = int(match.group(3) or 0)
    
    if days == 0 and hours == 0 and minutes == 0:
        return None
        
    return timedelta(days=days, hours=hours, minutes=minutes)

# -----------------------------

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class TransferState(StatesGroup):
    waiting_for_target = State()

class AdminState(StatesGroup):
    waiting_for_broadcast_text = State()
    waiting_for_grant_sub = State()

@dp.message.outer_middleware()
@dp.callback_query.outer_middleware()
async def bot_status_middleware(handler, event, data):
    user = getattr(event, "from_user", None)
    if user:
        register_or_update_user(user.id, user.username)

    if user and not BOT_ENABLED and user.id != ADMIN_ID:
        if isinstance(event, CallbackQuery):
            await event.answer("⚠️ Бот временно отключен на техническое обслуживание.", show_alert=True)
        return
    return await handler(event, data)

def log_action(user, text: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    username_part = f" @{user.username}" if user.username else ""
    print(f"[{now}]{username_part} id:{user.id} text:{text}")

async def execute_broadcast(broadcast_msg: str) -> tuple[int, int]:
    users = get_all_users_ids()
    success_count = 0
    fail_count = 0
    for user_id in users:
        try:
            await bot.send_message(chat_id=user_id, text=f"📢 **ОБЪЯВЛЕНИЕ:**\n\n{broadcast_msg}", parse_mode="Markdown")
            success_count += 1
            await asyncio.sleep(0.05)
        except TelegramAPIError:
            fail_count += 1
    return success_count, fail_count

def get_subscribe_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться на канал", url=CHANNEL_LINK)],
            [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")]
        ]
    )

def get_no_access_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Получить бесплатно", callback_data="sub_free_menu")],
            [InlineKeyboardButton(text="⭐ Купить подписку", callback_data="sub_buy")]
        ]
    )

def get_free_menu_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📧 Google аккаунт (12 часов)", callback_data="free_google")],
            [InlineKeyboardButton(text="👥 Пригласить реферала (+1 час)", callback_data="free_referral")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="sub_back")]
        ]
    )

def get_main_menu(user_id: int):
    keyboard = [
        [InlineKeyboardButton(text="💥 Снести аккаунт", callback_data="start_transfer")]
    ]
    if user_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton(text="⚙️ Админ панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_admin_keyboard():
    toggle_button = (
        InlineKeyboardButton(text="⛔ Выключить бота", callback_data="admin_toggle_bot")
        if BOT_ENABLED else
        InlineKeyboardButton(text="✅ Включить бота", callback_data="admin_toggle_bot")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔑 Выдать подписку", callback_data="admin_grant_sub")],
            [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_users_list")],
            [InlineKeyboardButton(text="📢 Объявление", callback_data="admin_broadcast")],
            [toggle_button],
            [InlineKeyboardButton(text="🔄 Перезагрузить бота", callback_data="admin_restart")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
        ]
    )

def get_admin_text():
    status = "🟢 Включен" if BOT_ENABLED else "🔴 Выключен (доступен только вам)"
    return f"👑 **Административная панель**\n\nСтатус бота: `{status}`"

async def check_user_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except TelegramBadRequest:
        return False

def validate_user_and_id(text: str) -> bool:
    has_username = bool(re.search(r'@[a-zA-Z0-9_]{4,}', text))
    has_id = bool(re.search(r'\b\d{6,12}\b', text))
    return has_username and has_id

# --- АДМИН ПАНЕЛЬ ---

@dp.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(get_admin_text(), reply_markup=get_admin_keyboard(), parse_mode="Markdown")

@dp.callback_query(F.data == "admin_panel")
async def process_admin_panel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен!", show_alert=True)
        return
    await callback.message.edit_text(get_admin_text(), reply_markup=get_admin_keyboard(), parse_mode="Markdown")

@dp.callback_query(F.data == "admin_back")
async def process_admin_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "Вы вернулись в главное меню:",
        reply_markup=get_main_menu(callback.from_user.id)
    )

@dp.callback_query(F.data == "admin_grant_sub")
async def process_admin_grant_sub(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminState.waiting_for_grant_sub)
    
    text = (
        "🔑 **Выдача подписки**\n\n"
        "Отправьте ID пользователя и время подписки через пробел.\n\n"
        "**Примеры:**\n"
        "`11111111111 1д` — выдаст подписку на 1 день\n"
        "`11111111111 12ч` — выдаст подписку на 12 часов\n"
        "`11111111111 бесконечно` — выдаст **бесконечную** подписку"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_panel")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@dp.message(AdminState.waiting_for_grant_sub)
async def process_grant_sub_input(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    if message.text and message.text.startswith("/"):
        return

    parts = message.text.strip().split()
    if len(parts) != 2 or not parts[0].isdigit():
        await message.answer("❌ **Ошибка формата!** Отправьте ID и время/режим через пробел.\nПример: `11111111111 бесконечно` или `11111111111 1д`", parse_mode="Markdown")
        return

    target_id = int(parts[0])
    time_str = parts[1].lower()

    if time_str in ["бесконечно", "навсегда", "inf", "infinite"]:
        set_user_subscription_infinite(target_id)
        await state.clear()
        
        await message.answer(
            f"✅ **Выдана бесконечная подписка!**\n\n"
            f"👤 ID: `{target_id}`\n"
            f"⏳ Срок: `Бесконечно`",
            reply_markup=get_admin_keyboard(),
            parse_mode="Markdown"
        )
        try:
            await bot.send_message(
                chat_id=target_id,
                text="🎉 **Вам выдана БЕСКОНЕЧНАЯ подписка!**\n\nТеперь вам навсегда доступны все функции бота.",
                reply_markup=get_main_menu(target_id),
                parse_mode="Markdown"
            )
        except TelegramAPIError:
            await message.answer("⚠️ Подписка сохранена, но не удалось отправить сообщение пользователю.")
        return

    duration = parse_time_duration(time_str)
    if not duration:
        await message.answer("❌ **Неверный формат времени!** Используйте комбинации `д`, `ч`, `м` (например: `1д`, `12ч`) или напишите `бесконечно`.", parse_mode="Markdown")
        return

    new_expires = add_user_subscription(target_id, duration)
    await state.clear()

    formatted_exp = new_expires.strftime("%d.%m.%Y %H:%M")
    await message.answer(
        f"✅ **Подписка успешно выдана!**\n\n"
        f"👤 ID: `{target_id}`\n"
        f"⏳ Действует до: `{formatted_exp}`",
        reply_markup=get_admin_keyboard(),
        parse_mode="Markdown"
    )

    try:
        await bot.send_message(
            chat_id=target_id,
            text=f"🎉 **Вам выдана подписка!**\n\nДействительна до: `{formatted_exp}`\nТеперь вам доступны все функции бота.",
            reply_markup=get_main_menu(target_id),
            parse_mode="Markdown"
        )
    except TelegramAPIError:
        await message.answer("⚠️ Подписка сохранена, но не удалось отправить сообщение пользователю.")

@dp.callback_query(F.data == "admin_users_list")
async def process_admin_users_list(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    users = get_users_list_from_db()
    if not users:
        await callback.message.edit_text("👥 В базе данных пока нет сохранённых пользователей.", reply_markup=get_admin_keyboard())
        await callback.answer()
        return

    text_lines = ["📋 **Список всех пользователей бота:**\n"]
    now = datetime.now()
    for user_id, username, count, sub_until in users:
        user_mention = f"@{escape_markdown(username)}" if username else "[без юзернейма]"
        sub_status = "❌ Нет"
        if user_id == ADMIN_ID:
            sub_status = "👑 Навсегда (Админ)"
        elif sub_until == "INFINITE":
            sub_status = "♾️ Бесконечно"
        elif sub_until:
            try:
                sub_date = datetime.strptime(sub_until, "%Y-%m-%d %H:%M:%S")
                if sub_date > now:
                    sub_status = f"✅ До {sub_date.strftime('%d.%m %H:%M')}"
                else:
                    sub_status = "❌ Истекла"
            except ValueError:
                pass

        text_lines.append(f"{user_mention} id : `{user_id}` ({count}) | Подписка: {sub_status}")

    full_text = "\n".join(text_lines)
    
    try:
        if len(full_text) > 3500:
            chunk = text_lines[0] + "\n"
            for line in text_lines[1:]:
                if len(chunk) + len(line) + 1 > 3500:
                    await callback.message.answer(chunk, parse_mode="Markdown")
                    chunk = ""
                chunk += line + "\n"
            if chunk:
                await callback.message.answer(chunk, reply_markup=get_admin_keyboard(), parse_mode="Markdown")
        else:
            await callback.message.edit_text(full_text, reply_markup=get_admin_keyboard(), parse_mode="Markdown")
    except TelegramBadRequest as e:
        await callback.message.answer(f"❌ Ошибка разметки сообщения: {e.message}")
        
    await callback.answer()

@dp.callback_query(F.data == "admin_toggle_bot")
async def process_admin_toggle_bot(callback: CallbackQuery):
    global BOT_ENABLED
    if callback.from_user.id != ADMIN_ID:
        return
    
    BOT_ENABLED = not BOT_ENABLED
    status_msg = "включен" if BOT_ENABLED else "выключен для пользователей"
    log_action(callback.from_user, f"[АДМИН] Бот был {status_msg}")
    
    await callback.answer(f"Бот {status_msg}!", show_alert=True)
    await callback.message.edit_text(get_admin_text(), reply_markup=get_admin_keyboard(), parse_mode="Markdown")

    if BOT_ENABLED:
        pending_broadcasts = get_and_clear_pending_broadcasts()
        if pending_broadcasts:
            await callback.message.answer(f"🔄 **Бот включен.** Начинаю отправку отложенных объявлений ({len(pending_broadcasts)} шт.)...", parse_mode="Markdown")
            for msg in pending_broadcasts:
                succ, fail = await execute_broadcast(msg)
                await callback.message.answer(
                    f"✅ **Отложенное объявление отправлено!**\n\n"
                    f"Доставлено: `{succ}`\n"
                    f"Не доставлено: `{fail}`",
                    parse_mode="Markdown"
                )

@dp.callback_query(F.data == "admin_broadcast")
async def process_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminState.waiting_for_broadcast_text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_panel")]
    ])
    await callback.message.edit_text("📝 Отправьте текст объявления, которое получат все пользователи бота:", reply_markup=kb)
    await callback.answer()

@dp.message(AdminState.waiting_for_broadcast_text)
async def process_broadcast_text(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    if message.text and message.text.startswith("/"):
        return

    broadcast_msg = message.text

    if not BOT_ENABLED:
        save_pending_broadcast(broadcast_msg)
        await message.answer(
            "⏳ **Бот сейчас выключен.**\n\nОбъявление сохранено в очередь и будет **автоматически отправлено** сразу после того, как вы включите бота!",
            reply_markup=get_admin_keyboard(),
            parse_mode="Markdown"
        )
        await state.clear()
        return

    users = get_all_users_ids()
    if not users:
        await message.answer("❌ В базе данных пока нет пользователей для рассылки.", reply_markup=get_admin_keyboard())
        await state.clear()
        return

    await message.answer(f"⏳ Начинаю рассылку для {len(users)} пользователей...")
    success_count, fail_count = await execute_broadcast(broadcast_msg)

    await message.answer(
        f"✅ **Рассылка завершена!**\n\n"
        f"Успешно доставлено: `{success_count}`\n"
        f"Не доставлено (заблокировали бота): `{fail_count}`",
        reply_markup=get_admin_keyboard(),
        parse_mode="Markdown"
    )
    await state.clear()

@dp.callback_query(F.data == "admin_restart")
async def process_admin_restart(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text("🔄 **Перезагрузка бота...**", parse_mode="Markdown")
    log_action(callback.from_user, "[АДМИН] Запросил перезагрузку бота")
    
    os.execl(sys.executable, sys.executable, *sys.argv)

# --- РАЗВИЛКА БЕСПЛАТНОЙ ПОДПИСКИ ---

@dp.callback_query(F.data == "sub_free_menu")
async def process_sub_free_menu(callback: CallbackQuery):
    text = (
        "🎁 **Получение бесплатного доступа**\n\n"
        "Выберите удобный вариант получения подписки:"
    )
    await callback.message.edit_text(text, reply_markup=get_free_menu_keyboard(), parse_mode="Markdown")

@dp.callback_query(F.data == "free_google")
async def process_free_google(callback: CallbackQuery):
    text = (
        "📧 **Бесплатная подписка на 12 часов (полдня) за Google аккаунт**\n\n"
        "Чтобы получить подписку на 12 часов бесплатно, вам нужно создать **новый Google аккаунт** и прислать логин (почту) и пароль администратору.\n\n"
        f"📩 Отправьте данные администратору: {ADMIN_USERNAME}\n\n"
        "После проверки данных вам будет зачислена подписка!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать админу", url="https://t.me/buhovi")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="sub_free_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "free_referral")
async def process_free_referral(callback: CallbackQuery):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{callback.from_user.id}"
    
    text = (
        "👥 **Реферальная система (+1 час за каждого реферала)**\n\n"
        "За **каждого** приглашенного пользователя вы получаете **+1 час подписки**.\n\n"
        "⚠️ **Условие:** Ваш реферал должен перейти по ссылке и **обязательно подписаться на канал**.\n\n"
        f"🔗 **Ваша персональная реферальная ссылка:**\n`{ref_link}`"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="sub_free_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "sub_buy")
async def process_sub_buy(callback: CallbackQuery):
    text = (
        "⭐ **Расценки на подписку (в Telegram Stars):**\n\n"
        "• **1 день** — 25 звезд ⭐\n"
        "• **3 дня** — 40 звезд ⭐\n"
        "• **7 дней** — 65 звезд ⭐\n\n"
        f"Для покупки выберите нужный тариф, отправьте звезды администратору {ADMIN_USERNAME} и напишите ему свой ID.\n\n"
        f"Ваш ID: `{callback.from_user.id}`"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Оплатить и написать админу", url="https://t.me/buhovi")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="sub_back")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "sub_back")
async def process_sub_back(callback: CallbackQuery):
    await callback.message.edit_text(
        "⛔ **Доступ ограничен!**\n\nУ вас нет активной подписки. Выберите способ получения доступа ниже:",
        reply_markup=get_no_access_keyboard(),
        parse_mode="Markdown"
    )

# --- ОСНОВНАЯ ЛОГИКА ---

@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    log_action(message.from_user, message.text or "[без текста]")
    
    register_or_update_user(message.from_user.id, message.from_user.username)
    
    if command.args and command.args.startswith("ref_"):
        ref_str = command.args.replace("ref_", "")
        if ref_str.isdigit():
            referrer_id = int(ref_str)
            add_referral_link(referrer_id, message.from_user.id)

    is_subscribed = await check_user_subscribed(message.from_user.id)
    if not is_subscribed:
        await message.answer(
            "👋 Для использования бота необходимо подписаться на наш канал!",
            reply_markup=get_subscribe_keyboard()
        )
        return

    rewarded_ref_id = process_referral_reward(message.from_user.id)
    if rewarded_ref_id:
        try:
            ref_sub_date = get_user_subscription(rewarded_ref_id)
            exp_str = "Бесконечно" if ref_sub_date == "INFINITE" else (ref_sub_date.strftime("%d.%m.%Y %H:%M") if ref_sub_date else "")
            await bot.send_message(
                chat_id=rewarded_ref_id,
                text=f"🎉 **Ваш реферал зарегистрировался и подписался на канал!**\n\nВам начислено **+1 час подписки**.\nНовый срок: `{exp_str}`",
                parse_mode="Markdown"
            )
        except TelegramAPIError:
            pass

    if not is_subscription_active(message.from_user.id):
        await message.answer(
            "⛔ **Доступ ограничен!**\n\nУ вас нет активной подписки. Выберите способ получения доступа ниже:",
            reply_markup=get_no_access_keyboard(),
            parse_mode="Markdown"
        )
        return

    exp_date = get_user_subscription(message.from_user.id)
    if message.from_user.id == ADMIN_ID:
        sub_text = "👑 Бесконечная (Администратор)"
    elif exp_date == "INFINITE":
        sub_text = "♾️ Бесконечная"
    else:
        sub_text = f"до {exp_date.strftime('%d.%m.%Y %H:%M')}"

    await message.answer(
        f"Добро пожаловать!\nВаша подписка активна: `{sub_text}`\n\nВыберите действие из меню ниже:",
        reply_markup=get_main_menu(message.from_user.id),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "check_subscription")
async def process_check_subscription(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    log_action(callback.from_user, "[Нажата кнопка: Я подписался]")
    
    is_subscribed = await check_user_subscribed(callback.from_user.id)
    if not is_subscribed:
        await callback.answer("❌ Вы ещё не подписались на канал!", show_alert=True)
        return

    rewarded_ref_id = process_referral_reward(callback.from_user.id)
    if rewarded_ref_id:
        try:
            ref_sub_date = get_user_subscription(rewarded_ref_id)
            exp_str = "Бесконечно" if ref_sub_date == "INFINITE" else (ref_sub_date.strftime("%d.%m.%Y %H:%M") if ref_sub_date else "")
            await bot.send_message(
                chat_id=rewarded_ref_id,
                text=f"🎉 **Ваш реферал успешно подписался на канал!**\n\nВам зачислен **+1 час подписки**.\nНовый срок: `{exp_str}`",
                parse_mode="Markdown"
            )
        except TelegramAPIError:
            pass

    if not is_subscription_active(callback.from_user.id):
        await callback.message.edit_text(
            "⛔ **Доступ ограничен!**\n\nУ вас нет активной подписки. Выберите способ получения доступа ниже:",
            reply_markup=get_no_access_keyboard(),
            parse_mode="Markdown"
        )
        return

    await callback.message.edit_text(
        "Подписка подтверждена! Выберите действие:",
        reply_markup=get_main_menu(callback.from_user.id)
    )

@dp.callback_query(F.data == "start_transfer")
async def process_start_transfer(callback: CallbackQuery, state: FSMContext):
    log_action(callback.from_user, "[Нажата кнопка: Снести аккаунт]")
    
    is_subscribed = await check_user_subscribed(callback.from_user.id)
    if not is_subscribed:
        await callback.message.edit_text(
            "👋 Для использования бота необходимо подписаться на наш канал!",
            reply_markup=get_subscribe_keyboard()
        )
        return

    if not is_subscription_active(callback.from_user.id):
        await callback.message.edit_text(
            "⛔ **Доступ ограничен!**\n\nУ вас нет активной подписки. Выберите способ получения доступа ниже:",
            reply_markup=get_no_access_keyboard(),
            parse_mode="Markdown"
        )
        return

    await state.set_state(TransferState.waiting_for_target)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_back")]
    ])
    await callback.message.edit_text("Отправьте @username и ID пользователя (обязательно укажите и юзернейм, и ID):", reply_markup=kb)
    await callback.answer()

@dp.message(TransferState.waiting_for_target)
async def process_target_input(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        return

    target_input = message.text
    user = message.from_user
    
    if not is_subscription_active(user.id):
        await message.answer("⛔ У вас истекла подписка! Для отправки целей продлите доступ.", reply_markup=get_no_access_keyboard())
        await state.clear()
        return

    if not validate_user_and_id(target_input):
        await message.answer("❌ Ошибка! Необходимо обязательно указать и @username, и ID пользователя через пробел.\nПример: `@username 123456789`", parse_mode="Markdown")
        return

    log_action(user, f"[Введена цель]: {target_input}")
    
    record_id = save_to_db(
        sender_id=user.id,
        sender_username=user.username or "",
        target_input=target_input
    )
    
    await state.clear()
    
    if record_id is False:
        await message.answer("❌ Этому пользователю нельзя снести аккаунт.")
        return

    script_path = os.path.join(BASE_DIR, "snos-system.py")
    if os.path.exists(script_path):
        subprocess.Popen([sys.executable, script_path])
        print(f"[СИСТЕМА] Запущен файл {script_path}")
    else:
        print(f"[ОШИБКА] Файл {script_path} не найден!")

    last_known_count = 0
    if record_id:
        while True:
            exists, count = check_record_status(record_id)
            if count > 0:
                last_known_count = count
            if not exists:
                break
            await asyncio.sleep(1)

    if last_known_count > 0:
        await message.answer(f"Жалобы отправлены.\nВсего отправлено: {last_known_count}")
    else:
        await message.answer("Жалобы отправлены.")

# --- HTTP СЕРВЕР ДЛЯ RENDER И UPTIMEROBOT ---

async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def main():
    init_db()
    print(f"База данных подключена по пути: {DB_NAME}")
    print("Бот запущен...")

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
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
