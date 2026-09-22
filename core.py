import logging
from datetime import datetime, timedelta, date

from config import OVERDUE_DAYS, REPORT_FILE_NAME
from db import get_active_requests

logger = logging.getLogger(__name__)


def format_task_html(task: dict, today: date) -> str:
    """Форматирует одну задачу в HTML для Telegram"""
    name = task.get("name", "Без названия")
    qty = task.get("quantity")
    unit = task.get("unit", "")
    obj = task.get("object", "Не указан")
    initiator = task.get("initiator", "Не указан")
    notes = (task.get("notes") or "").lower()

    req_date_str = task.get("request_date", "")
    req_date = date.fromisoformat(req_date_str) if req_date_str else None

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
    date_text = req_date.strftime("%d.%m.%Y") if req_date else "нет даты"

    lines = [
        f"{status_emoji} <b>{name}</b>",
        f"   └ Кол-во: <code>{qty_text}</code>",
        f"   └ Инициатор: {initiator}",
        f"   └ Объект: {obj}",
        f"   └ Заявка: {date_text}",
    ]

    if is_overdue:
        lines.append(f"   └ ⚠️ Просрочено на {days_elapsed} дн.")

    return "\n".join(lines)


def build_report(save_to_file: bool = True) -> str:
    """Генерирует HTML-отчёт по активным заявкам."""
    today = date.today()
    active_tasks = get_active_requests()

    report = [
        "<b> СВОДКА ПО АКТИВНЫМ ЗАЯВКАМ</b>",
        f" Дата: {today.strftime('%d.%m.%Y')}",
        f" Всего активных: <b>{len(active_tasks)}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if not active_tasks:
        report.append("✅ На данный момент активных заявок нет.")
        result = "\n".join(report)
        if save_to_file:
            _save_report(result)
        return result

    # Статистика
    ordered = [t for t in active_tasks if "заказ" in (t.get("notes") or "").lower()]
    overdue = [
        t for t in active_tasks
        if t.get("request_date")
        and date.fromisoformat(t["request_date"]) < today - timedelta(days=OVERDUE_DAYS)
    ]

    report.extend([
        f" Заказано: <b>{len(ordered)}</b>",
        f" Не заказано: <b>{len(active_tasks) - len(ordered)}</b>",
        f" Просрочено (&gt;{OVERDUE_DAYS} дн.): <b>{len(overdue)}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        ""
    ])

    # Группировка по объектам
    from itertools import groupby
    sorted_tasks = sorted(active_tasks, key=lambda t: t.get("object", ""))
    for obj, group_iter in groupby(sorted_tasks, key=lambda t: t.get("object", "")):
        group = list(group_iter)
        report.append(f"\n <b>Объект: {obj}</b>")
        for task in group:
            report.append(format_task_html(task, today))
        report.append("")

    # Раздел просроченных заявок по инициаторам
    if overdue:
        report.extend([
            "",
            " <b>⚠️ ПРОСРОЧЕННЫЕ ЗАЯВКИ</b>",
            "━━━━━━━━━━━━━━━━━━━━",
        ])
        sorted_overdue = sorted(overdue, key=lambda t: t.get("initiator", ""))
        for initiator, group_iter in groupby(sorted_overdue, key=lambda t: t.get("initiator", "")):
            group = list(group_iter)
            report.append(f"\n 👤 <b>{initiator}</b> — {len(group)} шт.")
            for task in group:
                name = task.get("name", "—")
                obj = task.get("object", "—")
                req_date_str = task.get("request_date", "")
                req_date = date.fromisoformat(req_date_str) if req_date_str else None
                days = (today - req_date).days if req_date else 0
                report.append(f"    • {name} ({obj}) — {days} дн.")

    result = "\n".join(report)
    if save_to_file:
        _save_report(result)
    logger.info("Отчёт сформирован")
    return result


def _save_report(text: str):
    """Сохраняет отчёт в файл."""
    try:
        with open(REPORT_FILE_NAME, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        logger.warning(f"Не удалось сохранить отчёт: {e}")
