import logging
import sqlite3
from datetime import datetime, date
from typing import Optional, List, Dict
from contextlib import contextmanager

from config import DB_PATH

logger = logging.getLogger(__name__)

# ===== Схема БД =====
_SCHEMA = """
CREATE TABLE IF NOT EXISTS lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_type TEXT NOT NULL,
    value TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    UNIQUE(list_type, value)
);

CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    quantity REAL,
    unit TEXT,
    request_date DATE NOT NULL,
    done_date DATE,
    initiator TEXT DEFAULT '',
    status TEXT DEFAULT '',
    object TEXT DEFAULT '',
    notes TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_requests_active ON requests(done_date, request_date);
CREATE INDEX IF NOT EXISTS idx_requests_object ON requests(object);
"""

# Значения по умолчанию для справочников
_DEFAULT_LISTS = {
    "initiator": ["Иван", "Петр", "Анна"],
    "object": ["Солнечное", "Привилегия"],
    "unit": ["шт", "кг", "л", "м2", "м3", "лист", "м.п.", "комп"],
}


@contextmanager
def get_conn():
    """Контекстный менеджер для соединения с БД."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Инициализирует БД: создаёт таблицы и заполняет справочники по умолчанию."""
    with get_conn() as conn:
        conn.executescript(_SCHEMA)

        # Заполняем справочники, если пустые
        for list_type, values in _DEFAULT_LISTS.items():
            for i, value in enumerate(values):
                conn.execute(
                    "INSERT OR IGNORE INTO lists (list_type, value, sort_order) VALUES (?, ?, ?)",
                    (list_type, value, i),
                )
    logger.info(f"БД инициализирована: {DB_PATH}")


# ===== Запросы (requests) =====

def add_request(
    name: str,
    quantity: float,
    unit: str,
    request_date: date,
    initiator: str,
    object_name: str,
    notes: str = "",
) -> int:
    """Добавляет заявку и возвращает её ID."""
    with get_conn() as conn:
        cursor = conn.execute(
            """INSERT INTO requests
               (name, quantity, unit, request_date, initiator, object, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (name, quantity, unit, request_date.isoformat(), initiator, object_name, notes),
        )
        row_id = cursor.lastrowid
    logger.info(f"Заявка #{row_id} добавлена: {name}")
    return row_id


def get_active_requests() -> List[dict]:
    """Возвращает активные заявки (без done_date), отсортированные по объекту."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, name, quantity, unit, request_date, done_date,
                      initiator, status, object, notes
               FROM requests
               WHERE done_date IS NULL AND request_date IS NOT NULL
               ORDER BY object, request_date"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_lists() -> Dict[str, List[str]]:
    """Возвращает все справочники в виде {тип: [значения]}."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT list_type, value FROM lists ORDER BY sort_order"
        ).fetchall()

    result = {}
    for row in rows:
        lt = row["list_type"]
        if lt not in result:
            result[lt] = []
        result[lt].append(row["value"])

    # Добавляем "Другое" в инициаторы
    if "initiator" in result and "Другое" not in result["initiator"]:
        result["initiator"].append("Другое")

    # Заполняем пропущенные типы значениями по умолчанию
    for lt, defaults in _DEFAULT_LISTS.items():
        if lt not in result:
            result[lt] = defaults

    return result


def add_list_value(list_type: str, value: str) -> bool:
    """Добавляет значение в справочник. Возвращает True если добавлено."""
    with get_conn() as conn:
        try:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) FROM lists WHERE list_type = ?",
                (list_type,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO lists (list_type, value, sort_order) VALUES (?, ?, ?)",
                (list_type, value, max_order + 1),
            )
            return True
        except sqlite3.IntegrityError:
            return False
