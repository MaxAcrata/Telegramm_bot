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


# ===== TELEGRAM =====
TELEGRAM_BOT_TOKEN = _require_env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _require_env("TELEGRAM_CHAT_ID")
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip()]

# ===== DATABASE =====
DB_PATH = os.getenv("DB_PATH", "/data/bot.db")

# ===== REPORTS =====
OVERDUE_DAYS = int(os.getenv("OVERDUE_DAYS", 3))
REPORT_HOUR = int(os.getenv("REPORT_HOUR", 9))
REPORT_MINUTE = int(os.getenv("REPORT_MINUTE", 0))
REPORT_FILE_NAME = "report.txt"

# ===== PROXY =====
SOCKS5_PROXY = os.getenv("SOCKS5_PROXY", "")

# ===== OTHER =====
MAX_MESSAGE_LENGTH = 4000
