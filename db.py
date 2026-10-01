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

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS initiator_users (
    initiator_name TEXT PRIMARY KEY,
    telegram_id INTEGER NOT NULL,
    object_name TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS request_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES requests(id),
    file_id TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_requests_active ON requests(done_date, request_date);
CREATE INDEX IF NOT EXISTS idx_requests_object ON requests(object);
CREATE INDEX IF NOT EXISTS idx_request_photos_req ON request_photos(request_id);
"""

# Значения настроек по умолчанию
_DEFAULT_SETTINGS = {
    "buttons_per_row_object": "2",
    "buttons_per_row_initiator": "4",
    "buttons_per_row_unit": "3",
}

# Значения по умолчанию для справочников
_DEFAULT_LISTS = {
    "initiator": ["Алексей", "Анатолий", "Михаил", "Игорь"],
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

        # Заполняем настройки по умолчанию
        for key, value in _DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
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
            (
                name,
                quantity,
                unit,
                request_date.isoformat(),
                initiator,
                object_name,
                notes,
            ),
        )
        row_id = cursor.lastrowid
    logger.info(f"Заявка #{row_id} добавлена: {name}")
    return row_id


def add_request_with_photos(
    name: str,
    quantity: float,
    unit: str,
    request_date: date,
    initiator: str,
    object_name: str,
    notes: str = "",
    photo_file_ids: Optional[List[str]] = None,
) -> int:
    """Добавляет заявку и фото в одной транзакции. Возвращает ID заявки."""
    with get_conn() as conn:
        cursor = conn.execute(
            """INSERT INTO requests
               (name, quantity, unit, request_date, initiator, object, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                name,
                quantity,
                unit,
                request_date.isoformat(),
                initiator,
                object_name,
                notes,
            ),
        )
        row_id = cursor.lastrowid
        if photo_file_ids:
            conn.executemany(
                "INSERT INTO request_photos (request_id, file_id) VALUES (?, ?)",
                [(row_id, fid) for fid in photo_file_ids],
            )
    logger.info(
        f"Заявка #{row_id} добавлена: {name} (фото: {len(photo_file_ids or [])})"
    )
    return row_id


def get_active_requests() -> List[dict]:
    """Возвращает активные заявки (без done_date), отсортированные по объекту."""
    with get_conn() as conn:
        rows = conn.execute("""SELECT id, name, quantity, unit, request_date, done_date,
                      initiator, status, object, notes
               FROM requests
               WHERE done_date IS NULL AND request_date IS NOT NULL
               ORDER BY object, request_date""").fetchall()
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

    # Добавляем "Другое" в объекты
    if "object" in result and "Другое" not in result["object"]:
        result["object"].append("Другое")

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


def rename_list_value(list_type: str, old_value: str, new_value: str) -> bool:
    """Переименовывает значение в справочнике. Возвращает True если успешно."""
    with get_conn() as conn:
        try:
            conn.execute(
                "UPDATE lists SET value = ? WHERE list_type = ? AND value = ?",
                (new_value, list_type, old_value),
            )
            return conn.total_changes > 0
        except sqlite3.IntegrityError:
            return False


def delete_list_value(list_type: str, value: str) -> bool:
    """Удаляет значение из справочника. Возвращает True если удалено."""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM lists WHERE list_type = ? AND value = ?",
            (list_type, value),
        )
        return conn.total_changes > 0


def get_setting(key: str, default: str = "") -> str:
    """Возвращает значение настройки."""
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default
    except Exception as e:
        logger.warning(f"get_setting({key!r}) ошибка: {e}")
        return default


def set_setting(key: str, value: str):
    """Устанавливает значение настройки."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )


def complete_request(request_id: int, done_date: date) -> Optional[dict]:
    """Отмечает заявку как выполненную. Возвращает данные заявки или None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM requests WHERE id = ?", (request_id,)
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE requests SET done_date = ? WHERE id = ?",
            (done_date.isoformat(), request_id),
        )
    result = dict(row)
    result["done_date"] = done_date.isoformat()
    logger.info(f"Заявка #{request_id} завершена")
    return result


def get_completed_requests(limit: int = 50) -> List[dict]:
    """Возвращает завершённые заявки (есть done_date), отсортированные по дате завершения."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, name, quantity, unit, request_date, done_date,
                      initiator, status, object, notes
               FROM requests
               WHERE done_date IS NOT NULL
               ORDER BY done_date DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ===== Фото к заявкам =====


def add_request_photo(request_id: int, file_id: str):
    """Сохраняет file_id фото для заявки."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO request_photos (request_id, file_id) VALUES (?, ?)",
            (request_id, file_id),
        )


def get_request_photos(request_id: int) -> List[str]:
    """Возвращает список file_id фото для заявки."""
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT file_id FROM request_photos WHERE request_id = ? ORDER BY id",
                (request_id,),
            ).fetchall()
        return [row["file_id"] for row in rows]
    except Exception as e:
        logger.warning(f"get_request_photos({request_id}) ошибка: {e}")
        return []


def get_photo_counts(request_ids: List[int]) -> Dict[int, int]:
    """Возвращает {request_id: photo_count} для списка заявок."""
    if not request_ids:
        return {}
    try:
        result = {}
        # SQLite лимит на placeholders — 999, разбиваем на батчи
        batch_size = 900
        for i in range(0, len(request_ids), batch_size):
            batch = request_ids[i : i + batch_size]
            placeholders = ",".join("?" * len(batch))
            with get_conn() as conn:
                rows = conn.execute(
                    f"""SELECT request_id, COUNT(*) as cnt
                        FROM request_photos
                        WHERE request_id IN ({placeholders})
                        GROUP BY request_id""",
                    batch,
                ).fetchall()
            result.update({row["request_id"]: row["cnt"] for row in rows})
        return result
    except Exception as e:
        logger.warning(f"get_photo_counts ошибка: {e}")
        return {}


# ===== Привязка инициаторов к Telegram =====


def link_initiator(initiator_name: str, telegram_id: int):
    """Привязывает инициатора к Telegram-ID."""
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO initiator_users (initiator_name, telegram_id)
               VALUES (?, ?)
               ON CONFLICT(initiator_name) DO UPDATE SET telegram_id = excluded.telegram_id""",
            (initiator_name, telegram_id),
        )
    logger.info(f"Инициатор «{initiator_name}» привязан к tg_id={telegram_id}")


def get_initiator_tg_id(initiator_name: str) -> Optional[int]:
    """Возвращает telegram_id инициатора или None."""
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT telegram_id FROM initiator_users WHERE initiator_name = ?",
                (initiator_name,),
            ).fetchone()
        return row["telegram_id"] if row else None
    except Exception as e:
        logger.warning(f"get_initiator_tg_id({initiator_name!r}) ошибка: {e}")
        return None


def get_initiator_by_tg_id(telegram_id: int) -> Optional[str]:
    """Возвращает имя инициатора по telegram_id или None."""
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT initiator_name FROM initiator_users WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
        return row["initiator_name"] if row else None
    except Exception as e:
        logger.warning(f"get_initiator_by_tg_id({telegram_id}) ошибка: {e}")
        return None


def get_all_initiator_links() -> Dict[str, int]:
    """Возвращает все привязки {имя: telegram_id}."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT initiator_name, telegram_id FROM initiator_users"
        ).fetchall()
    return {row["initiator_name"]: row["telegram_id"] for row in rows}
