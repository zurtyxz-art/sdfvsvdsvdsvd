import asyncio
import os
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import LabeledPrice, Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import sqlite3
from typing import List, Dict, Optional

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# ===== НАСТРОЙКИ БОТА =====
API_TOKEN = "8632490162:AAHilCg8_hJ2BHzPK__eWMIEIatuIT12PfM"
PROVIDER_TOKEN = ""

# ID группы, где находится бот
GROUP_ID = -1004280733439  # Замените на ID вашей группы

# Список ID администраторов
ADMIN_IDS = [5254779646]  # Замените на реальные ID админов

# Техподдержка
SUPPORT_USERNAME = "@tech_support_username"
SUPPORT_LINK = "https://t.me/tech_support_username"

# ID технического администратора
TECH_ADMIN_ID = 5254779646  # ID тех. админа

# База данных
DB_NAME = "bot_database.db"

# Инициализация бота
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


# States для FSM
class BroadcastStates(StatesGroup):
    waiting_for_message = State()
    waiting_for_buttons = State()


class PriceStates(StatesGroup):
    waiting_for_price = State()
    waiting_for_bot_price = State()
    waiting_for_hosting_price = State()


class BuyBotStates(StatesGroup):
    waiting_for_group_id = State()
    waiting_for_token = State()
    waiting_for_username = State()
    waiting_for_bot_username = State()


class TechNotifyState(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_message = State()


# ===== БАЗА ДАННЫХ =====
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_buyer BOOLEAN DEFAULT FALSE
        )
    ''')

    # Таблица платежей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            payment_type TEXT,
            payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_successful BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')

    # Таблица пригласительных ссылок
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invite_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link TEXT UNIQUE,
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            is_used BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')

    # Таблица купленных ботов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS purchased_bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            bot_token TEXT,
            bot_username TEXT,
            group_id INTEGER,
            purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            hosting_expires_at TIMESTAMP,
            is_active BOOLEAN DEFAULT FALSE,
            hosting_active BOOLEAN DEFAULT FALSE,
            verified_account BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')

    # Таблица хостинг платежей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS hosting_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id INTEGER,
            user_id INTEGER,
            amount INTEGER,
            months INTEGER DEFAULT 1,
            payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (bot_id) REFERENCES purchased_bots (id),
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')

    # Таблица настроек
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # Установка начальных цен
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value) VALUES ('price', '100')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value) VALUES ('bot_price', '500')
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value) VALUES ('hosting_price', '300')
    ''')

    conn.commit()
    conn.close()


def add_user(user_id: int, username: str = None, full_name: str = None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO users (user_id, username, full_name) 
        VALUES (?, ?, ?)
    ''', (user_id, username, full_name))
    conn.commit()
    conn.close()


def mark_as_buyer(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_buyer = TRUE WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()


def get_users_stats():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM users WHERE is_buyer = TRUE')
    total_buyers = cursor.fetchone()[0]
    cursor.execute('SELECT COALESCE(SUM(amount), 0) FROM payments WHERE is_successful = TRUE')
    total_income = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM purchased_bots')
    total_bots = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM purchased_bots WHERE hosting_active = TRUE')
    active_hostings = cursor.fetchone()[0]
    conn.close()
    return total_users, total_buyers, total_income, total_bots, active_hostings


def get_all_users():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username, full_name, is_buyer FROM users')
    users = cursor.fetchall()
    conn.close()
    return users


def get_current_price():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = "price"')
    result = cursor.fetchone()
    conn.close()
    return int(result[0]) if result else 100


def get_bot_price():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = "bot_price"')
    result = cursor.fetchone()
    conn.close()
    return int(result[0]) if result else 500


def get_hosting_price():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = "hosting_price"')
    result = cursor.fetchone()
    conn.close()
    return int(result[0]) if result else 300


def update_price(new_price: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE settings SET value = ? WHERE key = "price"', (str(new_price),))
    conn.commit()
    conn.close()


def update_bot_price(new_price: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE settings SET value = ? WHERE key = "bot_price"', (str(new_price),))
    conn.commit()
    conn.close()


def update_hosting_price(new_price: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE settings SET value = ? WHERE key = "hosting_price"', (str(new_price),))
    conn.commit()
    conn.close()


def save_invite_link(link: str, user_id: int):
    expires_at = datetime.now() + timedelta(hours=24)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO invite_links (link, user_id, expires_at) 
        VALUES (?, ?, ?)
    ''', (link, user_id, expires_at))
    conn.commit()
    conn.close()


def save_payment(user_id: int, amount: int, payment_type: str = "access"):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO payments (user_id, amount, payment_type, is_successful) 
        VALUES (?, ?, ?, TRUE)
    ''', (user_id, amount, payment_type))
    conn.commit()
    conn.close()


def save_purchased_bot(user_id: int, bot_token: str, bot_username: str, group_id: int, verified: bool = False):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO purchased_bots (user_id, bot_token, bot_username, group_id, verified_account) 
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, bot_token, bot_username, group_id, verified))
    conn.commit()
    conn.close()


def get_user_bots(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, bot_username, group_id, purchase_date, hosting_expires_at, hosting_active, is_active, verified_account 
        FROM purchased_bots 
        WHERE user_id = ?
    ''', (user_id,))
    bots = cursor.fetchall()
    conn.close()
    return bots


def get_all_bots():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT p.id, p.user_id, p.bot_username, p.group_id, p.purchase_date, p.hosting_expires_at, 
               p.hosting_active, p.is_active, p.verified_account, u.username 
        FROM purchased_bots p 
        LEFT JOIN users u ON p.user_id = u.user_id
    ''')
    bots = cursor.fetchall()
    conn.close()
    return bots


def get_bot_by_id(bot_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, user_id, bot_username, group_id, purchase_date, hosting_expires_at, hosting_active, is_active 
        FROM purchased_bots 
        WHERE id = ?
    ''', (bot_id,))
    bot = cursor.fetchone()
    conn.close()
    return bot


def activate_hosting(bot_id: int, months: int = 1):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT hosting_expires_at FROM purchased_bots WHERE id = ?', (bot_id,))
    result = cursor.fetchone()

    if result and result[0]:
        current_expires = datetime.fromisoformat(result[0])
        if current_expires > datetime.now():
            new_expires = current_expires + timedelta(days=30 * months)
        else:
            new_expires = datetime.now() + timedelta(days=30 * months)
    else:
        new_expires = datetime.now() + timedelta(days=30 * months)

    cursor.execute('''
        UPDATE purchased_bots 
        SET hosting_active = TRUE, hosting_expires_at = ?, is_active = TRUE 
        WHERE id = ?
    ''', (new_expires.isoformat(), bot_id))
    conn.commit()
    conn.close()
    return new_expires


def save_hosting_payment(bot_id: int, user_id: int, amount: int, months: int = 1):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO hosting_payments (bot_id, user_id, amount, months) 
        VALUES (?, ?, ?, ?)
    ''', (bot_id, user_id, amount, months))
    conn.commit()
    conn.close()


def get_expiring_hostings():
    """Получить ботов, у которых хостинг истекает через 3 дня или меньше"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Проверяем хостинги, которые истекают через 3, 2 и 1 день
    for days in [3, 2, 1]:
        target_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
        cursor.execute('''
            SELECT id, user_id, bot_username, hosting_expires_at 
            FROM purchased_bots 
            WHERE hosting_active = TRUE 
            AND date(hosting_expires_at) = ?
        ''', (target_date,))
        bots = cursor.fetchall()
        if bots:
            conn.close()
            return bots, days

    conn.close()
    return [], 0


# ===== КЛАВИАТУРЫ =====
def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    current_price = get_current_price()
    builder.button(text=f"💫 Купить доступ ({current_price} ⭐)", callback_data="buy_access")
    builder.button(text="ℹ️ О доступе", callback_data="about_access")
    builder.button(text="🛠 Управление ботами", callback_data="bot_management")
    builder.button(text=f"🆘 Техподдержка", url=SUPPORT_LINK)
    builder.adjust(1)
    return builder.as_markup()


def get_admin_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="👥 Пользователи", callback_data="admin_users")
    builder.button(text="💰 Изменить цену доступа", callback_data="admin_change_price")
    builder.button(text="📨 Рассылка", callback_data="admin_broadcast")
    builder.button(text="🤖 Все боты", callback_data="admin_all_bots")
    builder.adjust(2)
    return builder.as_markup()


def get_tech_admin_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="👥 Пользователи", callback_data="admin_users")
    builder.button(text="💰 Цена доступа", callback_data="admin_change_price")
    builder.button(text="💵 Цена бота", callback_data="admin_change_bot_price")
    builder.button(text="🖥 Цена хостинга", callback_data="admin_change_hosting_price")
    builder.button(text="📨 Рассылка", callback_data="admin_broadcast")
    builder.button(text="🤖 Все боты", callback_data="admin_all_bots")
    builder.button(text="📬 Уведомить о запуске", callback_data="tech_notify_launch")
    builder.adjust(2)
    return builder.as_markup()


def get_bot_management_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🤖 Купить бота", callback_data="buy_bot")
    builder.button(text="📋 Мои боты", callback_data="my_bots")
    builder.button(text="🔙 Назад", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()


# ===== ОСНОВНЫЕ КОМАНДЫ =====
@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name

    add_user(user_id, username, full_name)

    if user_id == TECH_ADMIN_ID:
        await message.answer(
            "👑 Технический администратор\n\nВыберите действие:",
            reply_markup=get_tech_admin_keyboard()
        )
    elif user_id in ADMIN_IDS:
        await message.answer(
            "👑 Админ-панель\n\nВыберите действие:",
            reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer(
            "👋 Добро пожаловать!\n\n"
            "Здесь вы можете получить доступ к приватному контенту по монтажу "
            "или приобрести собственного бота.\n"
            f"Текущая цена доступа: {get_current_price()} ⭐\n\n"
            "Используйте кнопки ниже:",
            reply_markup=get_main_keyboard()
        )


@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text(
        "👋 Главное меню\n\nВыберите действие:",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()


# ===== ПОКУПКА ДОСТУПА =====
@dp.callback_query(F.data == "buy_access")
async def buy_access(callback: CallbackQuery):
    current_price = get_current_price()
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Оплатить {current_price} ⭐", pay=True)
    builder.button(text="❌ Отмена", callback_data="cancel_payment")

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Доступ к приватному контенту",
        description=f"Одноразовый доступ к материалам по монтажу. Ссылка действует 24 часа.",
        payload=f"access_{callback.from_user.id}",
        provider_token=PROVIDER_TOKEN,
        currency="XTR",
        prices=[LabeledPrice(label="Доступ к контенту", amount=current_price)],
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@dp.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer("❌ Оплата отменена")


@dp.callback_query(F.data == "about_access")
async def about_access(callback: CallbackQuery):
    await callback.message.edit_text(
        "📚 Приватный контент по монтажу\n\n"
        "• Эксклюзивные туториалы\n"
        "• Исходники проектов\n"
        "• Премиум пресеты\n"
        "• Личная поддержка\n\n"
        f"Цена: {get_current_price()} ⭐\n"
        "После оплаты вы получите одноразовую ссылку на 24 часа.",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()


@dp.pre_checkout_query()
async def pre_checkout_query(pre_checkout: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout.id, ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: Message, state: FSMContext = None):
    user_id = message.from_user.id
    amount = message.successful_payment.total_amount
    payload = message.successful_payment.invoice_payload

    if payload.startswith("access_"):
        # Обработка покупки доступа
        save_payment(user_id, amount, "access")
        mark_as_buyer(user_id)

        try:
            invite_link = await bot.create_chat_invite_link(
                chat_id=GROUP_ID,
                member_limit=1,
                expire_date=datetime.now() + timedelta(hours=24)
            )

            save_invite_link(invite_link.invite_link, user_id)

            await message.answer(
                f"✨ Спасибо за оплату {amount} звёзд!\n\n"
                f"🔗 Ваша одноразовая ссылка для входа в группу:\n"
                f"{invite_link.invite_link}\n\n"
                f"⚠️ Ссылка действительна 24 часа и может быть использована только один раз."
            )

            for admin_id in ADMIN_IDS + [TECH_ADMIN_ID]:
                try:
                    await bot.send_message(
                        admin_id,
                        f"💰 Новая покупка доступа!\n"
                        f"Пользователь: @{message.from_user.username or user_id}\n"
                        f"Сумма: {amount} ⭐"
                    )
                except:
                    pass
        except Exception as e:
            logging.error(f"Error creating invite link: {e}")
            await message.answer("❌ Ошибка при создании ссылки. Обратитесь в техподдержку.")

    elif payload.startswith("bot_purchase_"):
        # Обработка покупки бота
        _, buyer_id, verified = payload.split("_")
        buyer_id = int(buyer_id)
        verified = verified == "True"

        save_payment(user_id, amount, "bot_purchase")

        # Сохраняем тип аккаунта в состояние
        await state.update_data(verified=verified)

        await message.answer(
            f"✅ Оплата бота на сумму {amount} ⭐ прошла успешно!\n\n"
            "Теперь пришлите ID вашей группы, чтобы бот мог создавать одноразовые ссылки.\n\n"
            "❗️ ВАЖНО: Группа должна быть приватной (частной)!\n"
            "🔍 Узнать ID группы можно здесь: @getidallbot\n\n"
            "Просто добавьте @getidallbot в вашу группу и он покажет ID.\n"
            "Отправьте ID группы в ответном сообщении (отрицательное число)."
        )

    elif payload.startswith("hosting_"):
        # Обработка покупки хостинга
        _, bot_id_str, months_str = payload.split("_")
        bot_id = int(bot_id_str)
        months = int(months_str)

        save_payment(user_id, amount, "hosting")
        save_hosting_payment(bot_id, user_id, amount, months)

        expires_at = activate_hosting(bot_id, months)

        await message.answer(
            f"✅ Оплата хостинга на сумму {amount} ⭐ прошла успешно!\n\n"
            f"⏰ Ваш бот будет запущен в течение 24 часов.\n"
            f"📅 Хостинг активен до: {expires_at.strftime('%d.%m.%Y')}\n\n"
            "Вам придет уведомление о запуске."
        )

        # Уведомляем тех. админа
        bot_info = get_bot_by_id(bot_id)
        if bot_info:
            try:
                await bot.send_message(
                    TECH_ADMIN_ID,
                    f"🖥 Новый хостинг!\n"
                    f"Бот ID: {bot_id}\n"
                    f"Юзернейм: {bot_info[2]}\n"
                    f"Группа ID: {bot_info[3]}\n"
                    f"Пользователь ID: {user_id}\n"
                    f"Месяцев: {months}\n"
                    f"Сумма: {amount} ⭐"
                )
            except:
                pass


# ===== ОБРАБОТКА ПОКУПКИ БОТА =====
@dp.message(F.text.regexp(r'^-?\d+$'))  # Ловим ID группы (отрицательное число)
async def process_group_id(message: Message, state: FSMContext):
    user_id = message.from_user.id
    group_id = int(message.text)

    # Проверяем, что это отрицательное число (ID группы/супергруппы)
    if group_id > 0:
        await message.answer(
            "❌ Это похоже на ID пользователя, а не группы.\n"
            "ID группы должен быть отрицательным числом (например, -1001234567890).\n\n"
            "🔍 Узнать ID группы: добавьте @getidallbot в группу и получите ID."
        )
        return

    data = await state.get_data()
    verified = data.get('verified', False)

    if verified:
        await message.answer(
            "✅ ID группы сохранен!\n\n"
            "Теперь отправьте токен бота от @BotFather и юзернейм бота в формате:\n"
            "ТОКЕН ЮЗЕРНЕЙМ\n\n"
            "Пример: 123456:ABCdef @my_bot"
        )
        await state.update_data(group_id=group_id)
        await state.set_state(BuyBotStates.waiting_for_token)
    else:
        # Сохраняем ID группы для неверифицированного аккаунта
        await state.update_data(group_id=group_id)
        await message.answer(
            "✅ ID группы сохранен!\n\n"
            "Теперь отправьте желаемый юзернейм для вашего бота (должен быть свободен):\n"
            "Пример: @my_new_bot\n\n"
            "Мы создадим бота с этим юзернеймом."
        )
        await state.set_state(BuyBotStates.waiting_for_bot_username)


@dp.message(BuyBotStates.waiting_for_token)
async def process_bot_token(message: Message, state: FSMContext):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer(
                "❌ Неверный формат!\n"
                "Отправьте токен и юзернейм через пробел:\n"
                "123456:ABCdef @my_bot"
            )
            return

        bot_token = parts[0]
        bot_username = parts[1].replace('@', '')

        # Проверяем токен
        try:
            test_bot = Bot(token=bot_token)
            bot_info = await test_bot.get_me()
            await test_bot.session.close()
        except Exception as e:
            await message.answer(
                f"❌ Токен недействителен!\n"
                f"Ошибка: {e}\n\n"
                "Проверьте токен от @BotFather и попробуйте снова."
            )
            return

        if bot_info.username != bot_username:
            await message.answer(
                f"❌ Юзернейм не совпадает с токеном!\n"
                f"Токен принадлежит боту @{bot_info.username}, а вы указали @{bot_username}\n\n"
                "Проверьте данные и попробуйте снова."
            )
            return

        data = await state.get_data()
        group_id = data.get('group_id')

        # Сохраняем бота в БД
        save_purchased_bot(message.from_user.id, bot_token, bot_username, group_id, verified=True)

        await message.answer(
            f"✅ Бот успешно сохранен!\n\n"
            f"🤖 Юзернейм: @{bot_username}\n"
            f"📝 Группа ID: {group_id}\n\n"
            "Теперь вам нужно купить хостинг для запуска бота.\n"
            "Перейдите в раздел «Мои боты» для управления."
        )

        # Уведомляем тех. админа
        try:
            await bot.send_message(
                TECH_ADMIN_ID,
                f"🤖 Новый бот (верифицированный)!\n"
                f"Пользователь: @{message.from_user.username or message.from_user.id}\n"
                f"Бот: @{bot_username}\n"
                f"Группа ID: {group_id}"
            )
        except:
            pass

        await state.clear()

    except Exception as e:
        logging.error(f"Error processing bot token: {e}")
        await message.answer(f"❌ Произошла ошибка: {e}")


@dp.message(BuyBotStates.waiting_for_bot_username)
async def process_bot_username(message: Message, state: FSMContext):
    bot_username = message.text.replace('@', '').strip()

    data = await state.get_data()
    group_id = data.get('group_id')

    # Сохраняем бота в БД (без токена, так как создавать будет тех. админ)
    save_purchased_bot(message.from_user.id, "", bot_username, group_id, verified=False)

    await message.answer(
        f"✅ Заявка на создание бота принята!\n\n"
        f"🤖 Желаемый юзернейм: @{bot_username}\n"
        f"📝 Группа ID: {group_id}\n\n"
        "Технический администратор создаст бота и свяжется с вами.\n"
        "После создания бота вам нужно будет купить хостинг для запуска.\n"
        "Перейдите в раздел «Мои боты» для управления."
    )

    # Уведомляем тех. админа
    try:
        await bot.send_message(
            TECH_ADMIN_ID,
            f"🤖 Заявка на создание бота (без верификации)!\n"
            f"Пользователь: @{message.from_user.username or message.from_user.id}\n"
            f"Желаемый юзернейм: @{bot_username}\n"
            f"Группа ID: {group_id}\n\n"
            "Необходимо создать бота и обновить токен в БД."
        )
    except:
        pass

    await state.clear()


# ===== УПРАВЛЕНИЕ БОТАМИ =====
@dp.callback_query(F.data == "bot_management")
async def bot_management(callback: CallbackQuery):
    await callback.message.edit_text(
        "🛠 Управление ботами\n\n"
        "Здесь вы можете купить собственного бота или управлять существующими.\n\n"
        f"💵 Стоимость бота: {get_bot_price()} ⭐\n"
        f"🖥 Хостинг: {get_hosting_price()} ⭐/месяц",
        reply_markup=get_bot_management_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "buy_bot")
async def buy_bot_info(callback: CallbackQuery):
    bot_price = get_bot_price()
    hosting_price = get_hosting_price()

    info_text = (
        "🤖 Покупка собственного бота\n\n"
        "Вы получаете такого же бота для своего использования со следующим функционалом:\n\n"
        "📚 Основные функции:\n"
        "• Продажа доступа к приватному контенту\n"
        "• Оплата звездами Telegram\n"
        "• Автоматическая выдача одноразовых ссылок\n"
        "• Управление пользователями и покупателями\n\n"
        "👑 Админ-панель:\n"
        "• Статистика (пользователи, доход)\n"
        "• Просмотр списка пользователей\n"
        "• Изменение цены доступа\n"
        "• Рассылка сообщений с кнопками\n\n"
        "🛠 Дополнительно:\n"
        "• Продажа ботов другим пользователям\n"
        "• Управление хостингом\n"
        "• Техподдержка\n\n"
        "❗️ ВАЖНО: Ваша группа должна быть приватной (частной)!\n"
        "Бот будет создавать одноразовые ссылки для вступления в группу.\n\n"
        f"💵 Стоимость бота: {bot_price} ⭐\n"
        f"🖥 Хостинг: {hosting_price} ⭐/месяц\n\n"
        "Выберите тип аккаунта:"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Есть верифицированный аккаунт", callback_data="verified_account")
    builder.button(text="❌ Нет верифицированного аккаунта", callback_data="unverified_account")
    builder.button(text="🔙 Назад", callback_data="bot_management")
    builder.adjust(1)

    await callback.message.edit_text(info_text, reply_markup=builder.as_markup())
    await callback.answer()


@dp.callback_query(F.data == "verified_account")
async def verified_account(callback: CallbackQuery, state: FSMContext):
    bot_price = get_bot_price()

    # Очищаем предыдущее состояние
    await state.clear()
    await state.update_data(verified=True)

    builder = InlineKeyboardBuilder()
    builder.button(text=f"Оплатить {bot_price} ⭐", pay=True)
    builder.button(text="❌ Отмена", callback_data="bot_management")

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Покупка бота",
        description="Покупка собственного бота с функционалом продажи доступа. Верифицированный аккаунт.",
        payload=f"bot_purchase_{callback.from_user.id}_True",
        provider_token=PROVIDER_TOKEN,
        currency="XTR",
        prices=[LabeledPrice(label="Бот", amount=bot_price)],
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@dp.callback_query(F.data == "unverified_account")
async def unverified_account(callback: CallbackQuery, state: FSMContext):
    bot_price = get_bot_price()

    # Очищаем предыдущее состояние
    await state.clear()
    await state.update_data(verified=False)

    builder = InlineKeyboardBuilder()
    builder.button(text=f"Оплатить {bot_price} ⭐", pay=True)
    builder.button(text="❌ Отмена", callback_data="bot_management")

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Покупка бота",
        description="Покупка бота без верифицированного аккаунта. Вывод звёзд с комиссией 5%.",
        payload=f"bot_purchase_{callback.from_user.id}_False",
        provider_token=PROVIDER_TOKEN,
        currency="XTR",
        prices=[LabeledPrice(label="Бот", amount=bot_price)],
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@dp.callback_query(F.data == "my_bots")
async def my_bots(callback: CallbackQuery):
    user_id = callback.from_user.id
    bots = get_user_bots(user_id)

    if not bots:
        await callback.message.edit_text(
            "📋 У вас пока нет купленных ботов.\n\n"
            "Купите бота в разделе «Купить бота».",
            reply_markup=get_bot_management_keyboard()
        )
        await callback.answer()
        return

    builder = InlineKeyboardBuilder()
    for bot_data in bots:
        bot_id, bot_username, group_id, purchase_date, hosting_expires, hosting_active, is_active, verified = bot_data

        status = "🟢" if hosting_active else "🔴"
        verified_text = "✅" if verified else "❌"

        builder.button(
            text=f"{status} {bot_username} {verified_text}",
            callback_data=f"bot_details_{bot_id}"
        )

    builder.button(text="🔙 Назад", callback_data="bot_management")
    builder.adjust(1)

    await callback.message.edit_text(
        "📋 Ваши боты:\n\n"
        f"Всего: {len(bots)}\n"
        "🟢 - хостинг активен\n"
        "🔴 - хостинг не активен\n"
        "✅ - верифицированный\n"
        "❌ - неверифицированный",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("bot_details_"))
async def bot_details(callback: CallbackQuery):
    bot_id = int(callback.data.split("_")[2])
    bot_info = get_bot_by_id(bot_id)

    if not bot_info:
        await callback.answer("❌ Бот не найден")
        return

    _, user_id, bot_username, group_id, purchase_date, hosting_expires, hosting_active, is_active = bot_info
    hosting_price = get_hosting_price()

    if hosting_expires:
        expires_date = datetime.fromisoformat(hosting_expires)
        days_left = (expires_date - datetime.now()).days
    else:
        days_left = 0
        expires_date = None

    info_text = (
        f"🤖 Бот: @{bot_username}\n"
        f"📝 Группа ID: {group_id}\n\n"
        f"📅 Дата покупки: {purchase_date[:10]}\n"
        f"🖥 Хостинг: {'🟢 Активен' if hosting_active else '🔴 Не активен'}\n"
    )

    if hosting_active and expires_date:
        info_text += f"📅 Действует до: {expires_date.strftime('%d.%m.%Y')}\n"
        info_text += f"⏳ Осталось дней: {days_left}\n"

    info_text += f"\n💵 Стоимость хостинга: {hosting_price} ⭐/месяц"

    builder = InlineKeyboardBuilder()
    builder.button(text=f"🖥 Купить хостинг (1 мес)", callback_data=f"buy_hosting_{bot_id}_1")
    builder.button(text=f"🖥 Купить хостинг (3 мес)", callback_data=f"buy_hosting_{bot_id}_3")
    builder.button(text=f"🖥 Купить хостинг (6 мес)", callback_data=f"buy_hosting_{bot_id}_6")
    builder.button(text=f"🖥 Купить хостинг (12 мес)", callback_data=f"buy_hosting_{bot_id}_12")
    builder.button(text="🔙 Назад", callback_data="my_bots")
    builder.adjust(1)

    await callback.message.edit_text(info_text, reply_markup=builder.as_markup())
    await callback.answer()


@dp.callback_query(F.data.startswith("buy_hosting_"))
async def buy_hosting(callback: CallbackQuery):
    parts = callback.data.split("_")
    bot_id = int(parts[2])
    months = int(parts[3])

    hosting_price = get_hosting_price()
    total_price = hosting_price * months

    builder = InlineKeyboardBuilder()
    builder.button(text=f"Оплатить {total_price} ⭐", pay=True)
    builder.button(text="❌ Отмена", callback_data=f"bot_details_{bot_id}")

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Хостинг бота",
        description=f"Хостинг бота на {months} мес. Бот будет запущен в течение 24 часов.",
        payload=f"hosting_{bot_id}_{months}",
        provider_token=PROVIDER_TOKEN,
        currency="XTR",
        prices=[LabeledPrice(label=f"Хостинг ({months} мес)", amount=total_price)],
        reply_markup=builder.as_markup()
    )
    await callback.answer()


# ===== АДМИН-ПАНЕЛЬ =====
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS and callback.from_user.id != TECH_ADMIN_ID:
        await callback.answer("❌ Нет доступа!")
        return

    total_users, total_buyers, total_income, total_bots, active_hostings = get_users_stats()
    keyboard = get_tech_admin_keyboard() if callback.from_user.id == TECH_ADMIN_ID else get_admin_keyboard()

    await callback.message.edit_text(
        "📊 Статистика\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"💳 Покупателей: {total_buyers}\n"
        f"💰 Общий доход: {total_income} ⭐\n"
        f"🤖 Всего ботов: {total_bots}\n"
        f"🖥 Активных хостингов: {active_hostings}\n"
        f"💵 Цена доступа: {get_current_price()} ⭐\n"
        f"🤖 Цена бота: {get_bot_price()} ⭐\n"
        f"🖥 Цена хостинга: {get_hosting_price()} ⭐",
        reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS and callback.from_user.id != TECH_ADMIN_ID:
        await callback.answer("❌ Нет доступа!")
        return

    users = get_all_users()
    keyboard = get_tech_admin_keyboard() if callback.from_user.id == TECH_ADMIN_ID else get_admin_keyboard()

    if not users:
        await callback.message.edit_text("👥 Пользователей нет", reply_markup=keyboard)
        return

    text = "👥 Пользователи:\n\n"
    for i, user in enumerate(users[:30], 1):
        status = "✅" if user[3] else "❌"
        username = f"@{user[1]}" if user[1] else "Нет"
        text += f"{i}. {status} {username} | ID: {user[0]}\n"

    if len(users) > 30:
        text += f"\n... и еще {len(users) - 30}"

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data == "admin_change_price")
async def admin_change_price(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS and callback.from_user.id != TECH_ADMIN_ID:
        await callback.answer("❌ Нет доступа!")
        return

    await callback.message.edit_text(
        "💰 Введите новую цену доступа в звёздах:",
        reply_markup=InlineKeyboardBuilder().button(
            text="🔙 Назад", callback_data="admin_back"
        ).as_markup()
    )
    await state.set_state(PriceStates.waiting_for_price)
    await callback.answer()


@dp.message(PriceStates.waiting_for_price)
async def process_new_price(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS and message.from_user.id != TECH_ADMIN_ID:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return

    try:
        new_price = int(message.text)
        if new_price < 1:
            await message.answer("❌ Цена должна быть больше 0!")
            return

        update_price(new_price)
        keyboard = get_tech_admin_keyboard() if message.from_user.id == TECH_ADMIN_ID else get_admin_keyboard()
        await message.answer(f"✅ Цена доступа обновлена: {new_price} ⭐", reply_markup=keyboard)
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число!")


@dp.callback_query(F.data == "admin_change_bot_price")
async def admin_change_bot_price(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != TECH_ADMIN_ID:
        await callback.answer("❌ Только тех. админ может менять цену бота!")
        return

    await callback.message.edit_text(
        "💵 Введите новую цену бота в звёздах:",
        reply_markup=InlineKeyboardBuilder().button(
            text="🔙 Назад", callback_data="admin_back"
        ).as_markup()
    )
    await state.set_state(PriceStates.waiting_for_bot_price)
    await callback.answer()


@dp.message(PriceStates.waiting_for_bot_price)
async def process_new_bot_price(message: Message, state: FSMContext):
    if message.from_user.id != TECH_ADMIN_ID:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return

    try:
        new_price = int(message.text)
        if new_price < 1:
            await message.answer("❌ Цена должна быть больше 0!")
            return

        update_bot_price(new_price)
        await message.answer(
            f"✅ Цена бота обновлена: {new_price} ⭐",
            reply_markup=get_tech_admin_keyboard()
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число!")


@dp.callback_query(F.data == "admin_change_hosting_price")
async def admin_change_hosting_price(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != TECH_ADMIN_ID:
        await callback.answer("❌ Только тех. админ может менять цену хостинга!")
        return

    await callback.message.edit_text(
        "🖥 Введите новую цену хостинга в звёздах (за месяц):",
        reply_markup=InlineKeyboardBuilder().button(
            text="🔙 Назад", callback_data="admin_back"
        ).as_markup()
    )
    await state.set_state(PriceStates.waiting_for_hosting_price)
    await callback.answer()


@dp.message(PriceStates.waiting_for_hosting_price)
async def process_new_hosting_price(message: Message, state: FSMContext):
    if message.from_user.id != TECH_ADMIN_ID:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return

    try:
        new_price = int(message.text)
        if new_price < 1:
            await message.answer("❌ Цена должна быть больше 0!")
            return

        update_hosting_price(new_price)
        await message.answer(
            f"✅ Цена хостинга обновлена: {new_price} ⭐/мес",
            reply_markup=get_tech_admin_keyboard()
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число!")


@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS and callback.from_user.id != TECH_ADMIN_ID:
        await callback.answer("❌ Нет доступа!")
        return

    await callback.message.edit_text(
        "📨 Введите сообщение для рассылки (текст, фото, видео, документ):",
        reply_markup=InlineKeyboardBuilder().button(
            text="🔙 Назад", callback_data="admin_back"
        ).as_markup()
    )
    await state.set_state(BroadcastStates.waiting_for_message)
    await callback.answer()


@dp.message(BroadcastStates.waiting_for_message)
async def broadcast_message(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS and message.from_user.id != TECH_ADMIN_ID:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return

    await state.update_data(
        broadcast_message=message.text or message.caption,
        broadcast_photo=message.photo[-1].file_id if message.photo else None,
        broadcast_video=message.video.file_id if message.video else None,
        broadcast_document=message.document.file_id if message.document else None
    )

    await message.answer(
        "📨 Добавьте кнопки (опционально):\n\n"
        "Формат: Текст кнопки -> ссылка\n"
        "Пример: Наш канал -> https://t.me/channel\n\n"
        "Для новой кнопки — новая строка.\n"
        "Если кнопки не нужны, введите 0"
    )
    await state.set_state(BroadcastStates.waiting_for_buttons)


@dp.message(BroadcastStates.waiting_for_buttons)
async def broadcast_buttons(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS and message.from_user.id != TECH_ADMIN_ID:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return

    data = await state.get_data()
    users = get_all_users()

    builder = None
    if message.text != "0":
        builder = InlineKeyboardBuilder()
        buttons_text = message.text.split("\n")

        for button_text in buttons_text:
            if "->" in button_text:
                text, url = button_text.split("->")
                builder.button(text=text.strip(), url=url.strip())

        builder.adjust(1)

    sent_count = 0
    failed_count = 0

    await message.answer(f"📨 Рассылка на {len(users)} пользователей...")

    for user in users:
        try:
            if data.get('broadcast_photo'):
                await bot.send_photo(
                    user[0],
                    data['broadcast_photo'],
                    caption=data.get('broadcast_message', ''),
                    reply_markup=builder.as_markup() if builder else None
                )
            elif data.get('broadcast_video'):
                await bot.send_video(
                    user[0],
                    data['broadcast_video'],
                    caption=data.get('broadcast_message', ''),
                    reply_markup=builder.as_markup() if builder else None
                )
            elif data.get('broadcast_document'):
                await bot.send_document(
                    user[0],
                    data['broadcast_document'],
                    caption=data.get('broadcast_message', ''),
                    reply_markup=builder.as_markup() if builder else None
                )
            else:
                await bot.send_message(
                    user[0],
                    data.get('broadcast_message', ''),
                    reply_markup=builder.as_markup() if builder else None
                )
            sent_count += 1
        except Exception as e:
            failed_count += 1
        await asyncio.sleep(0.1)

    keyboard = get_tech_admin_keyboard() if message.from_user.id == TECH_ADMIN_ID else get_admin_keyboard()
    await message.answer(
        f"📨 Рассылка завершена!\n✅ Отправлено: {sent_count}\n❌ Не удалось: {failed_count}",
        reply_markup=keyboard
    )
    await state.clear()


@dp.callback_query(F.data == "admin_all_bots")
async def admin_all_bots(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS and callback.from_user.id != TECH_ADMIN_ID:
        await callback.answer("❌ Нет доступа!")
        return

    bots = get_all_bots()
    keyboard = get_tech_admin_keyboard() if callback.from_user.id == TECH_ADMIN_ID else get_admin_keyboard()

    if not bots:
        await callback.message.edit_text("🤖 Нет купленных ботов", reply_markup=keyboard)
        return

    text = "🤖 Все боты:\n\n"
    for bot_data in bots[:20]:
        bot_id, user_id, bot_username, group_id, purchase_date, hosting_expires, hosting_active, is_active, verified, username = bot_data
        status = "🟢" if hosting_active else "🔴"
        text += f"{status} @{bot_username} | Группа: {group_id} | Владелец: @{username or user_id}\n"

    if len(bots) > 20:
        text += f"\n... и еще {len(bots) - 20}"

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data == "tech_notify_launch")
async def tech_notify_launch(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != TECH_ADMIN_ID:
        await callback.answer("❌ Только тех. админ!")
        return

    await callback.message.edit_text(
        "📬 Отправьте ID пользователя, которому нужно отправить уведомление о запуске бота:",
        reply_markup=InlineKeyboardBuilder().button(
            text="🔙 Назад", callback_data="admin_back"
        ).as_markup()
    )
    await state.set_state(TechNotifyState.waiting_for_user_id)
    await callback.answer()


@dp.message(TechNotifyState.waiting_for_user_id)
async def tech_notify_user_id(message: Message, state: FSMContext):
    if message.from_user.id != TECH_ADMIN_ID:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return

    try:
        user_id = int(message.text)
        await state.update_data(notify_user_id=user_id)

        await message.answer(
            f"📬 Введите текст уведомления для пользователя {user_id}:",
            reply_markup=InlineKeyboardBuilder().button(
                text="🔙 Назад", callback_data="admin_back"
            ).as_markup()
        )
        await state.set_state(TechNotifyState.waiting_for_message)
    except ValueError:
        await message.answer("❌ Введите корректный ID!")


@dp.message(TechNotifyState.waiting_for_message)
async def tech_notify_send(message: Message, state: FSMContext):
    if message.from_user.id != TECH_ADMIN_ID:
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return

    data = await state.get_data()
    user_id = data.get('notify_user_id')

    try:
        await bot.send_message(
            user_id,
            f"📬 Уведомление о запуске бота:\n\n{message.text}\n\n"
            f"Если у вас есть вопросы, обратитесь в техподдержку: {SUPPORT_LINK}"
        )
        await message.answer(
            f"✅ Уведомление отправлено пользователю {user_id}",
            reply_markup=get_tech_admin_keyboard()
        )
    except Exception as e:
        await message.answer(
            f"❌ Ошибка отправки: {e}",
            reply_markup=get_tech_admin_keyboard()
        )

    await state.clear()


@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery, state: FSMContext = None):
    if state:
        await state.clear()

    keyboard = get_tech_admin_keyboard() if callback.from_user.id == TECH_ADMIN_ID else get_admin_keyboard()
    await callback.message.edit_text("👑 Панель управления\n\nВыберите действие:", reply_markup=keyboard)
    await callback.answer()


# ===== ПРОВЕРКА ХОСТИНГА (без aioschedule) =====
async def check_expiring_hostings():
    """Проверка истекающих хостингов и отправка уведомлений"""
    while True:
        try:
            expiring_bots, days_left = get_expiring_hostings()

            for bot_data in expiring_bots:
                bot_id, user_id, bot_username, expires_at = bot_data

                try:
                    await bot.send_message(
                        user_id,
                        f"⚠️ Внимание!\n\n"
                        f"Хостинг бота @{bot_username} истекает через {days_left} дн.\n"
                        f"Дата окончания: {expires_at[:10]}\n\n"
                        f"Продлите хостинг заранее, чтобы бот продолжал работать!\n"
                        f"Стоимость: {get_hosting_price()} ⭐/мес\n\n"
                        f"Для продления перейдите в раздел «Мои боты»."
                    )
                except Exception as e:
                    logging.error(f"Error sending hosting notification: {e}")

            # Ждем 24 часа до следующей проверки
            await asyncio.sleep(86400)
        except Exception as e:
            logging.error(f"Error in hosting check: {e}")
            # При ошибке ждем час и пробуем снова
            await asyncio.sleep(3600)


# ===== ОБРАБОТКА ВСТУПЛЕНИЯ В ГРУППУ =====
@dp.chat_member()
async def handle_new_member(chat_member: types.ChatMemberUpdated):
    if chat_member.chat.id == GROUP_ID:
        if chat_member.invite_link:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE invite_links SET is_used = TRUE 
                WHERE link = ?
            ''', (chat_member.invite_link.invite_link,))
            conn.commit()
            conn.close()


# ===== ЗАПУСК =====
async def main():
    # Инициализация базы данных
    init_db()
    print("✅ База данных инициализирована")

    # Запускаем проверку хостингов в фоне
    asyncio.create_task(check_expiring_hostings())

    # Запуск бота
    print("🚀 Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен")
    except Exception as e:
        print(f"❌ Ошибка при запуске: {e}")