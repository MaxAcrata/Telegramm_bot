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


def load_initiators_from_team(use_cache: bool = True) -> List[str]:
    """
    Загружает список инициаторов из листа Team, колонка A.

    Args:
        use_cache: Использовать ли кэш

    Returns:
        Список уникальных инициаторов
    """
    now = datetime.now()

    # Проверяем кэш
    if use_cache and _cache["initiators"] is not None and _cache["initiators_timestamp"]:
        age = (now - _cache["initiators_timestamp"]).total_seconds()
        if age < CACHE_TTL:
            logger.info(f"Используем кэш инициаторов (возраст: {age:.0f}с)")
            return _cache["initiators"].copy()

    # Загружаем свежие данные
    logger.info("Загрузка инициаторов из листа Team...")
    try:
        client = _get_google_client()
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        worksheet = sheet.worksheet("Team")  # ✅ Лист Team

        # Получаем все значения из колонки A
        values = worksheet.col_values(1)  # Колонка A = индекс 1

        # Удаляем заголовок (первую строку) и пустые значения
        initiators = [
            v.strip()
            for v in values[1:]  # Пропускаем заголовок
            if v and v.strip()  # Убираем пустые
        ]

        # Убираем дубликаты, сохраняя порядок
        unique_initiators = list(dict.fromkeys(initiators))

        # Добавляем опцию "Другое" в конец
        if "Другое" not in unique_initiators:
            unique_initiators.append("Другое")

        # Обновляем кэш
        _cache["initiators"] = unique_initiators.copy()
        _cache["initiators_timestamp"] = now

        logger.info(f"Загружено {len(unique_initiators)} инициаторов: {unique_initiators}")
        return unique_initiators

    except Exception as e:
        logger.error(f"Ошибка загрузки инициаторов: {e}")
        # Возвращаем значения по умолчанию
        return ["Иван", "Петр", "Анна", "Другое"]


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
    logger.info("Кэш полностью очищен")