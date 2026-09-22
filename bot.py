import logging
from datetime import time, datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    ADMIN_IDS,
    REPORT_HOUR,
    REPORT_MINUTE,
)
from core import build_report
from db import init_db, get_all_lists, add_request
from utils import validate_quantity, split_message

logger = logging.getLogger(__name__)

# ===== СОСТОЯНИЯ CONVERSATION =====
NAME, QUANTITY, UNIT, INITIATOR, INITIATOR_CUSTOM, OBJECT, NOTES, CONFIRM = range(8)

# ===== КЛАВИАТУРА ОТМЕНЫ =====
CANCEL_KEYBOARD = ReplyKeyboardMarkup(
    [["❌ Отмена"]], resize_keyboard=True, one_time_keyboard=False
)


# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором"""
    return user_id in ADMIN_IDS


def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Возвращает главную клавиатуру в зависимости от прав"""
    if is_admin(user_id):
        keyboard = [
            ["📊 Анализ"],
            ["➕ Добавить заявку"],
            ["⛔ Выход"]
        ]
    else:
        keyboard = [["➕ Добавить заявку"], ["⛔ Выход"]]

    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def send_long_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, parse_mode: str = None):
    """Отправляет длинное сообщение по частям"""
    parts = split_message(text)
    for part in parts:
        await context.bot.send_message(
            chat_id=chat_id,
            text=part,
            parse_mode=parse_mode
        )


# ===== КОМАНДЫ =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user_id = update.effective_user.id
    username = update.effective_user.first_name or "пользователь"
    markup = get_main_keyboard(user_id)

    if is_admin(user_id):
        text = (
            f"👋 Здравствуйте, <b>{username}</b>!\n\n"
            f"Автоотчёт приходит каждый день в {REPORT_HOUR:02d}:{REPORT_MINUTE:02d}.\n\n"
            "Выберите действие:"
        )
    else:
        text = (
            f"👋 Здравствуйте, <b>{username}</b>!\n\n"
            "Используйте бот для добавления заявок."
        )

    await update.message.reply_text(text, reply_markup=markup, parse_mode='HTML')


async def run_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запускает анализ вручную"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ У вас нет прав для этой команды.")
        return

    await update.message.reply_text("⏳ Запускаю анализ...")

    try:
        result = build_report()
        await send_long_message(context, update.effective_chat.id, result, parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка анализа:\n<code>{e}</code>", parse_mode='HTML')


async def scheduled_report(context: ContextTypes.DEFAULT_TYPE):
    """Автоматический ежедневный отчёт"""
    chat_id = context.job.chat_id
    try:
        result = build_report()
        await send_long_message(context, chat_id, result, parse_mode='HTML')
    except Exception as e:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Ошибка автоотчёта:\n<code>{e}</code>",
            parse_mode='HTML'
        )


# ===== CONVERSATION HANDLER =====
async def start_add_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало добавления заявки"""
    context.user_data.clear()

    await update.message.reply_text(
        "📦 <b>Шаг 1/6:</b> Введите наименование товара/услуги:",
        reply_markup=CANCEL_KEYBOARD,
        parse_mode='HTML'
    )
    return NAME


async def set_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет название и запрашивает количество"""
    context.user_data['name'] = update.message.text.strip()
    await update.message.reply_text(
        "🔢 <b>Шаг 2/6:</b> Введите количество (только число):",
        reply_markup=CANCEL_KEYBOARD,
        parse_mode='HTML'
    )
    return QUANTITY


async def set_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет количество и запрашивает единицу измерения"""
    qty = update.message.text.strip()

    if not validate_quantity(qty):
        await update.message.reply_text(
            "❌ Пожалуйста, введите <b>число</b> (например, 10 или 5.5):",
            parse_mode='HTML'
        )
        return QUANTITY

    context.user_data['quantity'] = qty

    try:
        lists = get_all_lists()
        units = lists.get("unit", ["шт", "кг", "л", "м2", "м3", "лист", "м.п.", "комп"])
    except Exception:
        units = ["шт", "кг", "л", "м2", "м3", "лист", "м.п.", "комп"]

    keyboard = [units[i:i + 3] for i in range(0, len(units), 3)]
    keyboard.append(["❌ Отмена"])
    await update.message.reply_text(
        "📏 <b>Шаг 3/6:</b> Выберите единицу измерения:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode='HTML'
    )
    return UNIT


async def set_unit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет единицу измерения и запрашивает инициатора"""
    context.user_data['unit'] = update.message.text.strip()

    try:
        lists = get_all_lists()
        initiators = lists.get("initiator", ["Иван", "Петр", "Анна", "Другое"])
    except Exception as e:
        logger.error(f"Ошибка загрузки списков: {e}")
        initiators = ["Иван", "Петр", "Анна", "Другое"]

    keyboard = [initiators[i:i + 2] for i in range(0, len(initiators), 2)]
    keyboard.append(["❌ Отмена"])
    await update.message.reply_text(
        "👤 <b>Шаг 4/6:</b> Выберите инициатора:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode='HTML'
    )
    return INITIATOR


async def set_initiator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет инициатора и запрашивает объект"""
    initiator = update.message.text.strip()

    if initiator == "Другое":
        await update.message.reply_text(
            "✍️ Введите имя инициатора:",
            reply_markup=CANCEL_KEYBOARD,
            parse_mode='HTML'
        )
        return INITIATOR_CUSTOM

    context.user_data['initiator'] = initiator

    try:
        lists = get_all_lists()
        objects = lists.get("object", ["Солнечное", "Привилегия", "Не указан"])
    except Exception:
        objects = ["Солнечное", "Привилегия", "Не указан"]

    keyboard = [objects[i:i + 2] for i in range(0, len(objects), 2)]
    keyboard.append(["❌ Отмена"])
    await update.message.reply_text(
        "🏗️ <b>Шаг 5/6:</b> Выберите объект:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode='HTML'
    )
    return OBJECT


async def set_initiator_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет кастомное имя инициатора и переходит к объектам"""
    context.user_data['initiator'] = update.message.text.strip()

    try:
        lists = get_all_lists()
        objects = lists.get("object", ["Солнечное", "Привилегия", "Не указан"])
    except Exception:
        objects = ["Солнечное", "Привилегия", "Не указан"]

    keyboard = [objects[i:i + 2] for i in range(0, len(objects), 2)]
    keyboard.append(["❌ Отмена"])
    await update.message.reply_text(
        "🏗️ <b>Шаг 5/6:</b> Выберите объект:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode='HTML'
    )
    return OBJECT


async def set_object(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет объект и запрашивает примечание"""
    context.user_data['object'] = update.message.text.strip()

    await update.message.reply_text(
        "📝 <b>Шаг 6/6:</b> Добавьте примечание (или отправьте <code>-</code> для пропуска):",
        reply_markup=CANCEL_KEYBOARD,
        parse_mode='HTML'
    )
    return NOTES


async def set_notes_and_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет примечание и показывает сводку для подтверждения"""
    notes = update.message.text.strip()
    if notes == "-":
        notes = ""

    context.user_data['notes'] = notes

    summary = (
        "📋 <b>Проверьте заявку:</b>\n\n"
        f"📦 Наименование: <b>{context.user_data['name']}</b>\n"
        f"🔢 Количество: <code>{context.user_data['quantity']} {context.user_data['unit']}</code>\n"
        f"👤 Инициатор: {context.user_data['initiator']}\n"
        f"🏗️ Объект: {context.user_data['object']}\n"
        f"📝 Примечание: {notes or '—'}\n\n"
        "Подтвердите или отмените:"
    )

    keyboard = ReplyKeyboardMarkup(
        [["✅ Подтвердить", "❌ Отмена"]],
        resize_keyboard=True
    )

    await update.message.reply_text(summary, reply_markup=keyboard, parse_mode='HTML')
    return CONFIRM


async def confirm_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждает и сохраняет заявку, либо отменяет"""
    text = update.message.text.strip()
    user_id = update.effective_user.id

    if text == "❌ Отмена":
        context.user_data.clear()
        await update.message.reply_text(
            "❌ Заявка отменена.",
            reply_markup=get_main_keyboard(user_id)
        )
        return ConversationHandler.END

    # Сохраняем заявку
    from datetime import date
    today = date.today()

    try:
        add_request(
            name=context.user_data['name'],
            quantity=float(context.user_data['quantity']),
            unit=context.user_data['unit'],
            request_date=today,
            initiator=context.user_data['initiator'],
            object_name=context.user_data['object'],
            notes=context.user_data['notes'],
        )

        summary = (
            "✅ <b>Заявка успешно добавлена!</b>\n\n"
            f"📦 Наименование: {context.user_data['name']}\n"
            f"🔢 Количество: {context.user_data['quantity']} {context.user_data['unit']}\n"
            f"👤 Инициатор: {context.user_data['initiator']}\n"
            f"🏗️ Объект: {context.user_data['object']}\n"
            f"📝 Примечание: {context.user_data['notes'] or '—'}"
        )

        await update.message.reply_text(
            summary,
            reply_markup=get_main_keyboard(user_id),
            parse_mode='HTML'
        )

    except Exception as e:
        logger.error(f"Ошибка при сохранении заявки: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ Ошибка при сохранении заявки:\n<code>{e}</code>",
            parse_mode='HTML'
        )

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет текущую операцию"""
    context.user_data.clear()
    user_id = update.effective_user.id

    await update.message.reply_text(
        "❌ Операция отменена.",
        reply_markup=get_main_keyboard(user_id)
    )
    return ConversationHandler.END


# ===== ОБРАБОТКА ГЛАВНОГО МЕНЮ =====
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает кнопки главного меню"""
    text = update.message.text.strip()
    user_id = update.effective_user.id

    if text == "📊 Анализ":
        await run_analysis(update, context)

    elif text == "⛔ Выход":
        await update.message.reply_text(
            "👋 До встречи! Для возврата введите /start",
            reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
        )

    else:
        await update.message.reply_text(
            "Используйте кнопки меню или /start",
            reply_markup=get_main_keyboard(user_id)
        )


# ===== ГЛАВНАЯ ФУНКЦИЯ =====
def main():
    """Точка входа"""
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^➕ Добавить заявку$'), start_add_request)
        ],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_name)],
            QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_quantity)],
            UNIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_unit)],
            INITIATOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_initiator)],
            INITIATOR_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_initiator_custom)],
            OBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_object)],
            NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_notes_and_save)],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_request)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            MessageHandler(filters.Regex('^❌ Отмена$'), cancel),
        ],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))

    app.job_queue.run_daily(
        scheduled_report,
        time=time(hour=REPORT_HOUR, minute=REPORT_MINUTE),
        chat_id=int(TELEGRAM_CHAT_ID),
        name="daily_report",
    )

    logger.info(f" Бот запущен. Отчёт ежедневно в {REPORT_HOUR:02d}:{REPORT_MINUTE:02d}")
    app.run_polling()


if __name__ == "__main__":
    main()