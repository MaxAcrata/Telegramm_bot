import os
import sys
from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    """Возвращает значение обязательной переменной или завершает процесс."""
    value = os.getenv(name)
    if not value:
        print(f"❌ Обязательная переменная окружения {name} не задана. "
              f"Добавьте её в .env", file=sys.stderr)
        sys.exit(1)
    return value


# ===== GOOGLE SHEETS =====
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_SHEET_ID = _require_env("GOOGLE_SHEET_ID")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Input")

# ===== TELEGRAM =====
TELEGRAM_BOT_TOKEN = _require_env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _require_env("TELEGRAM_CHAT_ID")
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip()]

# ===== REPORTS =====
OVERDUE_DAYS = int(os.getenv("OVERDUE_DAYS", 3))
REPORT_HOUR = int(os.getenv("REPORT_HOUR", 9))
REPORT_MINUTE = int(os.getenv("REPORT_MINUTE", 0))
REPORT_FILE_NAME = "report.txt"
CACHE_TTL = int(os.getenv("CACHE_TTL", 300))  # 5 минут

# ===== OTHER =====
GOOGLE_FORM_LINK = os.getenv("GOOGLE_FORM_LINK", "")
MAX_MESSAGE_LENGTH = 4000

# ===== COLUMN MAPPING =====
COLUMN_MAPPING = {
    "name": ["наименование"],
    "quantity": ["кол-во"],
    "unit": ["ед. изм"],
    "request_date": ["дата заявки"],
    "done_date": ["дата выполнения"],
    "initiator": ["инициатор"],
    "status": ["статус"],
    "object": ["объект"],
    "notes": ["примечания"],
}

# ===== STATIC KEYBOARDS =====
UNITS = ["шт", "кг", "л", "м2", "м3", "лист", "м.п.", "комп"]
# INITIATORS теперь загружается динамически из листа Team