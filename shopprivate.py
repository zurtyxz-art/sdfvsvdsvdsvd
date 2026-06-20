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
from typing import List, Dict
import secrets

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# ===== НАСТРОЙКИ БОТА =====
# Вставьте сюда токен вашего бота от @BotFather
API_TOKEN = ""  # Например: "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
PROVIDER_TOKEN = ""  # Оставляем пустым для оплаты звездами

# ID группы, где находится бот (получить через @getidsbot)
GROUP_ID = -1004280733439  # Замените на ID вашей группы

# Список ID администраторов (получить через @getidsbot)
ADMIN_IDS = [5254779646, 5217681536]  # Замените на реальные ID админов

# Ссылки
SUPPORT_LINK = "https://t.me/zurtyxz"  # Ссылка на поддержку (замените на свою)
PRIVACY_POLICY_LINK = "https://telegra.ph/Politika-konfidencialnosti-04-01-26"  # Политика конфиденциальности
TERMS_OF_USE_LINK = "https://telegra.ph/Polzovatelskoe-soglashenie-04-01-19"  # Пользовательское соглашение

# ===== ПРОВЕРКА НАСТРОЕК =====
if API_TOKEN == "ВАШ_ТОКЕН_БОТА_ЗДЕСЬ":
    print("❌ ОШИБКА: Замените API_TOKEN на реальный токен бота!")
    print("Получить токен можно у @BotFather в Telegram")
    exit(1)

if GROUP_ID == -1001234567890:
    print("⚠️ ПРЕДУПРЕЖДЕНИЕ: Не забудьте заменить GROUP_ID на ID вашей группы!")
    print("ID группы можно узнать через @getidsbot")

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


# Работа с базой данных
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
            payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_successful BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')

    # Таблица ссылок
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

    # Таблица настроек
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # Установка начальной цены, если её нет
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value) VALUES ('price', '100')
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
    cursor.execute('''
        UPDATE users SET is_buyer = TRUE WHERE user_id = ?
    ''', (user_id,))
    conn.commit()
    conn.close()


def get_users_stats():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM users WHERE is_buyer = TRUE')
    total_buyers = cursor.fetchone()[0]

    cursor.execute('SELECT SUM(amount) FROM payments WHERE is_successful = TRUE')
    total_income = cursor.fetchone()[0] or 0

    conn.close()
    return total_users, total_buyers, total_income


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


def update_price(new_price: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE settings SET value = ? WHERE key = "price"', (str(new_price),))
    conn.commit()
    conn.close()


def save_invite_link(link: str, user_id: int):
    expires_at = datetime.now() + timedelta(hours=24)  # Ссылка действительна 24 часа
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO invite_links (link, user_id, expires_at) 
        VALUES (?, ?, ?)
    ''', (link, user_id, expires_at))
    conn.commit()
    conn.close()


def save_payment(user_id: int, amount: int, is_successful: bool = True):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO payments (user_id, amount, is_successful) 
        VALUES (?, ?, ?)
    ''', (user_id, amount, is_successful))
    conn.commit()
    conn.close()


# Клавиатуры
def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    current_price = get_current_price()
    builder.button(text=f"💫 Купить приват ({current_price} ⭐)", callback_data="buy_access")
    builder.button(text="ℹ️ О привате", callback_data="about_access")
    builder.button(text="🆘 Поддержка", url=SUPPORT_LINK)
    builder.button(text="📜 Пользовательское соглашение", url=TERMS_OF_USE_LINK)
    builder.button(text="🔒 Политика конфиденциальности", url=PRIVACY_POLICY_LINK)
    builder.adjust(1)
    return builder.as_markup()


def get_legal_keyboard():
    """Клавиатура с правовой информацией"""
    builder = InlineKeyboardBuilder()
    builder.adjust(1)
    return builder.as_markup()


def get_admin_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="👥 Пользователи", callback_data="admin_users")
    builder.button(text="💰 Изменить цену", callback_data="admin_change_price")
    builder.button(text="📨 Рассылка", callback_data="admin_broadcast")
    builder.adjust(2)
    return builder.as_markup()


# Команды
@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name

    add_user(user_id, username, full_name)

    # Формируем приветственное сообщение с правовой информацией
    welcome_text = (
        "👋 Добро пожаловать!\n\n"
        "Здесь вы можете купить приват по монтажу.\n"
        f"Текущая цена: {get_current_price()} ⭐\n\n"
        "Используя бота, вы соглашаетесь с:\n"
        "• Пользовательским соглашением\n"
        "• Политикой конфиденциальности\n\n"
        "По всем вопросам обращайтесь в поддержку."
    )

    if user_id in ADMIN_IDS:
        await message.answer(
            "👑 Админ-панель\n\nВыберите действие:",
            reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer(
            welcome_text,
            reply_markup=get_main_keyboard(),
            disable_web_page_preview=True
        )

        # Отправляем отдельное сообщение с правовыми кнопками
        


@dp.callback_query(F.data == "buy_access")
async def buy_access(callback: CallbackQuery):
    current_price = get_current_price()

    # Создаем клавиатуру с правовой информацией для счета
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Оплатить {current_price} ⭐", pay=True)
    builder.button(text="❌ Отмена", callback_data="cancel_payment")

    # Отправляем правовую информацию перед оплатой


    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Доступ к привату",
        description=f"Одноразовая ссылка для вступления в приват. Действительна 24 часа.\n\n"
                    f"Совершая покупку, вы соглашаетесь с пользовательским соглашением и политикой конфиденциальности.",
        payload=f"access_{callback.from_user.id}",
        provider_token=PROVIDER_TOKEN,
        currency="XTR",
        prices=[LabeledPrice(label="Приват", amount=current_price)],
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@dp.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer("❌ Оплата отменена")


@dp.callback_query(F.data == "about_access")
async def about_access(callback: CallbackQuery):
    about_text = (
        "📚 Приват по монтажу\n\n"
        "• Эксклюзивные туториалы\n"
        "• Исходники\n"
        "• Пресеты\n"
        "• Поддержка и помощь\n"
        "• Больше информации тут - https://t.me/Zurtyxz_Edits/1949\n\n"
        f"Цена: {get_current_price()} ⭐\n"
        "После оплаты вы получите одноразовую ссылку на 24 часа."
    )

    await callback.message.edit_text(
        about_text,
        reply_markup=get_main_keyboard()
    )
    await callback.answer()


@dp.pre_checkout_query()
async def pre_checkout_query(pre_checkout: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout.id, ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    user_id = message.from_user.id
    amount = message.successful_payment.total_amount

    # Сохраняем информацию о платеже
    save_payment(user_id, amount)
    mark_as_buyer(user_id)

    # Создаем одноразовую ссылку
    try:
        invite_link = await bot.create_chat_invite_link(
            chat_id=GROUP_ID,
            member_limit=1,  # Одноразовая ссылка
            expire_date=datetime.now() + timedelta(hours=24)
        )

        # Сохраняем ссылку в базе
        save_invite_link(invite_link.invite_link, user_id)

        # Отправляем ссылку пользователю
        await message.answer(
            f"✨ Спасибо за оплату {amount} звёзд!\n\n"
            f"🔗 Ваша одноразовая ссылка для входа в группу:\n"
            f"{invite_link.invite_link}\n\n"
            f"⚠️ Ссылка действительна 24 часа и может быть использована только один раз.\n"
            f"Не передавайте её третьим лицам!\n\n"
            f"📞 По вопросам: {SUPPORT_LINK}"
        )

        # Оповещаем админов о новой покупке
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"💰 Новая покупка!\n"
                    f"Пользователь: @{message.from_user.username or message.from_user.id}\n"
                    f"Сумма: {amount} ⭐\n"
                    f"Ссылка создана: {invite_link.invite_link[:30]}..."
                )
            except Exception as e:
                logging.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")

    except Exception as e:
        logging.error(f"Error creating invite link: {e}")
        await message.answer(
            f"❌ Произошла ошибка при создании ссылки. Пожалуйста, обратитесь в поддержку: {SUPPORT_LINK}"
        )


# Админ-панель
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ У вас нет доступа!")
        return

    total_users, total_buyers, total_income = get_users_stats()

    await callback.message.edit_text(
        "📊 Статистика бота\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"💳 Покупателей: {total_buyers}\n"
        f"💰 Общий доход: {total_income} ⭐\n"
        f"💵 Текущая цена: {get_current_price()} ⭐",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ У вас нет доступа!")
        return

    users = get_all_users()

    if not users:
        await callback.message.edit_text(
            "👥 Пользователей пока нет",
            reply_markup=get_admin_keyboard()
        )
        return

    text = "👥 Список пользователей:\n\n"
    for user in users[:5000]:  # Показываем первые 50
        status = "" if user[3] else ""
        username = f"@{user[1]}" if user[1] else "Нет username"
        text += f"{status} {username} | ID: {user[0]}\n"

    if len(users) > 5000:
        text += f"\n... и еще {len(users) - 5000} пользователей"

    # Разбиваем длинное сообщение
    if len(text) > 4096:
        for x in range(0, len(text), 4096):
            await callback.message.answer(text[x:x + 4096])
    else:
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard())

    await callback.answer()


@dp.callback_query(F.data == "admin_change_price")
async def admin_change_price(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ У вас нет доступа!")
        return

    await callback.message.edit_text(
        "💰 Введите новую цену в звёздах (только число):",
        reply_markup=InlineKeyboardBuilder().button(
            text="🔙 Назад", callback_data="admin_back"
        ).as_markup()
    )
    await state.set_state(PriceStates.waiting_for_price)
    await callback.answer()


@dp.message(PriceStates.waiting_for_price)
async def process_new_price(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа!")
        await state.clear()
        return

    try:
        new_price = int(message.text)
        if new_price < 1:
            await message.answer("❌ Цена должна быть больше 0!")
            return

        update_price(new_price)
        await message.answer(
            f"✅ Цена обновлена! Текущая цена: {new_price} ⭐",
            reply_markup=get_admin_keyboard()
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Пожалуйста, введите число!")


@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ У вас нет доступа!")
        return

    await callback.message.edit_text(
        "📨 Введите сообщение для рассылки (текст, фото, видео):",
        reply_markup=InlineKeyboardBuilder().button(
            text="🔙 Назад", callback_data="admin_back"
        ).as_markup()
    )
    await state.set_state(BroadcastStates.waiting_for_message)
    await callback.answer()


@dp.message(BroadcastStates.waiting_for_message)
async def broadcast_message(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа!")
        await state.clear()
        return

    # Сохраняем сообщение для рассылки
    await state.update_data(
        broadcast_message=message.text or message.caption,
        broadcast_photo=message.photo[-1].file_id if message.photo else None,
        broadcast_video=message.video.file_id if message.video else None,
        broadcast_document=message.document.file_id if message.document else None
    )

    await message.answer(
        "📨 Добавьте кнопки к сообщению (опционально)\n\n"
        "Формат: Текст кнопки - ссылка\n"
        "Пример: Наш канал - https://t.me/channel\n\n"
        "Для каждой новой кнопки — новая строка.\n"
        "Если кнопки не нужны, введите 0"
    )
    await state.set_state(BroadcastStates.waiting_for_buttons)


@dp.message(BroadcastStates.waiting_for_buttons)
async def broadcast_buttons(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа!")
        await state.clear()
        return

    data = await state.get_data()
    users = get_all_users()

    builder = None
    if message.text != "0":
        # Создаем кнопки
        builder = InlineKeyboardBuilder()
        buttons_text = message.text.split("\n")

        for button_text in buttons_text:
            if "-" in button_text:
                text, url = button_text.split("-")
                builder.button(text=text.strip(), url=url.strip())

        builder.adjust(1)

    # Отправляем рассылку
    sent_count = 0
    failed_count = 0

    await message.answer(f"📨 Начинаю рассылку на {len(users)} пользователей...")

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
            logging.error(f"Failed to send to {user[0]}: {e}")
            failed_count += 1
        await asyncio.sleep(0.1)  # Задержка для избежания ограничений

    await message.answer(
        f"📨 Рассылка завершена!\n\n"
        f"✅ Отправлено: {sent_count}\n"
        f"❌ Не удалось отправить: {failed_count}",
        reply_markup=get_admin_keyboard()
    )

    await state.clear()


@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery, state: FSMContext = None):
    if state:
        await state.clear()
    await callback.message.edit_text(
        "👑 Админ-панель\n\nВыберите действие:",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()


# Обработка новых участников в группе
@dp.chat_member()
async def handle_new_member(chat_member: types.ChatMemberUpdated):
    # Проверяем, что это наша группа
    if chat_member.chat.id == GROUP_ID:
        # Проверяем, использовал ли пользователь нашу ссылку
        if chat_member.invite_link:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE invite_links SET is_used = TRUE 
                WHERE link = ?
            ''', (chat_member.invite_link.invite_link,))
            conn.commit()
            conn.close()


async def main():
    # Инициализация базы данных
    init_db()
    print("✅ База данных инициализирована")

    # Запуск бота
    print("🚀 Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен")
    except Exception as e:
        print(f"❌ Ошибка при запуске бота: {e}")