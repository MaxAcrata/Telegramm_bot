import logging
import re
from datetime import datetime, timedelta, date
from html import escape

from config import OVERDUE_DAYS, REPORT_FILE_NAME
from db import get_active_requests, get_completed_requests, get_photo_counts

logger = logging.getLogger(__name__)

# Регулярное выражение для поиска URLs
_URL_PATTERN = re.compile(
    r'https?://[^\s<>"\')\]]+|'  # http:// или https://
    r'www\.[^\s<>"\')\]]+'  # www.
)


def make_links_clickable(text: str) -> str:
    """Преобразует ссылки в тексте в кликабельные HTML-ссылки для Telegram.

    Остальной текст экранируется для безопасности (защита от XSS).
    """
    if not text:
        return ""

    parts = []
    last_end = 0

    for match in _URL_PATTERN.finditer(text):
        start, end = match.span()
        url = match.group(0)

        # Экранируем текст до ссылки
        if start > last_end:
            parts.append(escape(text[last_end:start]))

        # Создаём кликабельную ссылку
        href = url
        if url.startswith("www."):
            href = "https://" + url
        parts.append(f'<a href="{escape(href)}">{escape(url)}</a>')

        last_end = end

    # Экранируем оставшийся текст
    if last_end < len(text):
        parts.append(escape(text[last_end:]))

    return "".join(parts)


def format_task_html(task: dict, today: date, photo_count: int = 0) -> str:
    """Форматирует одну задачу в HTML для Telegram"""
    name = escape(task.get("name", "Без названия"))
    qty = task.get("quantity")
    unit = escape(task.get("unit", ""))
    obj = escape(task.get("object", "Не указан"))
    initiator = escape(task.get("initiator", "Не указан"))
    notes_raw = task.get("notes") or ""
    notes_lower = notes_raw.lower()

    req_date_str = task.get("request_date", "")
    req_date = date.fromisoformat(req_date_str) if req_date_str else None

    # Статус
    is_ordered = "заказ" in notes_lower
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

    # Добавляем примечание, если оно есть
    if notes_raw and notes_raw != "-":
        notes_html = make_links_clickable(notes_raw)
        lines.append(f"   └ Примечание: {notes_html}")

    if photo_count:
        lines.append(f"   └ 📎 Фото: {photo_count} шт.")

    if is_overdue:
        lines.append(f"   └ ⚠️ Просрочено на {days_elapsed} дн.")

    return "\n".join(lines)


def build_report(save_to_file: bool = True, mode: str = "active") -> tuple:
    """Генерирует HTML-отчёт. mode: 'active' или 'completed'.
    Возвращает (text, ids_with_photos) — текст отчёта и список ID заявок с фото."""
    today = date.today()

    if mode == "completed":
        text, ids = _build_completed_report(today, save_to_file)
    else:
        text, ids = _build_active_report(today, save_to_file)

    return text, ids


def _build_completed_report(today: date, save_to_file: bool) -> tuple:
    """Отчёт по выполненным заявкам. Возвращает (text, ids_with_photos)."""
    tasks = get_completed_requests()

    report = [
        "<b>✅ ВЫПОЛНЕННЫЕ ЗАЯВКИ</b>",
        f"📅 Дата: {today.strftime('%d.%m.%Y')}",
        f"📊 Всего: <b>{len(tasks)}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if not tasks:
        report.append("Нет выполненных заявок.")
        result = "\n".join(report)
        if save_to_file:
            _save_report(result)
        return result, []

    # Получаем количество фото для всех заявок
    task_ids = [t["id"] for t in tasks]
    photo_counts = get_photo_counts(task_ids)
    ids_with_photos = [rid for rid, cnt in photo_counts.items() if cnt > 0]

    for task in tasks:
        name = escape(task.get("name", "—"))
        qty = task.get("quantity")
        unit = escape(task.get("unit", ""))
        obj = escape(task.get("object", "—"))
        initiator = escape(task.get("initiator", "—"))
        done_str = task.get("done_date", "")
        done_date = date.fromisoformat(done_str) if done_str else None
        done_text = done_date.strftime("%d.%m.%Y") if done_date else "—"
        qty_text = f"{qty} {unit}".strip() if qty else "—"
        notes_raw = task.get("notes") or ""

        report.append(f"✅ <b>{name}</b>")
        report.append(f"   └ Кол-во: <code>{qty_text}</code>")
        report.append(f"   └ Инициатор: {initiator}")
        report.append(f"   └ Объект: {obj}")
        report.append(f"   └ Выполнено: {done_text}")

        # Добавляем примечание, если оно есть
        if notes_raw and notes_raw != "-":
            notes_html = make_links_clickable(notes_raw)
            report.append(f"   └ Примечание: {notes_html}")

        # Добавляем количество фото
        pc = photo_counts.get(task["id"], 0)
        if pc:
            report.append(f"   └ 📎 Фото: {pc} шт.")

        report.append("")

    result = "\n".join(report)
    if save_to_file:
        _save_report(result)
    return result, ids_with_photos


def _build_active_report(today: date, save_to_file: bool) -> tuple:
    """Отчёт по активным заявкам. Возвращает (text, ids_with_photos)."""
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
        return result, []

    # Статистика
    ordered = [t for t in active_tasks if "заказ" in (t.get("notes") or "").lower()]
    overdue = [
        t
        for t in active_tasks
        if t.get("request_date")
        and date.fromisoformat(t["request_date"]) < today - timedelta(days=OVERDUE_DAYS)
    ]

    report.extend(
        [
            f" Заказано: <b>{len(ordered)}</b>",
            f" Не заказано: <b>{len(active_tasks) - len(ordered)}</b>",
            f" Просрочено (&gt;{OVERDUE_DAYS} дн.): <b>{len(overdue)}</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
        ]
    )

    # Группировка по объектам
    from itertools import groupby

    # Получаем количество фото для всех заявок
    task_ids = [t["id"] for t in active_tasks]
    photo_counts = get_photo_counts(task_ids)
    ids_with_photos = [rid for rid, cnt in photo_counts.items() if cnt > 0]

    sorted_tasks = sorted(active_tasks, key=lambda t: t.get("object", ""))
    for obj, group_iter in groupby(sorted_tasks, key=lambda t: t.get("object", "")):
        group = list(group_iter)
        report.append(f"\n <b>Объект: {escape(obj)}</b>")
        for task in group:
            pc = photo_counts.get(task["id"], 0)
            report.append(format_task_html(task, today, photo_count=pc))
        report.append("")

    # Раздел просроченных заявок по инициаторам
    if overdue:
        report.extend(
            [
                "",
                " <b>⚠️ ПРОСРОЧЕННЫЕ ЗАЯВКИ</b>",
                "━━━━━━━━━━━━━━━━━━━━",
            ]
        )
        sorted_overdue = sorted(overdue, key=lambda t: t.get("initiator", ""))
        for initiator, group_iter in groupby(
            sorted_overdue, key=lambda t: t.get("initiator", "")
        ):
            group = list(group_iter)
            report.append(f"\n 👤 <b>{escape(initiator)}</b> — {len(group)} шт.")
            for task in group:
                name = escape(task.get("name", "—"))
                obj = escape(task.get("object", "—"))
                notes_raw = task.get("notes") or ""
                req_date_str = task.get("request_date", "")
                req_date = date.fromisoformat(req_date_str) if req_date_str else None
                days = (today - req_date).days if req_date else 0
                pc = photo_counts.get(task["id"], 0)
                photo_label = f" 📎{pc}" if pc else ""
                report.append(f"    • {name} ({obj}) — {days} дн.{photo_label}")
                if notes_raw and notes_raw != "-":
                    notes_html = make_links_clickable(notes_raw)
                    report.append(f"      Примечание: {notes_html}")

    result = "\n".join(report)
    if save_to_file:
        _save_report(result)
    logger.info("Отчёт сформирован")
    return result, ids_with_photos


def _save_report(text: str):
    """Сохраняет отчёт в файл."""
    try:
        with open(REPORT_FILE_NAME, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        logger.warning(f"Не удалось сохранить отчёт: {e}")
