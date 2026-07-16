# HANDOFF — Оборудыш (16.07.2026)

## Текущее состояние

Единый релиз объединяет функционал 9–16 июля: паспорта экземпляров, недельный календарь, SSE/revision, локальные шрифты, SQLite-оптимизацию и Google Sheets score queue. Рабочая версия находится в `main` после релизного коммита.

Следующая сессия начинается с `NEXT.md`. Главные задачи: закрытая таблица людей, отдельная таблица баллов, актуализация каталога и финальный тест.

## Ключевые файлы

- `bot/main.py` — API, Telegram-бот, SQLite, scheduler, SSE и Google Sheets.
- `bot/texts.py` — редактируемые уведомления и подписи Telegram.
- `prototype/index.html` — интерфейс и клиентская логика.
- `prototype/texts.js` — редактируемые видимые подписи Mini App.
- `prototype/style.css`, `prototype/fonts/` — дизайн и локальный Montserrat.
- `bot/test_core.py` — локальные unit-тесты.

## Новая схема и API

- `equipment_units(short,num,serial,note,state,updated_at,updated_by)`.
- `requests.issued_by`, `requests.returned_by`.
- `score_events` — локальная надёжная очередь начислений.
- `GET /api/events`.
- `POST /api/equipment/unit`, `/api/equipment/unit/update`.
- `/api/revision` остаётся лёгким источником версии данных.

Миграция выполняется автоматически без сброса БД. Старые nullable-поля не заполняются задним числом.

## Проверка

```powershell
cd bot
.\.venv\Scripts\python.exe -m unittest -v test_core.py
.\.venv\Scripts\python.exe -m py_compile main.py texts.py test_core.py
```

Локальный результат на 16.07.2026: 17/17 PASS плюс полный DEV E2E оборудования, 626, паспорта и SSE.

## Деплой

Следовать только верхнему разделу `DEPLOY.md`: backup → остановка одного `oborudka.service` → перенос файлов → обновление project venv → миграционный запуск → проверка → включение Google Sheets. System Python и другие боты не трогать.

После выкладки обязательно проверить в Telegram: media group, проблемный возврат, чаты, непрочитанные, паспорт, ремонтный экземпляр, недельный календарь, `/digest`, `/scorestatus`, `/scoresync`.
