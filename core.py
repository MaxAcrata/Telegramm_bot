import logging
from datetime import datetime, timedelta
import pandas as pd

from config import COLUMN_MAPPING, OVERDUE_DAYS, REPORT_FILE_NAME
from google_sheets import load_google_sheet
from utils import parse_date, format_date

logger = logging.getLogger(__name__)


def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Приводит названия колонок к единому виду"""
    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace(r"[\n\r]+", " ", regex=True)
    )
    return df


def map_columns(df: pd.DataFrame) -> dict:
    """
    Сопоставляет колонки таблицы с внутренними ключами.

    Raises:
        ValueError: Если не удалось найти обязательную колонку
    """
    normalized_columns = {str(col).strip(): col for col in df.columns}
    result = {}

    for key, variants in COLUMN_MAPPING.items():
        found = None
        for variant in variants:
            variant_lower = variant.lower().strip()
            for norm_name, orig_name in normalized_columns.items():
                if variant_lower in norm_name:
                    found = orig_name
                    break
            if found:
                break

        if not found:
            raise ValueError(
                f"Не найдена колонка для '{key}'. "
                f"Доступные: {list(df.columns)}"
            )
        result[key] = found

    return result


def get_active_tasks(df: pd.DataFrame, cols: dict) -> pd.DataFrame:
    """
    Фильтрует активные задачи (без даты выполнения).

    Args:
        df: Исходный DataFrame
        cols: Маппинг колонок

    Returns:
        DataFrame только с активными задачами
    """
    # Парсим даты
    df[cols["request_date"]] = df[cols["request_date"]].apply(parse_date)
    df[cols["done_date"]] = df[cols["done_date"]].apply(parse_date)

    # Фильтруем
    active = df[
        df[cols["done_date"]].isna() &
        df[cols["request_date"]].notna()
        ]

    return active


def format_task_html(row: pd.Series, cols: dict, today: datetime) -> str:
    """Форматирует одну задачу в HTML для Telegram"""
    name = str(row.get(cols["name"], "Без названия")).strip()
    qty = str(row.get(cols["quantity"], "")).strip()
    unit = str(row.get(cols["unit"], "")).strip()
    obj = str(row.get(cols["object"], "Не указан")).strip()
    req_date = row.get(cols["request_date"])
    notes = str(row.get(cols["notes"], "")).strip().lower()

    # Статус
    is_ordered = "заказ" in notes
    days_elapsed = (today - req_date).days if req_date else 0
    is_overdue = days_elapsed > OVERDUE_DAYS

    # Эмодзи-индикаторы
    if is_overdue:
        status_emoji = "🔴"
    elif is_ordered:
        status_emoji = "🟡"
    else:
        status_emoji = "⚪"

    qty_text = f"{qty} {unit}".strip() if qty else "—"
    date_text = format_date(req_date)

    lines = [
        f"{status_emoji} <b>{name}</b>",
        f"   └ Кол-во: <code>{qty_text}</code>",
        f"   └ Объект: {obj}",
        f"   └ Заявка: {date_text}",
    ]

    if is_overdue:
        lines.append(f"   └ ⚠️ Просрочено на {days_elapsed} дн.")

    return "\n".join(lines)


def build_report_html(active_tasks: pd.DataFrame, cols: dict) -> str:
    """
    Генерирует HTML-отчёт для Telegram.

    Args:
        active_tasks: DataFrame с активными задачами
        cols: Маппинг колонок

    Returns:
        Отформатированный HTML-текст отчёта
    """
    today = datetime.today().date()

    report = [
        "<b> СВОДКА ПО АКТИВНЫМ ЗАЯВКАМ</b>",
        f" Дата: {today.strftime('%d.%m.%Y')}",
        f" Всего активных: <b>{len(active_tasks)}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if active_tasks.empty:
        report.append("✅ На данный момент активных заявок нет.")
        return "\n".join(report)

    # Статистика
    notes = active_tasks[cols["notes"]].fillna("").astype(str).str.lower()
    ordered = active_tasks[notes.str.contains("заказ", na=False)]
    not_ordered = active_tasks[~notes.str.contains("заказ", na=False)]
    overdue = active_tasks[
        active_tasks[cols["request_date"]] < today - timedelta(days=OVERDUE_DAYS)
        ]

    report.extend([
        f" Заказано: <b>{len(ordered)}</b>",
        f" Не заказано: <b>{len(not_ordered)}</b>",
        f" Просрочено (&gt;{OVERDUE_DAYS} дн.): <b>{len(overdue)}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        ""
    ])

    # Группировка по объектам
    for obj, group in active_tasks.groupby(cols["object"]):
        report.append(f"\n <b>Объект: {obj}</b>")
        for _, task in group.iterrows():
            report.append(format_task_html(task, cols, today))
        report.append("")

    return "\n".join(report)


def analyze_google_sheet(save_to_file: bool = True) -> str:
    """
    Главная функция анализа.

    Args:
        save_to_file: Сохранять ли отчёт в файл

    Returns:
        HTML-отчёт
    """
    try:
        logger.info("Запуск анализа Google таблицы...")

        # Загружаем и чистим данные
        df = load_google_sheet()
        df = clean_column_names(df).dropna(how="all")
        cols = map_columns(df)

        # Получаем активные задачи
        active_tasks = get_active_tasks(df, cols)

        # Формируем отчёт
        result = build_report_html(active_tasks, cols)

        # Сохраняем в файл (опционально)
        if save_to_file:
            with open(REPORT_FILE_NAME, "w", encoding="utf-8") as f:
                f.write(result)

        logger.info("Анализ завершён успешно")
        return result

    except Exception as e:
        logger.error(f"Ошибка при анализе таблицы: {e}", exc_info=True)
        raise


def get_unique_values(column_key: str) -> list:
    """
    Получает уникальные значения из колонки.

    Args:
        column_key: Ключ колонки из COLUMN_MAPPING

    Returns:
        Список уникальных непустых значений
    """
    try:
        df = load_google_sheet()
        df = clean_column_names(df)
        cols = map_columns(df)

        if column_key not in cols:
            logger.warning(f"Ключ '{column_key}' не найден")
            return []

        col_name = cols[column_key]
        values = (
            df[col_name]
            .dropna()
            .astype(str)
            .str.strip()
            .tolist()
        )

        # Фильтруем пустые и служебные значения
        unique = list(dict.fromkeys(
            v for v in values
            if v and v.lower() not in ("nan", "none", "")
        ))

        return unique

    except Exception as e:
        logger.warning(f"Ошибка загрузки колонки '{column_key}': {e}")
        return []