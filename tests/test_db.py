"""Тесты для db.py"""
import pytest
import tempfile
import os
from datetime import date
from unittest.mock import patch

import db
from db import get_conn, init_db, add_request, get_active_requests, get_all_lists, add_list_value


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    """Создаёт временную БД для каждого теста."""
    db_path = str(tmp_path / "test.db")
    with patch.object(db, "DB_PATH", db_path):
        init_db()
        yield db_path


def test_init_db_creates_tables():
    """Таблицы создаются при инициализации"""
    with get_conn() as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "requests" in tables
        assert "lists" in tables


def test_init_db_populates_defaults():
    """Справочники заполняются значениями по умолчанию"""
    lists = get_all_lists()
    assert "initiator" in lists
    assert "object" in lists
    assert "unit" in lists
    assert "шт" in lists["unit"]
    assert "Другое" in lists["initiator"]


def test_add_request():
    """Заявка добавляется и возвращается"""
    row_id = add_request(
        name="Кирпич",
        quantity=100.0,
        unit="шт",
        request_date=date(2025, 1, 15),
        initiator="Иван",
        object_name="Стройка",
        notes="срочно",
    )
    assert row_id > 0

    active = get_active_requests()
    assert len(active) == 1
    assert active[0]["name"] == "Кирпич"
    assert active[0]["quantity"] == 100.0
    assert active[0]["initiator"] == "Иван"


def test_get_active_requests_filters_done():
    """Завершённые заявки не возвращаются"""
    add_request("A", 1, "шт", date(2025, 1, 1), "И", "О")
    add_request("B", 2, "кг", date(2025, 1, 2), "И", "О")

    # Завершаем первую заявку
    with get_conn() as conn:
        conn.execute(
            "UPDATE requests SET done_date = ? WHERE name = ?",
            (date(2025, 1, 5).isoformat(), "A"),
        )

    active = get_active_requests()
    assert len(active) == 1
    assert active[0]["name"] == "B"


def test_get_active_requests_sorted_by_object():
    """Заявки сортируются по объекту"""
    add_request("A", 1, "шт", date(2025, 1, 1), "И", "Б-объект")
    add_request("B", 2, "кг", date(2025, 1, 2), "И", "А-объект")

    active = get_active_requests()
    assert active[0]["object"] == "А-объект"
    assert active[1]["object"] == "Б-объект"


def test_get_all_lists():
    """Справочники возвращаются корректно"""
    lists = get_all_lists()
    assert isinstance(lists, dict)
    assert "Алексей" in lists["initiator"]
    assert "шт" in lists["unit"]


def test_add_list_value():
    """Новое значение добавляется в справочник"""
    result = add_list_value("object", "Новый объект")
    assert result is True

    lists = get_all_lists()
    assert "Новый объект" in lists["object"]


def test_add_list_value_duplicate():
    """Дубликат не добавляется"""
    add_list_value("object", "Тест")
    result = add_list_value("object", "Тест")
    assert result is False
