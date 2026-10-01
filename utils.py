import logging
import math
from datetime import datetime
from typing import Optional

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)


def parse_date(value) -> Optional[datetime]:
    """Парсит строку или объект даты в datetime.date"""
    if not value or str(value).strip() in ("", "nan", "None"):
        return None

    if isinstance(value, datetime):
        return value.date()

    value = str(value).strip()
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def format_date(value) -> str:
    """Форматирует дату в DD.MM.YYYY"""
    if not value or str(value).strip() in ("", "nan"):
        return "нет даты"

    if isinstance(value, str):
        parsed = parse_date(value)
        return parsed.strftime("%d.%m.%Y") if parsed else "нет даты"

    return value.strftime("%d.%m.%Y")


def validate_quantity(value: str) -> bool:
    """Проверяет, что количество - положительное конечное число"""
    try:
        num = float(value.replace(",", "."))
        return num > 0 and math.isfinite(num)
    except ValueError:
        return False


def split_message(text: str, max_length: int = 4000) -> list:
    """Разбивает длинное сообщение на части, не ломая HTML-теги и строки."""
    if len(text) <= max_length:
        return [text]

    messages = []
    while text:
        if len(text) <= max_length:
            messages.append(text)
            break

        # Ищем последний перенос строки в пределах лимита
        cut = text.rfind("\n", 0, max_length)
        if cut == -1:
            cut = max_length

        part = text[:cut]

        # Закрываем незакрытые HTML-теги в этой части
        # Храним (tag_name, full_opening_tag) для сохранения атрибутов
        open_tags = []
        i = 0
        while i < len(part):
            if part[i] == "<":
                end = part.find(">", i)
                if end == -1:
                    break
                full_tag = part[i : end + 1]
                tag_content = part[i + 1 : end]
                if tag_content.startswith("/"):
                    close_name = tag_content[1:].split()[0]
                    if open_tags and open_tags[-1][0] == close_name:
                        open_tags.pop()
                elif not tag_content.endswith("/"):
                    tag_name = tag_content.split()[0]
                    if tag_name in (
                        "b",
                        "i",
                        "u",
                        "s",
                        "code",
                        "pre",
                        "em",
                        "strong",
                        "a",
                    ):
                        open_tags.append((tag_name, full_tag))
                i = end + 1
            else:
                i += 1

        # Закрываем открытые теги
        for tag_name, _ in reversed(open_tags):
            part += f"</{tag_name}>"

        messages.append(part)

        # Восстанавливаем открытые теги в следующей части (с атрибутами)
        remainder_start = cut
        while remainder_start < len(text) and text[remainder_start] == "\n":
            remainder_start += 1

        reopen = "".join(full_tag for _, full_tag in open_tags)
        text = reopen + text[remainder_start:]

    return messages
