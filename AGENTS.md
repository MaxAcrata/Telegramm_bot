# AGENTS.md

Instructions for AI agents working with this codebase.

## Project Overview

Telegram bot for managing construction material requests. Data lives in a local SQLite database (`bot.db`). Users submit requests through a 6-step conversation flow; admins receive daily HTML reports, can complete requests, and manage reference lists.

## Architecture

| File | Responsibility | Depends on |
|---|---|---|
| `bot.py` | Telegram handlers, ConversationHandlers, keyboards, scheduled report, admin panel, registration, notifications | `core`, `db`, `utils`, `config` |
| `config.py` | Loads `.env`, validates required vars at import time, defines constants | `dotenv` |
| `core.py` | Report generation: HTML formatting, overdue analysis, active/completed modes | `db`, `config` |
| `db.py` | SQLite database: schema, CRUD for requests, lists, settings, initiator-user links | `sqlite3`, `config` |
| `utils.py` | Quantity validation (positive finite numbers only), HTML-safe message splitting | (standalone) |

Data flow: `bot.py` → `db.py` → SQLite → `core.py` → HTML report

## Key Conventions

- **Language**: All user-facing strings are in Russian. Variable names and docstrings in English.
- **Config**: All secrets and environment-dependent values in `.env`. `config.py` calls `_require_env()` for mandatory vars — process exits at import time if missing.
- **Database**: SQLite via `sqlite3` (stdlib). Schema auto-created by `db.init_db()`. Tables:
  - `requests` — заявки
  - `lists` — справочники (`list_type`: `initiator`, `object`, `unit`)
  - `settings` — настройки (кнопок в строке и т.д.)
  - `initiator_users` — привязка инициаторов к Telegram-ID
- **Conversation states (заявки)**: `NAME → QUANTITY → UNIT → INITIATOR (auto-skip if linked) → INITIATOR_CUSTOM → OBJECT → OBJECT_CUSTOM → NOTES → CONFIRM`. CONFIRM accepts only `✅ Подтвердить` or `❌ Отмена`.
- **Conversation states (регистрация)**: `REG_NAME` — non-admin users pick their initiator name on first `/start`.
- **Conversation states (завершение заявки)**: `COMPLETE_SELECT → COMPLETE_CONFIRM` — admin selects active request to mark done.
- **Conversation states (анализ)**: filter choice `active` / `completed` via inline buttons.
- **Conversation states (админ-панель)**: `ADMIN_MENU → ADMIN_LIST_VIEW → ADMIN_RENAME_NEW / ADMIN_DELETE / ADMIN_ADD_VALUE / ADMIN_BUTTONS_EDIT` — manage reference lists via inline keyboards.
- **HTML in Telegram**: Reports use Telegram HTML parse mode. `split_message()` in `utils.py` splits long messages on `\n` boundaries and closes unclosed HTML tags per chunk.
- **SOCKS5 proxy**: Optional, configured via `SOCKS5_PROXY` env var.

## ConversationHandlers registration order (in `main()`)

1. `register_conv` — `/start` for unregistered non-admin users (registration)
2. `CommandHandler("start", start)` — `/start` for admins and registered users
3. `analysis_handler` — `📊 Анализ` button
4. `complete_handler` — `✅ Завершить заявку` button
5. `admin_handler` — `⚙️ Настройки` button
6. `conv_handler` — `➕ Добавить заявку` button
7. `handle_menu` — catch-all for remaining text

**Important**: `start()` must return `ConversationHandler.END` for admins and registered users to avoid blocking subsequent handlers.

## Notifications on request completion

When admin completes a request, three notifications are sent:
1. Admin inline message (edited callback message)
2. Shared chat (`TELEGRAM_CHAT_ID`)
3. Initiator personal message (if linked via `initiator_users` table)

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
- **All 32 tests pass**.

When adding new tests:
- Async bot handlers: use `@pytest.mark.asyncio`, mock `update.message.reply_text` with `AsyncMock()`, mock `context.user_data` as a plain dict.
- DB functions: use the `tmp_path` fixture pattern from `test_db.py`.

## Common Pitfalls

- **Import-time side effects**: `config.py` calls `sys.exit(1)` if required env vars are missing. Tests that import `core` or `bot` transitively import `config`. The `.env` file must exist with valid values.
- **SQLite file locking**: Only one process should write to `bot.db` at a time. The `get_conn()` context manager uses WAL journal mode for better concurrency.
- **ConversationHandler fallbacks**: The `❌ Отмена` button is handled via `MessageHandler(filters.Regex('^❌ Отмена$'), cancel)` in fallbacks, not per-state. This means it works in all states including CONFIRM.
- **Emoji in regex filters**: `⚙️` (U+2699 + U+FE0F variation selector) may arrive without the selector in Telegram messages. Use `filters.Regex('Настройки')` (match on text, not emoji) instead of `filters.Regex('^⚙️ Настройки$')`.
- **Admin panel "Настройки" restart**: The `admin_handler` must include `MessageHandler(filters.Regex('Настройки'), admin_start)` in **fallbacks** (not just entry_points) so the button works when pressed while already inside the settings conversation.
- **Admin panel "Назад" button**: `back_main` callback appears in both `ADMIN_MENU` and `ADMIN_LIST_VIEW` states. Both `admin_menu_handler` and `admin_list_view_handler` must handle it (use shared `_show_main_settings()` helper).
- **PowerShell syntax**: On Windows, use `;` not `&&` to chain shell commands.
- **New tables need fallback**: Functions accessing `settings` and `initiator_users` tables must use try/except to handle cases where the table doesn't exist yet (e.g., in tests with temporary DBs). See `get_setting()` and `get_initiator_by_tg_id()` for examples.

## Files to Touch Together

- Changing conversation flow → update `bot.py` (handlers + ConversationHandler states) and `tests/test_bot.py`
- Changing report format → update `core.py` and `tests/test_core.py`
- Changing DB schema → update `db.py` (schema + CRUD) and `tests/test_db.py`
- Adding a new env var → add to `config.py`, update `.env.example` if present, update README.md
- Changing default names or lists → update `_DEFAULT_LISTS` in `db.py` and fallbacks in `bot.py`

## Security Notes

### Secrets and configuration
- `.env` is in `.gitignore` — never commit it.
- `bot.db` is in `.gitignore` — it contains operational data, not code.
- `credentials.json` (Google Cloud service account key) — must be deleted and key revoked. Leftover from pre-SQLite migration.
- Telegram bot token gives full control over the bot. If exposed, revoke via @BotFather immediately.
- `ADMIN_IDS` controls who can trigger analysis and manage settings. Validate before adding new admin-only features.
- `initiator_users` table stores Telegram user IDs — treat as personal data.

### Authorization
- Every admin/complete handler re-checks `is_admin()` as defense-in-depth (not just the entry point).
- `is_admin()` uses `update.effective_user.id` from Telegram server — cannot be spoofed via `callback_data`.
- Registration checks `get_initiator_tg_id()` before linking — prevents hijacking an already-linked name.

### HTML injection prevention
- **All user-supplied fields** (`name`, `unit`, `initiator`, `object`, `notes`, `username`, DB list values) must be escaped with `html.escape()` before embedding in Telegram HTML messages (`parse_mode='HTML'`).
- This applies in both `bot.py` (user messages) and `core.py` (reports).
- Telegram's HTML parser supports `<a href>` — unescaped user input can inject phishing links.

### Input validation
- `validate_quantity()` rejects negative, zero, `inf`, and `NaN` values (`math.isfinite` check).
- `bpr` setting is range-checked (1–6).
- `callback_data` values from list names are truncated to 50 characters (Telegram 64-byte limit).

### Error handling
- Exception messages are never shown to users — only generic messages. Full details go to `logger.error()` only.
- Proxy URL credentials are masked before logging.

### Rate limiting
- No rate limiting is currently implemented. Consider adding per-user throttling for production use.