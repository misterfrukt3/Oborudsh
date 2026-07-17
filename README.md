# Оборудыш


Регистрация может автоматически заполняться из закрытого листа `люди`.
Одноразовая рассылка пользователям старого кнопочного бота выполняется старшим командой
`/migrateold`; старая база читается напрямую, новая база не изменяется.
Каталог обновляется скриптом `bot/update_catalog_from_csv.py`.

Telegram Mini App для бронирования съёмочного оборудования и аудитории 626 Media BMSTU.

## Состав

- `prototype/` — Mini App: HTML/JS, CSS, каталог, локальные шрифты и редактируемые подписи.
- `bot/main.py` — aiohttp API, aiogram 3, SQLite, scheduler, SSE и Google Sheets.
- `bot/texts.py` — пользовательские тексты Telegram.
- `bot/test_core.py` — unit-тесты.
- `DEPLOY.md` — безопасное обновление единственного production-сервиса.
- `NEXT.md` — точный список задач для продолжения работы с другого компьютера.
- `CLAUDE.md` / `AGENTS.md` — полный контекст проекта для ассистентов.

## Локальная проверка

Требуется Python 3.10+ в отдельном окружении проекта.

```powershell
cd bot
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest -v test_core.py
```

Production использует один сервис `/opt/oborudka`; не создавайте второй бот или вторую базу. `ENABLE_PRODUCTION_ROLE=0` временно скрывает роль production. Google Sheets можно оставить выключенным — начисления сохранятся локально.
