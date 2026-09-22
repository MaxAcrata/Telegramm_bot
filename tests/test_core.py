"""Тесты для core.py"""
import pytest
from datetime import date
from unittest.mock import patch

from core import format_task_html, build_report


def test_format_task_html():
    """Тест форматирования задачи в HTML"""
    task = {
        "name": "Кирпич",
        "quantity": 1000.0,
        "unit": "шт",
        "request_date": "2023-01-01",
        "object": "Стройка А",
        "initiator": "Иван",
        "notes": "срочно",
    }

    today = date(2023, 1, 5)
    result = format_task_html(task, today)

    assert "<b>Кирпич</b>" in result
    assert "1000.0 шт" in result
    assert "Стройка А" in result
    assert "Иван" in result
    assert "01.01.2023" in result


def test_format_task_html_overdue():
    """Просроченная задача показывает предупреждение"""
    task = {
        "name": "Тест",
        "quantity": 1.0,
        "unit": "шт",
        "request_date": "2023-01-01",
        "object": "О",
        "initiator": "И",
        "notes": "",
    }

    today = date(2023, 1, 10)
    result = format_task_html(task, today)

    assert "Просрочено" in result
    assert "🔴" in result


def test_format_task_html_ordered():
    """Заказанная задача показывает жёлтый индикатор"""
    task = {
        "name": "Тест",
        "quantity": 1.0,
        "unit": "шт",
        "request_date": "2023-01-01",
        "object": "О",
        "initiator": "И",
        "notes": "заказ оформлен",
    }

    today = date(2023, 1, 2)
    result = format_task_html(task, today)

    assert "🟡" in result


@patch("core.get_active_requests")
def test_build_report_empty(mock_get):
    """Пустой отчёт"""
    mock_get.return_value = []

    report = build_report(save_to_file=False)

    assert "активных заявок нет" in report
    assert "Всего активных: <b>0</b>" in report


@patch("core.get_active_requests")
def test_build_report_with_tasks(mock_get):
    """Отчёт с задачами"""
    mock_get.return_value = [
        {
            "name": "Кирпич", "quantity": 100.0, "unit": "шт",
            "request_date": "2023-01-01", "object": "Стройка",
            "initiator": "Иван", "notes": "", "done_date": None, "status": "", "id": 1,
        },
        {
            "name": "Цемент", "quantity": 50.0, "unit": "кг",
            "request_date": "2023-01-01", "object": "Стройка",
            "initiator": "Петр", "notes": "заказ", "done_date": None, "status": "", "id": 2,
        },
    ]

    report = build_report(save_to_file=False)

    assert "Всего активных: <b>2</b>" in report
    assert "Заказано: <b>1</b>" in report
    assert "Не заказано: <b>1</b>" in report
    assert "Кирпич" in report
    assert "Цемент" in report


@patch("core.get_active_requests")
def test_build_report_overdue_section(mock_get):
    """Раздел просроченных заявок по инициаторам"""
    mock_get.return_value = [
        {
            "name": "Старая заявка", "quantity": 1.0, "unit": "шт",
            "request_date": "2020-01-01", "object": "О",
            "initiator": "Иван", "notes": "", "done_date": None, "status": "", "id": 1,
        },
    ]

    report = build_report(save_to_file=False)

    assert "ПРОСРОЧЕННЫЕ ЗАЯВКИ" in report
    assert "Иван" in report
