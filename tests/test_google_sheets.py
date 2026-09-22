"""Тесты для google_sheets.py"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

import google_sheets
from google_sheets import (
    _get_google_client,
    load_google_sheet,
    load_initiators_from_team,
    add_row,
    clear_cache,
)


@pytest.fixture(autouse=True)
def reset_cache():
    """Сбрасывает кэш перед каждым тестом."""
    google_sheets._cache = {
        "df": None,
        "timestamp": None,
        "initiators": None,
        "initiators_timestamp": None,
        "lists": None,
        "lists_timestamp": None,
    }
    google_sheets._client_cache = None
    yield
    google_sheets._cache = {
        "df": None,
        "timestamp": None,
        "initiators": None,
        "initiators_timestamp": None,
    }
    google_sheets._client_cache = None


# ===== Тесты кэширования клиента =====

@patch("google_sheets.gspread")
@patch("google_sheets.Credentials")
def test_client_is_cached(mock_creds, mock_gspread):
    """Клиент создаётся один раз и кэшируется"""
    client1 = _get_google_client()
    client2 = _get_google_client()

    assert client1 is client2
    mock_creds.from_service_account_file.assert_called_once()
    mock_gspread.authorize.assert_called_once()


@patch("google_sheets.gspread")
@patch("google_sheets.Credentials")
def test_client_recreated_after_reset(mock_creds, mock_gspread):
    """После сброса кэша клиент создаётся заново"""
    _get_google_client()
    google_sheets._client_cache = None
    _get_google_client()

    assert mock_creds.from_service_account_file.call_count == 2
    assert mock_gspread.authorize.call_count == 2


# ===== Тесты load_google_sheet =====

@patch("google_sheets._get_google_client")
def test_load_google_sheet_fresh(mock_get_client):
    """Загружает данные из таблицы"""
    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = [
        ["Наименование", "Кол-во", "Ед. изм"],
        ["Кирпич", "100", "шт"],
        ["Цемент", "50", "кг"],
    ]
    mock_sheet = MagicMock()
    mock_sheet.worksheet.return_value = mock_ws
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_sheet
    mock_get_client.return_value = mock_client

    df = load_google_sheet(use_cache=False)

    assert len(df) == 2
    assert list(df.columns) == ["Наименование", "Кол-во", "Ед. изм"]
    assert df.iloc[0]["Наименование"] == "Кирпич"


@patch("google_sheets._get_google_client")
def test_load_google_sheet_uses_cache(mock_get_client):
    """Второй вызов использует кэш"""
    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = [
        ["Колонка"],
        ["Значение"],
    ]
    mock_sheet = MagicMock()
    mock_sheet.worksheet.return_value = mock_ws
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_sheet
    mock_get_client.return_value = mock_client

    load_google_sheet(use_cache=False)
    load_google_sheet(use_cache=True)

    # open_by_key вызывается только один раз (при первой загрузке)
    mock_client.open_by_key.assert_called_once()


@patch("google_sheets._get_google_client")
def test_load_google_sheet_cache_expired(mock_get_client):
    """После истечения TTL кэш обновляется"""
    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = [["Колонка"], ["Значение"]]
    mock_sheet = MagicMock()
    mock_sheet.worksheet.return_value = mock_ws
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_sheet
    mock_get_client.return_value = mock_client

    # Первая загрузка
    load_google_sheet(use_cache=False)

    # Искусственно устаревляем кэш
    google_sheets._cache["timestamp"] = datetime.now() - timedelta(seconds=999)

    # Вторая загрузка — должна обновить данные
    load_google_sheet(use_cache=True)

    assert mock_client.open_by_key.call_count == 2


@patch("google_sheets._get_google_client")
def test_load_google_sheet_empty_raises(mock_get_client):
    """Пустая таблица вызывает ValueError"""
    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = []
    mock_sheet = MagicMock()
    mock_sheet.worksheet.return_value = mock_ws
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_sheet
    mock_get_client.return_value = mock_client

    with pytest.raises(ValueError, match="пуста"):
        load_google_sheet(use_cache=False)


# ===== Тесты add_row =====

@patch("google_sheets._get_google_client")
def test_add_row(mock_get_client):
    """Строка добавляется и кэш инвалидируется"""
    mock_ws = MagicMock()
    mock_sheet = MagicMock()
    mock_sheet.worksheet.return_value = mock_ws
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_sheet
    mock_get_client.return_value = mock_client

    # Устанавливаем кэш, чтобы проверить инвалидацию
    google_sheets._cache["df"] = "stale"
    google_sheets._cache["timestamp"] = datetime.now()

    result = add_row(["Кирпич", "100", "шт"])

    assert result is True
    mock_ws.append_row.assert_called_once_with(
        ["Кирпич", "100", "шт"],
        value_input_option='USER_ENTERED'
    )
    assert google_sheets._cache["df"] is None
    assert google_sheets._cache["timestamp"] is None


@patch("google_sheets._get_google_client")
def test_add_row_error_propagates(mock_get_client):
    """Ошибка gspread пробрасывается наружу"""
    mock_ws = MagicMock()
    mock_ws.append_row.side_effect = Exception("API error")
    mock_sheet = MagicMock()
    mock_sheet.worksheet.return_value = mock_ws
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_sheet
    mock_get_client.return_value = mock_client

    with pytest.raises(Exception, match="API error"):
        add_row(["data"])


# ===== Тесты load_initiators_from_team =====

@patch("google_sheets._get_google_client")
def test_load_initiators(mock_get_client):
    """Загружает инициаторов из листа Team"""
    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = [
        ["Инициатор", "Объект"],
        ["Иван", "Солнечное"],
        ["Петр", "Привилегия"],
        ["Анна", "Солнечное"],
        ["Иван", ""],
    ]
    mock_sheet = MagicMock()
    mock_sheet.worksheet.return_value = mock_ws
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_sheet
    mock_get_client.return_value = mock_client

    initiators = load_initiators_from_team(use_cache=False)

    assert "Иван" in initiators
    assert "Петр" in initiators
    assert "Анна" in initiators
    assert "Другое" in initiators
    # Дубликат "Иван" должен быть убран
    assert initiators.count("Иван") == 1
    # "Другое" — последний элемент
    assert initiators[-1] == "Другое"


@patch("google_sheets._get_google_client")
def test_load_initiators_uses_cache(mock_get_client):
    """Повторный вызов использует кэш"""
    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = [
        ["Инициатор"],
        ["Иван"],
    ]
    mock_sheet = MagicMock()
    mock_sheet.worksheet.return_value = mock_ws
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_sheet
    mock_get_client.return_value = mock_client

    load_initiators_from_team(use_cache=False)
    load_initiators_from_team(use_cache=True)

    mock_client.open_by_key.assert_called_once()


@patch("google_sheets._get_google_client")
def test_load_initiators_error_returns_defaults(mock_get_client):
    """При ошибке возвращаются значения по умолчанию"""
    mock_get_client.side_effect = Exception("Network error")

    initiators = load_initiators_from_team(use_cache=False)

    assert initiators == ["Иван", "Петр", "Анна", "Другое"]


# ===== Тесты clear_cache =====

def test_clear_cache():
    """clear_cache обнуляет все поля кэша"""
    google_sheets._cache["df"] = "stale"
    google_sheets._cache["timestamp"] = datetime.now()
    google_sheets._cache["initiators"] = ["test"]
    google_sheets._cache["initiators_timestamp"] = datetime.now()

    clear_cache()

    assert google_sheets._cache["df"] is None
    assert google_sheets._cache["timestamp"] is None
    assert google_sheets._cache["initiators"] is None
    assert google_sheets._cache["initiators_timestamp"] is None
