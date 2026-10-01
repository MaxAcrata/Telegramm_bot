import logging
from datetime import time, datetime, date
from html import escape
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler,
)
from telegram.request import HTTPXRequest

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    ADMIN_IDS,
    REPORT_HOUR,
    REPORT_MINUTE,
    SOCKS5_PROXY,
)
from core import build_report
from db import (
    init_db, get_all_lists, add_request,
    rename_list_value, delete_list_value, add_list_value,
    get_setting, set_setting, get_active_requests, complete_request,
    link_initiator, get_initiator_tg_id, get_initiator_by_tg_id,
)
from utils import validate_quantity, split_message

logger = logging.getLogger(__name__)

# ===== СОСТОЯНИЯ CONVERSATION =====
(NAME, QUANTITY, UNIT, INITIATOR, INITIATOR_CUSTOM,
 OBJECT, OBJECT_CUSTOM, NOTES, CONFIRM) = range(9)

# ===== СОСТОЯНИЯ ЗАВЕРШЕНИЯ ЗАЯВКИ =====
(COMPLETE_SELECT, COMPLETE_CONFIRM) = range(50, 52)

# ===== СОСТОЯНИЕ РЕГИСТРАЦИИ ИНИЦИАТОРА =====
REG_NAME = 90

# ===== СОСТОЯНИЯ АДМИН-ПАНЕЛИ =====
(ADMIN_MENU, ADMIN_LIST_VIEW, ADMIN_RENAME_OLD,
 ADMIN_RENAME_NEW, ADMIN_DELETE, ADMIN_ADD_VALUE,
 ADMIN_BUTTONS_EDIT) = range(100, 107)

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
            ["✅ Завершить заявку"],
            ["⚙️ Настройки"],
            ["⛔ Выход"]
        ]
    else:
        keyboard = [["➕ Добавить заявку"], ["⛔ Выход"]]

    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def send_long_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, parse_mode: str = None, disable_web_page_preview: bool = True):
    """Отправляет длинное сообщение по частям"""
    parts = split_message(text)
    for part in parts:
        await context.bot.send_message(
            chat_id=chat_id,
            text=part,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview
        )


# ===== КОМАНДЫ =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user_id = update.effective_user.id
    username = update.effective_user.first_name or "пользователь"

    if is_admin(user_id):
        markup = get_main_keyboard(user_id)
        text = (
            f"👋 Здравствуйте, <b>{escape(username)}</b>!\n\n"
            f"Автоотчёт приходит каждый день в {REPORT_HOUR:02d}:{REPORT_MINUTE:02d}.\n\n"
            "Выберите действие:"
        )
        await update.message.reply_text(text, reply_markup=markup, parse_mode='HTML')
        return ConversationHandler.END
    else:
        existing = get_initiator_by_tg_id(user_id)
        if existing:
            await update.message.reply_text(
                f"👋 Здравствуйте, <b>{escape(username)}</b>!\n\n"
                f"Вы привязаны как <b>{escape(existing)}</b>.\n"
                "Используйте бот для добавления заявок.",
                reply_markup=get_main_keyboard(user_id),
                parse_mode='HTML',
            )
            return ConversationHandler.END
        else:
            return await register_start(update, context)


async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список инициаторов для привязки"""
    lists = get_all_lists()
    initiators = [i for i in lists.get("initiator", []) if i != "Другое"]

    cols = int(get_setting("buttons_per_row_initiator", "4"))
    keyboard = [initiators[i:i + cols] for i in range(0, len(initiators), cols)]
    keyboard.append(["Другое"])

    await update.message.reply_text(
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Выберите своё имя из списка, чтобы получать уведомления о заявках:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode='HTML',
    )
    return REG_NAME


async def register_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет имя инициатора"""
    text = update.message.text.strip()
    user_id = update.effective_user.id

    if text == "Другое":
        await update.message.reply_text(
            "✍️ Введите ваше имя (как в справочнике или новое):",
            reply_markup=ReplyKeyboardRemove(),
        )
        return REG_NAME

    # H2: Проверяем, не привязано ли имя к другому пользователю
    existing_tg = get_initiator_tg_id(text)
    if existing_tg and existing_tg != user_id:
        await update.message.reply_text(
            f"⚠️ Имя «{escape(text)}» уже привязано к другому пользователю.\n"
            "Выберите другое имя или обратитесь к администратору.",
            parse_mode='HTML',
        )
        return REG_NAME

    link_initiator(text, user_id)
    await update.message.reply_text(
        f"✅ Вы привязаны как <b>{escape(text)}</b>.\n\n"
        "Теперь вы будете получать уведомления о выполнении ваших заявок.\n"
        "Используйте «➕ Добавить заявку» для создания заявки.",
        reply_markup=get_main_keyboard(user_id),
        parse_mode='HTML',
    )
    return ConversationHandler.END


async def run_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запускает анализ вручную (для обратной совместимости)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ У вас нет прав для этой команды.")
        return

    await update.message.reply_text("⏳ Запускаю анализ...")

    try:
        result = build_report(mode="active")
        await send_long_message(context, update.effective_chat.id, result, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка анализа: {e}", exc_info=True)
        await update.message.reply_text("❌ Ошибка при формировании отчёта. Попробуйте позже.")


async def scheduled_report(context: ContextTypes.DEFAULT_TYPE):
    """Автоматический ежедневный отчёт"""
    chat_id = context.job.chat_id
    try:
        result = build_report()
        await send_long_message(context, chat_id, result, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка автоотчёта: {e}", exc_info=True)
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Ошибка при формировании автоотчёта.",
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

    cols = int(get_setting("buttons_per_row_unit", "3"))
    keyboard = [units[i:i + cols] for i in range(0, len(units), cols)]
    keyboard.append(["❌ Отмена"])
    await update.message.reply_text(
        "📏 <b>Шаг 3/6:</b> Выберите единицу измерения:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode='HTML'
    )
    return UNIT


async def set_unit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет единицу измерения и запрашивает инициатора (или ставит автоматически)"""
    context.user_data['unit'] = update.message.text.strip()

    user_id = update.effective_user.id
    linked_name = get_initiator_by_tg_id(user_id)

    if linked_name:
        context.user_data['initiator'] = linked_name
        try:
            lists = get_all_lists()
            objects = lists.get("object", ["Солнечное", "Привилегия", "Не указан"])
        except Exception:
            objects = ["Солнечное", "Привилегия", "Не указан"]

        cols = int(get_setting("buttons_per_row_object", "2"))
        keyboard = [objects[i:i + cols] for i in range(0, len(objects), cols)]
        keyboard.append(["❌ Отмена"])
        await update.message.reply_text(
            f"👤 Инициатор: <b>{escape(linked_name)}</b> (автоматически)\n\n"
            "🏗️ <b>Шаг 5/6:</b> Выберите объект:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
            parse_mode='HTML',
        )
        return OBJECT

    try:
        lists = get_all_lists()
        initiators = lists.get("initiator", ["Алексей", "Анатолий", "Михаил", "Игорь", "Другое"])
    except Exception as e:
        logger.error(f"Ошибка загрузки списков: {e}")
        initiators = ["Алексей", "Анатолий", "Михаил", "Игорь", "Другое"]

    cols = int(get_setting("buttons_per_row_initiator", "4"))
    keyboard = [initiators[i:i + cols] for i in range(0, len(initiators), cols)]
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

    cols = int(get_setting("buttons_per_row_object", "2"))
    keyboard = [objects[i:i + cols] for i in range(0, len(objects), cols)]
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

    cols = int(get_setting("buttons_per_row_object", "2"))
    keyboard = [objects[i:i + cols] for i in range(0, len(objects), cols)]
    keyboard.append(["❌ Отмена"])
    await update.message.reply_text(
        "🏗️ <b>Шаг 5/6:</b> Выберите объект:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode='HTML'
    )
    return OBJECT


async def set_object(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет объект и запрашивает примечание"""
    obj = update.message.text.strip()

    if obj == "Другое":
        await update.message.reply_text(
            "✍️ Введите название объекта:",
            reply_markup=CANCEL_KEYBOARD,
            parse_mode='HTML'
        )
        return OBJECT_CUSTOM

    context.user_data['object'] = obj

    await update.message.reply_text(
        "📝 <b>Шаг 6/6:</b> Добавьте примечание (ссылки допустимы) или отправьте <code>-</code> для пропуска:",
        reply_markup=CANCEL_KEYBOARD,
        parse_mode='HTML'
    )
    return NOTES


async def set_object_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет кастомное название объекта и переходит к примечанию"""
    context.user_data['object'] = update.message.text.strip()

    await update.message.reply_text(
        "📝 <b>Шаг 6/6:</b> Добавьте примечание (ссылки допустимы) или отправьте <code>-</code> для пропуска:",
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
        f"📦 Наименование: <b>{escape(context.user_data['name'])}</b>\n"
        f"🔢 Количество: <code>{escape(context.user_data['quantity'])} {escape(context.user_data['unit'])}</code>\n"
        f"👤 Инициатор: {escape(context.user_data['initiator'])}\n"
        f"🏗️ Объект: {escape(context.user_data['object'])}\n"
        f"📝 Примечание: {escape(notes) if notes else '—'}\n\n"
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

    if text != "✅ Подтвердить":
        await update.message.reply_text(
            "⚠️ Используйте кнопки:\n"
            "✅ Подтвердить — сохранить заявку\n"
            "❌ Отмена — отменить",
        )
        return CONFIRM

    # Сохраняем заявку
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
            f"📦 Наименование: {escape(context.user_data['name'])}\n"
            f"🔢 Количество: {escape(context.user_data['quantity'])} {escape(context.user_data['unit'])}\n"
            f"👤 Инициатор: {escape(context.user_data['initiator'])}\n"
            f"🏗️ Объект: {escape(context.user_data['object'])}\n"
            f"📝 Примечание: {escape(context.user_data['notes']) if context.user_data['notes'] else '—'}"
        )

        await update.message.reply_text(
            summary,
            reply_markup=get_main_keyboard(user_id),
            parse_mode='HTML'
        )

    except Exception as e:
        logger.error(f"Ошибка при сохранении заявки: {e}", exc_info=True)
        await update.message.reply_text("❌ Ошибка при сохранении заявки. Попробуйте позже.")

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


# ===== ФИЛЬТР АНАЛИЗА =====
async def analysis_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает выбор фильтра анализа"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return ConversationHandler.END

    keyboard = [
        [
            InlineKeyboardButton("📋 Актуальные", callback_data="report:active"),
            InlineKeyboardButton("✅ Выполненные", callback_data="report:completed"),
        ],
    ]
    await update.message.reply_text(
        "📊 Какие заявки показать?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return 0


async def analysis_filter_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерирует отчёт по выбранному фильтру"""
    query = update.callback_query
    await query.answer()
    mode = query.data.split(":")[1]

    await query.edit_message_text("⏳ Формирую отчёт...")

    try:
        result = build_report(mode=mode)
        await query.message.reply_text(result, parse_mode='HTML', disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Ошибка формирования отчёта: {e}", exc_info=True)
        await query.message.reply_text("❌ Ошибка при формировании отчёта. Попробуйте позже.")

    return ConversationHandler.END


# ===== ЗАВЕРШЕНИЕ ЗАЯВКИ АДМИНИСТРАТОРОМ =====
async def complete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список активных заявок для завершения"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return ConversationHandler.END

    requests = get_active_requests()
    if not requests:
        await update.message.reply_text("✅ Нет активных заявок для завершения.")
        return ConversationHandler.END

    keyboard = []
    for r in requests:
        name = r["name"][:30]
        obj = r.get("object", "—")[:15]
        label = f"#{r['id']} {name} ({obj})"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"cr:{r['id']}")])

    await update.message.reply_text(
        "✅ <b>Завершение заявки</b>\n\nВыберите заявку:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML',
    )
    return COMPLETE_SELECT


async def complete_select_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает подтверждение завершения"""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    req_id = int(query.data.split(":")[1])

    requests = get_active_requests()
    selected = next((r for r in requests if r["id"] == req_id), None)
    if not selected:
        await query.edit_message_text("⚠️ Заявка не найдена или уже завершена.")
        return ConversationHandler.END

    context.user_data["complete_request"] = selected
    r = selected
    qty_text = f"{r['quantity']} {r['unit']}".strip() if r.get("quantity") else "—"

    text = (
        f"📋 <b>Заявка #{r['id']}</b>\n\n"
        f"📦 {escape(r['name'])}\n"
        f"🔢 {escape(qty_text)}\n"
        f"👤 {escape(r.get('initiator', '—'))}\n"
        f"🏗️ {escape(r.get('object', '—'))}\n\n"
        "Завершить?"
    )
    keyboard = [
        [
            InlineKeyboardButton("✅ Выполнено", callback_data="cr:confirm"),
            InlineKeyboardButton("❌ Отмена", callback_data="cr:cancel"),
        ],
    ]
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML',
    )
    return COMPLETE_CONFIRM


async def complete_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает заявку и отправляет уведомление"""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cr:cancel":
        context.user_data.pop("complete_request", None)
        await query.edit_message_text("❌ Отменено.")
        return ConversationHandler.END

    # data == "cr:confirm"
    r = context.user_data.get("complete_request")
    if not r:
        await query.edit_message_text("⚠️ Данные не найдены.")
        return ConversationHandler.END

    today = date.today()
    complete_request(r["id"], today)

    qty_text = f"{r['quantity']} {r['unit']}".strip() if r.get("quantity") else "—"
    notification = (
        f"✅ <b>Заявка выполнена</b>\n\n"
        f"📦 {escape(r['name'])}\n"
        f"🔢 {escape(qty_text)}\n"
        f"👤 {escape(r.get('initiator', '—'))}\n"
        f"🏗️ {escape(r.get('object', '—'))}\n"
        f"📅 Выполнено: {today.strftime('%d.%m')}"
    )

    await query.edit_message_text(notification, parse_mode='HTML')

    # Уведомление в общий чат
    try:
        await context.bot.send_message(
            chat_id=int(TELEGRAM_CHAT_ID),
            text=notification,
            parse_mode='HTML',
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить уведомление в чат: {e}")

    # Уведомление инициатору в ЛС
    initiator_name = r.get("initiator", "")
    if initiator_name:
        tg_id = get_initiator_tg_id(initiator_name)
        if tg_id:
            try:
                await context.bot.send_message(
                    chat_id=tg_id,
                    text=notification,
                    parse_mode='HTML',
                    disable_web_page_preview=True,
                )
            except Exception as e:
                logger.warning(f"Не удалось отправить ЛС инициатору {initiator_name}: {e}")

    context.user_data.pop("complete_request", None)
    return ConversationHandler.END


# ===== АДМИН-ПАНЕЛЬ: УПРАВЛЕНИЕ СПРАВОЧНИКАМИ =====
LIST_TYPE_LABELS = {
    "object": "🏗️ Объекты",
    "initiator": "👤 Исполнители",
    "unit": "📏 Единицы измерения",
}


async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в админ-панель настроек"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("🏗️ Объекты", callback_data="list:object")],
        [InlineKeyboardButton("👤 Исполнители", callback_data="list:initiator")],
        [InlineKeyboardButton("📏 Единицы измерения", callback_data="list:unit")],
        [InlineKeyboardButton("🔢 Кнопок в строке", callback_data="buttons")],
    ]
    await update.message.reply_text(
        "⚙️ <b>Настройки</b>\n\nВыберите раздел:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML',
    )
    return ADMIN_MENU


async def _show_main_settings(query):
    """Показывает главное меню настроек (редактирует сообщение)"""
    keyboard = [
        [InlineKeyboardButton("🏗️ Объекты", callback_data="list:object")],
        [InlineKeyboardButton("👤 Исполнители", callback_data="list:initiator")],
        [InlineKeyboardButton("📏 Единицы измерения", callback_data="list:unit")],
        [InlineKeyboardButton("🔢 Кнопок в строке", callback_data="buttons")],
    ]
    await query.edit_message_text(
        "⚙️ <b>Настройки</b>\n\nВыберите раздел:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML',
    )
    return ADMIN_MENU


async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора в главном меню настроек"""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "buttons":
        return await admin_buttons_show(update, context)

    if data == "back_main":
        return await _show_main_settings(query)

    # data == "list:..."
    list_type = data.split(":")[1]
    context.user_data["admin_list_type"] = list_type
    return await _show_list(update, context, list_type)


async def _show_list(update: Update, context: ContextTypes.DEFAULT_TYPE, list_type: str):
    """Показывает значения справочника с inline-кнопками"""
    query = update.callback_query
    lists = get_all_lists()
    values = lists.get(list_type, [])
    label = LIST_TYPE_LABELS.get(list_type, list_type)

    text = f"<b>{label}</b>\n\n"
    if values:
        text += "\n".join(f"• {escape(v)}" for v in values)
    else:
        text += "(пусто)"

    keyboard = []
    for v in values:
        if v == "Другое":
            continue
        safe_v = v[:50]  # Limit callback_data length
        keyboard.append([
            InlineKeyboardButton(f"✏️ {escape(v)}", callback_data=f"rename:{safe_v}"),
            InlineKeyboardButton(f"🗑", callback_data=f"del:{safe_v}"),
        ])
    keyboard.append([InlineKeyboardButton("➕ Добавить", callback_data="add")])

    bpr_key = f"buttons_per_row_{list_type}"
    cols = int(get_setting(bpr_key, "2"))
    keyboard.append([InlineKeyboardButton(f"🔢 В строке: {cols}", callback_data="set_bpr")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_main")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML',
    )
    return ADMIN_LIST_VIEW


async def admin_list_view_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий внутри просмотра справочника"""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    data = query.data
    list_type = context.user_data.get("admin_list_type", "object")

    if data == "add":
        await query.edit_message_text(
            f"✍️ Введите новое значение для <b>{LIST_TYPE_LABELS.get(list_type, list_type)}</b>:",
            parse_mode='HTML',
        )
        return ADMIN_ADD_VALUE

    if data.startswith("rename:"):
        old_value = data.split(":", 1)[1]
        context.user_data["admin_rename_old"] = old_value
        await query.edit_message_text(
            f"✏️ Текущее значение: <b>{escape(old_value)}</b>\n\nВведите новое название:",
            parse_mode='HTML',
        )
        return ADMIN_RENAME_NEW

    if data.startswith("del:"):
        value = data.split(":", 1)[1]
        keyboard = [
            [
                InlineKeyboardButton("✅ Да", callback_data=f"confirm_del:{value}"),
                InlineKeyboardButton("❌ Нет", callback_data="back_list"),
            ]
        ]
        await query.edit_message_text(
            f"🗑 Удалить <b>{escape(value)}</b>?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML',
        )
        return ADMIN_DELETE

    if data == "set_bpr":
        bpr_key = f"buttons_per_row_{list_type}"
        current = int(get_setting(bpr_key, "2"))
        keyboard = []
        for n in range(1, 7):
            marker = " ✅" if n == current else ""
            keyboard.append(InlineKeyboardButton(f"{n}{marker}", callback_data=f"bpr:{n}"))
        await query.edit_message_text(
            "🔢 Сколько кнопок в строке?",
            reply_markup=InlineKeyboardMarkup([keyboard]),
        )
        return ADMIN_BUTTONS_EDIT

    if data == "back_main":
        return await _show_main_settings(query)

    return ADMIN_LIST_VIEW


async def admin_rename_new_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет новое значение после переименования"""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    new_value = update.message.text.strip()
    old_value = context.user_data.get("admin_rename_old", "")
    list_type = context.user_data.get("admin_list_type", "object")

    if not new_value:
        await update.message.reply_text("❌ Значение не может быть пустым. Попробуйте ещё раз:")
        return ADMIN_RENAME_NEW

    success = rename_list_value(list_type, old_value, new_value)
    if success:
        await update.message.reply_text(f"✅ Переименовано: {escape(old_value)} → {escape(new_value)}")
    else:
        await update.message.reply_text("❌ Не удалось переименовать (возможно, дубликат).")

    return await _show_list_msg(update, context, list_type)


async def admin_delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение удаления"""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    data = query.data
    list_type = context.user_data.get("admin_list_type", "object")

    if data.startswith("confirm_del:"):
        value = data.split(":", 1)[1]
        delete_list_value(list_type, value)
        await query.answer(f"Удалено: {value}", show_alert=True)

    return await _show_list(update, context, list_type)


async def admin_add_value_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавляет новое значение в справочник"""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    new_value = update.message.text.strip()
    list_type = context.user_data.get("admin_list_type", "object")

    if not new_value:
        await update.message.reply_text("❌ Значение не может быть пустым. Попробуйте ещё раз:")
        return ADMIN_ADD_VALUE

    success = add_list_value(list_type, new_value)
    if success:
        await update.message.reply_text(f"✅ Добавлено: {escape(new_value)}")
    else:
        await update.message.reply_text(f"⚠️ Значение «{escape(new_value)}» уже существует.")

    return await _show_list_msg(update, context, list_type)


async def admin_buttons_edit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Устанавливает количество кнопок в строке"""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    data = query.data
    list_type = context.user_data.get("admin_list_type", "object")

    if data.startswith("bpr:"):
        n = int(data.split(":")[1])
        if 1 <= n <= 6:
            set_setting(f"buttons_per_row_{list_type}", str(n))
            await query.answer(f"Установлено: {n} в строке", show_alert=True)
        else:
            await query.answer("Значение должно быть от 1 до 6", show_alert=True)

    return await _show_list(update, context, list_type)


async def admin_buttons_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает общую настройку кнопок"""
    query = update.callback_query

    text = "🔢 <b>Количество кнопок в строке:</b>\n\n"
    for lt, label in LIST_TYPE_LABELS.items():
        cols = int(get_setting(f"buttons_per_row_{lt}", "2"))
        text += f"  {label}: <b>{cols}</b>\n"

    keyboard = [
        [InlineKeyboardButton("🏗️ Объекты", callback_data="list:object")],
        [InlineKeyboardButton("👤 Исполнители", callback_data="list:initiator")],
        [InlineKeyboardButton("📏 Единицы", callback_data="list:unit")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")],
    ]
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML',
    )
    return ADMIN_MENU


async def _show_list_msg(update: Update, context: ContextTypes.DEFAULT_TYPE, list_type: str):
    """Показывает справочник через обычное сообщение (не callback)"""
    lists = get_all_lists()
    values = lists.get(list_type, [])
    label = LIST_TYPE_LABELS.get(list_type, list_type)

    text = f"<b>{label}</b>\n\n"
    if values:
        text += "\n".join(f"• {escape(v)}" for v in values)
    else:
        text += "(пусто)"

    keyboard = []
    for v in values:
        if v == "Другое":
            continue
        safe_v = v[:50]  # Limit callback_data length
        keyboard.append([
            InlineKeyboardButton(f"✏️ {escape(v)}", callback_data=f"rename:{safe_v}"),
            InlineKeyboardButton(f"🗑", callback_data=f"del:{safe_v}"),
        ])
    keyboard.append([InlineKeyboardButton("➕ Добавить", callback_data="add")])

    bpr_key = f"buttons_per_row_{list_type}"
    cols = int(get_setting(bpr_key, "2"))
    keyboard.append([InlineKeyboardButton(f"🔢 В строке: {cols}", callback_data="set_bpr")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_main")])

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML',
    )
    return ADMIN_LIST_VIEW


async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выход из админ-панели"""
    context.user_data.clear()
    user_id = update.effective_user.id
    await update.message.reply_text(
        "❌ Настройки закрыты.",
        reply_markup=get_main_keyboard(user_id),
    )
    return ConversationHandler.END


# ===== ОБРАБОТКА ГЛАВНОГО МЕНЮ =====
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает кнопки главного меню"""
    text = update.message.text.strip()
    user_id = update.effective_user.id

    if text == "⛔ Выход":
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

    builder = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN)
    if SOCKS5_PROXY:
        proxy_url = SOCKS5_PROXY
        if not proxy_url.startswith("socks"):
            proxy_url = f"socks5://{proxy_url}"
        http_request = HTTPXRequest(proxy_url=proxy_url)
        builder = builder.request(http_request)
        masked = proxy_url.split("@")[-1] if "@" in proxy_url else proxy_url
        logger.info(f"Используется SOCKS5-прокси: {masked}")
    app = builder.build()

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
            OBJECT_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_object_custom)],
            NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_notes_and_save)],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_request)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            MessageHandler(filters.Regex('^❌ Отмена$'), cancel),
        ],
    )

    admin_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('Настройки'), admin_start)
        ],
        states={
            ADMIN_MENU: [CallbackQueryHandler(admin_menu_handler)],
            ADMIN_LIST_VIEW: [CallbackQueryHandler(admin_list_view_handler)],
            ADMIN_RENAME_NEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_rename_new_handler)],
            ADMIN_DELETE: [CallbackQueryHandler(admin_delete_handler)],
            ADMIN_ADD_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_value_handler)],
            ADMIN_BUTTONS_EDIT: [CallbackQueryHandler(admin_buttons_edit_handler)],
        },
        fallbacks=[
            CommandHandler('cancel', admin_cancel),
            MessageHandler(filters.Regex('^❌ Отмена$'), admin_cancel),
            MessageHandler(filters.Regex('Настройки'), admin_start),
        ],
    )

    analysis_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^📊 Анализ$'), analysis_start)
        ],
        states={
            0: [CallbackQueryHandler(analysis_filter_handler, pattern=r'^report:(active|completed)$')],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
        ],
    )

    complete_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^✅ Завершить заявку$'), complete_start)
        ],
        states={
            COMPLETE_SELECT: [CallbackQueryHandler(complete_select_handler, pattern=r'^cr:\d+$')],
            COMPLETE_CONFIRM: [CallbackQueryHandler(complete_confirm_handler, pattern=r'^cr:(confirm|cancel)$')],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            MessageHandler(filters.Regex('^❌ Отмена$'), cancel),
        ],
    )

    register_conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start)
        ],
        states={
            REG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_name)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
        ],
    )

    app.add_handler(register_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(analysis_handler)
    app.add_handler(complete_handler)
    app.add_handler(admin_handler)
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