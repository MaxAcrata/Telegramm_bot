# AGENTS.md

Instructions for AI agents working with this codebase.

## Project Overview

Telegram bot for managing construction material requests. Data lives in a local SQLite database (`bot.db`). Users submit requests through a 6-step conversation flow; admins receive daily HTML reports.

## Architecture

| File | Responsibility | Depends on |
|---|---|---|
| `bot.py` | Telegram handlers, ConversationHandler, keyboards, scheduled report | `core`, `db`, `utils`, `config` |
| `config.py` | Loads `.env`, validates required vars at import time, defines constants | `dotenv` |
| `core.py` | Report generation: HTML formatting, overdue analysis | `db`, `config` |
| `db.py` | SQLite database: schema, CRUD for requests and lists | `sqlite3`, `config` |
| `utils.py` | Quantity validation, HTML-safe message splitting | (standalone) |

Data flow: `bot.py` → `db.py` → SQLite → `core.py` → HTML report

## Key Conventions

- **Language**: All user-facing strings are in Russian. Variable names and docstrings in English.
- **Config**: All secrets and environment-dependent values in `.env`. `config.py` calls `_require_env()` for mandatory vars — process exits at import time if missing.
- **Database**: SQLite via `sqlite3` (stdlib). Schema auto-created by `db.init_db()`. Two tables: `requests` (заявки) and `lists` (справочники). Each column in `lists` is identified by `list_type`: `initiator`, `object`, `unit`.
- **Conversation states**: `NAME → QUANTITY → UNIT → INITIATOR → INITIATOR_CUSTOM → OBJECT → NOTES → CONFIRM`. Every state shows a cancel button (`❌ Отмена`). CONFIRM state shows a summary and waits for `✅ Подтвердить`.
- **HTML in Telegram**: Reports use Telegram HTML parse mode. `split_message()` in `utils.py` splits long messages on `\n` boundaries and closes unclosed HTML tags per chunk.

## Running

```bash
# Activate venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/Mac

# Run bot (creates bot.db automatically)
python bot.py

# Run tests
python -m pytest tests/ -v
```

## Testing

- **Framework**: pytest + pytest-asyncio
- **Test runner**: `python -m pytest tests/ -v` (must use venv Python)
- **DB tests**: `test_db.py` uses a `tmp_path` fixture with `patch.object(db, "DB_PATH", ...)` to isolate each test to a temporary database.
- **Core tests**: `test_core.py` mocks `db.get_active_requests` to return fixture data.
- **Bot tests**: `test_bot.py` mocks `db.get_all_lists` and `db.add_request` to avoid real DB calls.
- **Known issue**: `test_validate_quantity_invalid` fails on `"-10"` — `validate_quantity()` accepts negative numbers. This is a pre-existing bug.

When adding new tests:
- Async bot handlers: use `@pytest.mark.asyncio`, mock `update.message.reply_text` with `AsyncMock()`, mock `context.user_data` as a plain dict.
- DB functions: use the `tmp_path` fixture pattern from `test_db.py`.

## Common Pitfalls

- **Import-time side effects**: `config.py` calls `sys.exit(1)` if required env vars are missing. Tests that import `core` or `bot` transitively import `config`. The `.env` file must exist with valid values.
- **SQLite file locking**: Only one process should write to `bot.db` at a time. The `get_conn()` context manager uses WAL journal mode for better concurrency.
- **ConversationHandler fallbacks**: The `❌ Отмена` button is handled via `MessageHandler(filters.Regex('^❌ Отмена$'), cancel)` in fallbacks, not per-state. This means it works in all states including CONFIRM.
- **PowerShell syntax**: On Windows, use `;` not `&&` to chain shell commands.

## Files to Touch Together

- Changing conversation flow → update `bot.py` (handlers + ConversationHandler states) and `tests/test_bot.py`
- Changing report format → update `core.py` and `tests/test_core.py`
- Changing DB schema → update `db.py` (schema + CRUD) and `tests/test_db.py`
- Adding a new env var → add to `config.py`, update `.env.example` if present, update README.md

## Security Notes

- `.env` is in `.gitignore` — never commit it.
- `bot.db` is in `.gitignore` — it contains operational data, not code.
- Telegram bot token gives full control over the bot. If exposed, revoke via @BotFather immediately.
- `ADMIN_IDS` controls who can trigger analysis. Validate before adding new admin-only features.
