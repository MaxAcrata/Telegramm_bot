"""Тесты для bot.py"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

from bot import (
    is_admin,
    get_main_keyboard,
    cancel,
    start_add_request,
    set_name,
    set_quantity,
    set_unit,
    set_notes_and_save,
    confirm_request,
    NAME, QUANTITY, UNIT, INITIATOR, OBJECT, NOTES, CONFIRM,
    CANCEL_KEYBOARD,
)
from telegram.ext import ConversationHandler


# ===== Вспомогательные функции =====

def make_update(text: str = None, user_id: int = 123, first_name: str = "Тест"):
    """Создаёт мок Update"""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.first_name = first_name
    if text is not None:
        update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def make_context():
    """Создаёт мок Context"""
    context = MagicMock()
    context.user_data = {}
    context.bot.send_message = AsyncMock()
    return context


# ===== Тесты вспомогательных функций =====

@patch("bot.ADMIN_IDS", [111, 222])
def test_is_admin_true():
    assert is_admin(111) is True


@patch("bot.ADMIN_IDS", [111, 222])
def test_is_admin_false():
    assert is_admin(999) is False


@patch("bot.ADMIN_IDS", [111])
def test_get_main_keyboard_admin():
    kb = get_main_keyboard(111)
    text = str(kb)
    assert "📊 Анализ" in text
    assert "🔄 Обновить кэш" in text
    assert "➕ Добавить заявку" in text


@patch("bot.ADMIN_IDS", [111])
def test_get_main_keyboard_user():
    kb = get_main_keyboard(999)
    text = str(kb)
    assert "➕ Добавить заявку" in text
    assert "📊 Анализ" not in text


# ===== Тесты отмены =====

@pytest.mark.asyncio
@patch("bot.ADMIN_IDS", [123])
async def test_cancel_clears_user_data():
    update = make_update(user_id=123)
    context = make_context()
    context.user_data["name"] = "test"

    result = await cancel(update, context)

    assert result == ConversationHandler.END
    assert context.user_data == {}
    update.message.reply_text.assert_called_once()
    assert "отменена" in update.message.reply_text.call_args[0][0].lower()


# ===== Тесты начала диалога =====

@pytest.mark.asyncio
@patch("bot.ADMIN_IDS", [123])
async def test_start_add_request():
    update = make_update(user_id=123)
    context = make_context()

    result = await start_add_request(update, context)

    assert result == NAME
    assert context.user_data == {}
    reply_text = update.message.reply_text.call_args
    assert "Шаг 1/6" in reply_text[0][0]


# ===== Тесты шагов диалога =====

@pytest.mark.asyncio
async def test_set_name():
    update = make_update(text="Кирпич")
    context = make_context()

    result = await set_name(update, context)

    assert result == QUANTITY
    assert context.user_data["name"] == "Кирпич"
    assert "Шаг 2/6" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_set_quantity_valid():
    update = make_update(text="10")
    context = make_context()

    result = await set_quantity(update, context)

    assert result == UNIT
    assert context.user_data["quantity"] == "10"
    assert "Шаг 3/6" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_set_quantity_invalid():
    update = make_update(text="abc")
    context = make_context()

    result = await set_quantity(update, context)

    assert result == QUANTITY
    assert "quantity" not in context.user_data
    assert "число" in update.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
@patch("bot.load_initiators_from_team", return_value=["Иван", "Петр", "Другое"])
async def test_set_unit(mock_load):
    update = make_update(text="шт")
    context = make_context()

    result = await set_unit(update, context)

    assert result == INITIATOR
    assert context.user_data["unit"] == "шт"
    mock_load.assert_called_once()


@pytest.mark.asyncio
@patch("bot.load_initiators_from_team", side_effect=Exception("error"))
async def test_set_unit_fallback(mock_load):
    update = make_update(text="кг")
    context = make_context()

    result = await set_unit(update, context)

    assert result == INITIATOR
    # Проверяем, что fallback-инициаторы в клавиатуре
    kb_text = str(update.message.reply_text.call_args)
    assert "Иван" in kb_text


# ===== Тесты подтверждения =====

@pytest.mark.asyncio
async def test_set_notes_shows_confirmation():
    update = make_update(text="Срочно")
    context = make_context()
    context.user_data = {
        "name": "Кирпич", "quantity": "100", "unit": "шт",
        "initiator": "Иван", "object": "Стройка"
    }

    result = await set_notes_and_save(update, context)

    assert result == CONFIRM
    assert context.user_data["notes"] == "Срочно"
    reply_text = update.message.reply_text.call_args[0][0]
    assert "Проверьте заявку" in reply_text
    assert "Кирпич" in reply_text


@pytest.mark.asyncio
async def test_set_notes_dash_becomes_empty():
    update = make_update(text="-")
    context = make_context()
    context.user_data = {
        "name": "Тест", "quantity": "1", "unit": "шт",
        "initiator": "Иван", "object": "Объект"
    }

    await set_notes_and_save(update, context)

    assert context.user_data["notes"] == ""


@pytest.mark.asyncio
@patch("bot.add_row")
@patch("bot.ADMIN_IDS", [123])
async def test_confirm_request_saves(mock_add_row):
    update = make_update(text="✅ Подтвердить", user_id=123)
    context = make_context()
    context.user_data = {
        "name": "Кирпич", "quantity": "100", "unit": "шт",
        "initiator": "Иван", "object": "Стройка", "notes": "Срочно"
    }

    result = await confirm_request(update, context)

    assert result == ConversationHandler.END
    mock_add_row.assert_called_once()
    row = mock_add_row.call_args[0][0]
    assert row[0] == "Кирпич"
    assert row[1] == "100"
    assert row[5] == "Иван"
    assert row[8] == "Срочно"
    # Проверяем, что user_data очищен
    assert context.user_data == {}


@pytest.mark.asyncio
@patch("bot.ADMIN_IDS", [123])
async def test_confirm_request_cancel():
    update = make_update(text="❌ Отмена", user_id=123)
    context = make_context()
    context.user_data = {"name": "Кирпич"}

    result = await confirm_request(update, context)

    assert result == ConversationHandler.END
    assert context.user_data == {}
    reply_text = update.message.reply_text.call_args[0][0]
    assert "отменена" in reply_text.lower()


@pytest.mark.asyncio
@patch("bot.add_row", side_effect=Exception("API error"))
@patch("bot.ADMIN_IDS", [123])
async def test_confirm_request_error(mock_add_row):
    update = make_update(text="✅ Подтвердить", user_id=123)
    context = make_context()
    context.user_data = {
        "name": "Кирпич", "quantity": "100", "unit": "шт",
        "initiator": "Иван", "object": "Стройка", "notes": ""
    }

    result = await confirm_request(update, context)

    assert result == ConversationHandler.END
    reply_text = update.message.reply_text.call_args[0][0]
    assert "ошибка" in reply_text.lower()
    assert context.user_data == {}
