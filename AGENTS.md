# AGENTS.md

Instructions for AI agents working with this codebase.

## Project Overview

Telegram bot for managing construction material requests. Data lives in Google Sheets. Users submit requests through a 6-step conversation flow; admins receive daily HTML reports.

## Architecture

| File | Responsibility | Depends on |
|---|---|---|
| `bot.py` | Telegram handlers, ConversationHandler, keyboards, scheduled report | `core`, `google_sheets`, `utils`, `config` |
| `config.py` | Loads `.env`, validates required vars at import time, defines constants | `dotenv` |
| `core.py` | Data analysis: column mapping, active task filtering, HTML report building | `google_sheets`, `utils`, `config` |
| `google_sheets.py` | Google Sheets API client, data caching (TTL-based), row insertion | `gspread`, `config` |
| `utils.py` | Date parsing, quantity validation, HTML-safe message splitting | (standalone) |

Data flow: `bot.py` → `core.py` → `google_sheets.py` → Google Sheets API

## Key Conventions

- **Language**: All user-facing strings are in Russian. Variable names and docstrings in English.
- **Config**: All secrets and environment-dependent values in `.env`. `config.py` calls `_require_env()` for mandatory vars — process exits at import time if missing.
- **Caching**: `google_sheets.py` uses two caches — one for the spreadsheet data (`_cache["df"]`), one for the Google client (`_client_cache`). TTL is `CACHE_TTL` seconds (default 300). `add_row()` invalidates the data cache.
- **Column mapping**: `COLUMN_MAPPING` in `config.py` maps logical names to possible column header variants. `map_columns()` in `core.py` does fuzzy matching (substring containment).
- **Conversation states**: `NAME → QUANTITY → UNIT → INITIATOR → INITIATOR_CUSTOM → OBJECT → NOTES → CONFIRM`. Every state shows a cancel button (`❌ Отмена`). CONFIRM state shows a summary and waits for `✅ Подтвердить`.
- **HTML in Telegram**: Reports use Telegram HTML parse mode. `split_message()` in `utils.py` splits long messages on `\n` boundaries and closes unclosed HTML tags per chunk.

## Running

```bash
# Activate venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/Mac

# Run bot
python bot.py

# Run tests
python -m pytest tests/ -v
```

## Testing

- **Framework**: pytest + pytest-asyncio
- **Test runner**: `python -m pytest tests/ -v` (must use venv Python)
- **Mocking**: Google Sheets calls are mocked via `unittest.mock.patch`. Telegram API calls use `AsyncMock` for reply_text/send_message.
- **Fixtures**: `test_google_sheets.py` has `reset_cache` autouse fixture that clears `_cache` and `_client_cache` before each test.
- **Known issue**: `test_validate_quantity_invalid` fails on `"-10"` — `validate_quantity()` accepts negative numbers. This is a pre-existing bug, not related to recent changes.

When adding new tests:
- Async bot handlers: use `@pytest.mark.asyncio`, mock `update.message.reply_text` with `AsyncMock()`, mock `context.user_data` as a plain dict.
- Google Sheets functions: mock `google_sheets._get_google_client` to avoid real API calls.

## Common Pitfalls

- **Import-time side effects**: `config.py` calls `sys.exit(1)` if required env vars are missing. Tests that import `core` or `bot` transitively import `config`. The `.env` file must exist with valid values, or tests that touch these modules will fail at collection.
- **gspread client reuse**: `_get_google_client()` caches the client globally. Tests must reset `google_sheets._client_cache = None` in fixtures to avoid cross-test contamination.
- **ConversationHandler fallbacks**: The `❌ Отмена` button is handled via `MessageHandler(filters.Regex('^❌ Отмена$'), cancel)` in fallbacks, not per-state. This means it works in all states including CONFIRM.
- **PowerShell syntax**: On Windows, use `;` not `&&` to chain shell commands.

## Files to Touch Together

- Changing conversation flow → update `bot.py` (handlers + ConversationHandler states) and `tests/test_bot.py`
- Changing column mapping → update `config.py` (`COLUMN_MAPPING`) and `tests/test_core.py`
- Changing cache behavior → update `google_sheets.py` and `tests/test_google_sheets.py`
- Adding a new env var → add to `config.py`, update `.env.example` if present, update README.md

## Security Notes

- `.env` and `credentials.json` are in `.gitignore` — never commit them.
- Telegram bot token gives full control over the bot. If exposed, revoke via @BotFather immediately.
- `ADMIN_IDS` controls who can trigger analysis and cache refresh. Validate before adding new admin-only features.
