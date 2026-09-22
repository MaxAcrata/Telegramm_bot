import logging
from datetime import datetime
from typing import Optional, List
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

from config import (
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_SHEET_ID,
    GOOGLE_SHEET_NAME,
    CACHE_TTL,
)

logger = logging.getLogger(__name__)

# ===== КЭШИРОВАНИЕ =====
_cache = {
    "df": None,
    "timestamp": None,
    "initiators": None,
    "initiators_timestamp": None,
    "lists": None,
    "lists_timestamp": None,
}


_client_cache = None


def _get_google_client():
    """Возвращает авторизованный клиент Google Sheets (с кэшированием)."""
    global _client_cache
    if _client_cache is not None:
        return _client_cache
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_FILE,
        scopes=scopes
    )
    _client_cache = gspread.authorize(credentials)
    return _client_cache


def load_google_sheet(use_cache: bool = True) -> pd.DataFrame:
    """
    Загружает Google таблицу с кэшированием.

    Args:
        use_cache: Использовать ли кэш (по умолчанию True)

    Returns:
        DataFrame с данными таблицы
    """
    now = datetime.now()

    # Проверяем кэш
    if use_cache and _cache["df"] is not None and _cache["timestamp"]:
        age = (now - _cache["timestamp"]).total_seconds()
        if age < CACHE_TTL:
            logger.info(f"Используем кэш (возраст: {age:.0f}с)")
            return _cache["df"].copy()

    # Загружаем свежие данные
    logger.info("Загрузка данных из Google Sheets...")
    try:
        client = _get_google_client()
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        worksheet = sheet.worksheet(GOOGLE_SHEET_NAME)

        data = worksheet.get_all_values()
        if not data:
            raise ValueError("Таблица пуста")

        df = pd.DataFrame(data[1:], columns=data[0])

        # Обновляем кэш
        _cache["df"] = df.copy()
        _cache["timestamp"] = now

        logger.info(f"Загружено {len(df)} строк")
        return df

    except Exception as e:
        logger.error(f"Ошибка загрузки таблицы: {e}")
        raise


def _extract_unique(values: list) -> list:
    """Извлекает уникальные непустые значения из списка, пропуская заголовок."""
    cleaned = [
        v.strip()
        for v in values[1:]  # Пропускаем заголовок (первую строку)
        if v and v.strip()
    ]
    return list(dict.fromkeys(cleaned))


# Маппинг заголовков колонок листа Team на ключи списков
_TEAM_COLUMN_MAP = {
    "инициатор": "initiators",
    "объект": "objects",
    "ед. изм": "units",
    "единица": "units",
    "наименование": "names",
    "статус": "statuses",
}

# Значения по умолчанию, если лист Team недоступен
_TEAM_DEFAULTS = {
    "initiators": ["Иван", "Петр", "Анна", "Другое"],
    "objects": ["Солнечное", "Привилегия", "Не указан"],
    "units": ["шт", "кг", "л", "м2", "м3", "лист", "м.п.", "комп"],
}


def load_lists_from_team(use_cache: bool = True) -> dict:
    """
    Загружает все списки из листа Team.
    Каждая колонка = отдельный список. Заголовок первой строки определяет тип.

    Returns:
        Словарь {ключ: [значения]}, например:
        {"initiators": ["Иван", ...], "objects": ["Солнечное", ...], "units": ["шт", ...]}
    """
    cache_key = "lists"
    ts_key = "lists_timestamp"

    now = datetime.now()

    if use_cache and _cache[cache_key] is not None and _cache[ts_key]:
        age = (now - _cache[ts_key]).total_seconds()
        if age < CACHE_TTL:
            logger.info(f"Используем кэш списков Team (возраст: {age:.0f}с)")
            return _cache[cache_key].copy()

    logger.info("Загрузка списков из листа Team...")
    try:
        client = _get_google_client()
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        worksheet = sheet.worksheet("Team")

        all_values = worksheet.get_all_values()
        if not all_values or len(all_values) < 2:
            logger.warning("Лист Team пуст или содержит только заголовки")
            return _TEAM_DEFAULTS.copy()

        headers = all_values[0]
        result = {}

        for col_idx, header in enumerate(headers):
            header_lower = header.strip().lower()
            # Определяем ключ по заголовку
            list_key = None
            for pattern, key in _TEAM_COLUMN_MAP.items():
                if pattern in header_lower:
                    list_key = key
                    break

            if not list_key:
                continue

            # Собираем значения колонки
            col_values = [row[col_idx] if col_idx < len(row) else "" for row in all_values]
            unique = _extract_unique(col_values)

            if unique:
                result[list_key] = unique
                logger.info(f"  {header} → {list_key}: {len(unique)} значений")

        # Добавляем "Другое" в инициаторы, если его нет
        if "initiators" in result and "Другое" not in result["initiators"]:
            result["initiators"].append("Другое")

        # Заполняем пропущенные ключи значениями по умолчанию
        for key, default in _TEAM_DEFAULTS.items():
            if key not in result:
                result[key] = default
                logger.info(f"  {key}: используется значение по умолчанию")

        _cache[cache_key] = result.copy()
        _cache[ts_key] = now

        return result

    except Exception as e:
        logger.error(f"Ошибка загрузки списков из Team: {e}")
        return _TEAM_DEFAULTS.copy()


def load_initiators_from_team(use_cache: bool = True) -> List[str]:
    """Загружает список инициаторов из листа Team (обёртка над load_lists_from_team)."""
    lists = load_lists_from_team(use_cache=use_cache)
    return lists.get("initiators", _TEAM_DEFAULTS["initiators"])


def add_row(values: list) -> bool:
    """
    Добавляет строку в конец таблицы.

    Args:
        values: Список значений для новой строки

    Returns:
        True в случае успеха
    """
    try:
        client = _get_google_client()
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        worksheet = sheet.worksheet(GOOGLE_SHEET_NAME)

        worksheet.append_row(values, value_input_option='USER_ENTERED')

        # Инвалидируем кэш
        _cache["df"] = None
        _cache["timestamp"] = None

        logger.info("Строка успешно добавлена")
        return True

    except Exception as e:
        logger.error(f"Ошибка добавления строки: {e}")
        raise


def clear_cache():
    """Очищает весь кэш принудительно"""
    _cache["df"] = None
    _cache["timestamp"] = None
    _cache["initiators"] = None
    _cache["initiators_timestamp"] = None
    _cache["lists"] = None
    _cache["lists_timestamp"] = None
    logger.info("Кэш полностью очищен")