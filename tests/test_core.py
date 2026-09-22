import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from datetime import datetime

from core import (
    clean_column_names,
    map_columns,
    get_active_tasks,
    format_task_html,
    build_report_html,
)
from utils import parse_date, validate_quantity


def test_clean_column_names():
    """Тест очистки названий колонок"""
    df = pd.DataFrame(columns=[" Наименование\n", "Кол-во ", "ЕД. ИЗМ"])
    df = clean_column_names(df)
    assert "наименование" in df.columns
    assert "кол-во" in df.columns
    assert "ед. изм" in df.columns


def test_parse_date_valid():
    """Тест парсинга корректных дат"""
    assert parse_date("15.05.2023").day == 15
    assert parse_date("2023-05-15").month == 5
    assert parse_date("05/15/2023").year == 2023


def test_parse_date_invalid():
    """Тест парсинга некорректных дат"""
    assert parse_date("не дата") is None
    assert parse_date("") is None
    assert parse_date(None) is None


def test_validate_quantity():
    """Тест валидации количества"""
    assert validate_quantity("10") is True
    assert validate_quantity("5.5") is True
    assert validate_quantity("5,5") is True
    assert validate_quantity("текст") is False
    assert validate_quantity("") is False


def test_map_columns_success():
    """Тест успешного маппинга колонок"""
    df = pd.DataFrame(columns=[
        "наименование", "кол-во", "ед. изм", "дата заявки",
        "дата выполнения", "инициатор", "статус", "объект", "примечания"
    ])
    cols = map_columns(df)
    assert cols["name"] == "наименование"
    assert cols["quantity"] == "кол-во"


def test_map_columns_missing():
    """Тест маппинга при отсутствии колонки"""
    df = pd.DataFrame(columns=["неизвестная колонка"])
    with pytest.raises(ValueError):
        map_columns(df)


@patch("core.load_google_sheet")
def test_get_active_tasks(mock_load):
    """Тест фильтрации активных задач"""
    df = pd.DataFrame({
        "наименование": ["Товар 1", "Товар 2"],
        "кол-во": ["10", "20"],
        "ед. изм": ["шт", "кг"],
        "дата заявки": ["01.01.2023", "02.01.2023"],
        "дата выполнения": ["", "05.01.2023"],
        "инициатор": ["Иван", "Петр"],
        "статус": ["", ""],
        "объект": ["Объект 1", "Объект 2"],
        "примечания": ["", ""],
    })

    cols = {
        "name": "наименование",
        "quantity": "кол-во",
        "unit": "ед. изм",
        "request_date": "дата заявки",
        "done_date": "дата выполнения",
        "initiator": "инициатор",
        "status": "статус",
        "object": "объект",
        "notes": "примечания",
    }

    active = get_active_tasks(df, cols)
    assert len(active) == 1
    assert active.iloc[0]["наименование"] == "Товар 1"


def test_format_task_html():
    """Тест форматирования задачи в HTML"""
    cols = {
        "name": "наименование",
        "quantity": "кол-во",
        "unit": "ед. изм",
        "request_date": "дата заявки",
        "object": "объект",
        "initiator": "инициатор",
        "notes": "примечания",
    }

    row = pd.Series({
        "наименование": "Кирпич",
        "кол-во": "1000",
        "ед. изм": "шт",
        "дата заявки": datetime(2023, 1, 1).date(),
        "объект": "Стройка А",
        "инициатор": "Иван",
        "примечания": "срочно",
    })

    today = datetime(2023, 1, 5).date()
    result = format_task_html(row, cols, today)

    assert "<b>Кирпич</b>" in result
    assert "1000 шт" in result
    assert "Стройка А" in result
    assert "Иван" in result


def test_build_report_empty():
    """Тест построения отчёта с пустыми данными"""
    cols = {
        "name": "н", "quantity": "к", "unit": "е",
        "object": "о", "request_date": "д",
        "notes": "п", "done_date": "в"
    }

    df_empty = pd.DataFrame(columns=cols.values())
    report = build_report_html(df_empty, cols)

    assert "активных заявок нет" in report
    assert "Всего активных: <b>0</b>" in report