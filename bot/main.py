"""Оборудыш - Mini App backend (тестовый бот).

Один процесс (python main.py):
  * aiohttp: раздача prototype/ + JSON API для Mini App (/api/...);
  * aiogram: /start с кнопкой Mini App, карточки заявок в админ-чат,
    уведомления пользователям о статусах, чат заявитель<->куратор.

Авторизация - проверка подписи Telegram initData (HMAC от токена бота).
Хранение - SQLite (bot/oborudka.db). Каталог живёт на фронте (catalog.js).

Пока НЕ здесь (следующие итерации): проверка занятости по датам на сервере,
напоминания/автоотмены (APScheduler), автосверка MB с Google-таблицей, фото сдачи.
"""
import asyncio
import base64
import csv
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qsl

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputRichMessage,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)
import aiohttp
from aiohttp import web
from dotenv import load_dotenv
import texts as tx

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
PORT = int(os.getenv("PORT", "8737"))
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0") or 0)
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
SENIOR_ADMIN_IDS = {int(x) for x in os.getenv("SENIOR_ADMIN_IDS", "").replace(" ", "").split(",") if x}
EXTRA_ADMIN_IDS = set()  # обычные админы, добавленные командой /addadmin (не из .env)
WEBAPP_DIR = BASE.parent / "prototype"
DB_PATH = BASE / "oborudka.db"
UPLOADS = BASE / "uploads"
# ДЕВ-режим для локальных тестов БЕЗ Telegram: DEV_USER_ID=123 в .env -
# запросы без валидной подписи считаются этим пользователем. На проде не задавать!
DEV_USER_ID = int(os.getenv("DEV_USER_ID", "0") or 0)
# автосверка Media BMSTU: опубликованный в веб CSV листа 'список ребят'. Пусто - сверка выключена (MB = авто-ok).
MB_SHEET_URL = os.getenv("MB_SHEET_URL", "")
# автосверка организаций (СО/ССФ): локальный файл, который делает bot/make_members.py из Excel. Пусто/нет - сверка выключена.
ORG_MEMBERS_FILE = os.getenv("ORG_MEMBERS_FILE", str(BASE / "org_members.csv"))
# справочник для автозаполнения по username (если файла нет - работает по старому шаблону)
DIRECTORY_FILE = os.getenv("DIRECTORY_FILE", "")
# Закрытый справочник участников: точное ФИО -> организации, отделы и роль.
MEMBERS_SHEET_ID = os.getenv("MEMBERS_SHEET_ID", "").strip()
MEMBERS_SHEET_TAB = os.getenv("MEMBERS_SHEET_TAB", "люди").strip() or "люди"
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
if GOOGLE_SERVICE_ACCOUNT_FILE:
    _google_key_path = Path(GOOGLE_SERVICE_ACCOUNT_FILE)
    GOOGLE_SERVICE_ACCOUNT_FILE = str(
        _google_key_path if _google_key_path.is_absolute() else BASE / _google_key_path
    )
# Одноразовый импорт адресатов из старой кнопочной версии.
_legacy_path = Path(os.getenv("LEGACY_DB_PATH", "equipment_bot.sqlite3"))
LEGACY_DB_PATH = _legacy_path if _legacy_path.is_absolute() else BASE / _legacy_path
LEGACY_MIGRATION_PASSWORD = os.getenv("LEGACY_MIGRATION_PASSWORD", "")
LEGACY_MIGRATION_WAITING = set()


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


ENABLE_PRODUCTION_ROLE = env_bool("ENABLE_PRODUCTION_ROLE")
GOOGLE_SHEETS_ENABLED = env_bool("GOOGLE_SHEETS_ENABLED")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON_B64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_B64", "").strip()
GOOGLE_SHEET_EVENTS_TAB = os.getenv("GOOGLE_SHEET_EVENTS_TAB", "Начисления").strip() or "Начисления"
GOOGLE_SHEET_SUMMARY_TAB = os.getenv("GOOGLE_SHEET_SUMMARY_TAB", "Админы").strip() or "Админы"


def env_decimal(name: str, default: str) -> Decimal:
    try:
        value = Decimal(os.getenv(name, default).strip())
        if value < 0:
            raise InvalidOperation
        return value
    except (InvalidOperation, ValueError):
        return Decimal(default)


SCORE_DAILY_ADMIN = env_decimal("SCORE_DAILY_ADMIN", "0.1")
SCORE_REQUEST = env_decimal("SCORE_REQUEST", "0.01")
SCORE_626 = env_decimal("SCORE_626", "0.05")

MSK = timezone(timedelta(hours=3))
log = logging.getLogger("oborudka")

bot: Bot = None  # type: ignore  # создаётся в main()
BOT_USERNAME = ""
dp = Dispatcher()
SSE_CLIENTS = set()


# ================= БД =================

class ClosingConnection(sqlite3.Connection):
    """sqlite3 context manager that commits/rolls back and always closes."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY, name TEXT DEFAULT '', username TEXT DEFAULT '',
          photo TEXT DEFAULT '', orgs TEXT DEFAULT '[]', deps TEXT DEFAULT '[]',
          role TEXT DEFAULT 'СО/ССФ', agreed INTEGER DEFAULT 0,
          verified TEXT DEFAULT 'none', block_reason TEXT DEFAULT '', block_until TEXT DEFAULT '', created TEXT);
        CREATE TABLE IF NOT EXISTS requests(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, items TEXT,
          dfrom TEXT, dto TEXT, event TEXT, comment TEXT DEFAULT '',
          media INTEGER DEFAULT 0, pw INTEGER DEFAULT 0,
          status TEXT DEFAULT 'new', curator INTEGER, history TEXT DEFAULT '[]',
          taken_at TEXT, returned_at TEXT, admin_msg INTEGER,
          dfrom_iso TEXT DEFAULT '', dto_iso TEXT DEFAULT '',
          tfrom TEXT DEFAULT '', tto TEXT DEFAULT '',
          created_ts REAL DEFAULT 0, notif TEXT DEFAULT '{}', escalated INTEGER DEFAULT 0,
          nums TEXT DEFAULT '{}', issued_by INTEGER, returned_by INTEGER);
        CREATE TABLE IF NOT EXISTS b626(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, day TEXT, slot TEXT,
          goal TEXT, needs TEXT DEFAULT '[]', status TEXT DEFAULT 'new',
          curator INTEGER, history TEXT DEFAULT '[]', admin_msg INTEGER,
          created_ts REAL DEFAULT 0, notif TEXT DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS messages(
          id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, ref INTEGER,
          sender INTEGER, text TEXT, tm TEXT, role TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS extra_items(
          id INTEGER PRIMARY KEY AUTOINCREMENT, cat TEXT, short TEXT UNIQUE,
          full TEXT DEFAULT '', total INTEGER DEFAULT 1, level TEXT DEFAULT '', created TEXT);
        CREATE TABLE IF NOT EXISTS cat_blocks(
          cat TEXT PRIMARY KEY, until TEXT DEFAULT '', term TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS removed_items(short TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS fav_sets(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, items TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS reads(
          user_id INTEGER, kind TEXT, ref INTEGER, seen INTEGER DEFAULT 0,
          PRIMARY KEY(user_id, kind, ref));
        CREATE TABLE IF NOT EXISTS actions(
          id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, kind TEXT, ref INTEGER,
          action TEXT, ts TEXT);
        CREATE TABLE IF NOT EXISTS extra_admins(
          user_id INTEGER PRIMARY KEY, added_by INTEGER, added_ts TEXT);
        CREATE TABLE IF NOT EXISTS equipment_units(
          short TEXT, num INTEGER, serial TEXT DEFAULT '', note TEXT DEFAULT '',
          state TEXT DEFAULT 'ready', updated_at TEXT DEFAULT '', updated_by INTEGER,
          PRIMARY KEY(short, num));
        CREATE TABLE IF NOT EXISTS score_events(
          event_id TEXT PRIMARY KEY, happened_at TEXT, fio TEXT, admin_id INTEGER,
          kind TEXT, object_id TEXT, points TEXT, details TEXT DEFAULT '',
          status TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0,
          next_retry REAL DEFAULT 0, sent_at TEXT DEFAULT '', last_error TEXT DEFAULT '');
        CREATE INDEX IF NOT EXISTS idx_requests_user_id ON requests(user_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_requests_status_dates ON requests(status, dfrom_iso, dto_iso);
        CREATE INDEX IF NOT EXISTS idx_b626_user_id ON b626(user_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_b626_status_day ON b626(status, day);
        CREATE INDEX IF NOT EXISTS idx_messages_ref ON messages(kind, ref, id);
        CREATE INDEX IF NOT EXISTS idx_actions_ref ON actions(kind, ref, action, admin_id);
        CREATE INDEX IF NOT EXISTS idx_actions_ts ON actions(ts, admin_id);
        CREATE INDEX IF NOT EXISTS idx_score_events_due ON score_events(status, next_retry);
        CREATE INDEX IF NOT EXISTS idx_equipment_units_state ON equipment_units(short, state, num);
        """)
    _ensure_revision_triggers()


REVISION_TABLES = (
    "users", "requests", "b626", "messages", "extra_items", "cat_blocks",
    "removed_items", "fav_sets", "reads", "actions", "extra_admins", "equipment_units",
)


def _ensure_revision_triggers() -> None:
    """Change the revision after every user-visible database mutation."""
    with db() as c:
        c.execute("INSERT OR IGNORE INTO meta(k, v) VALUES('_revision', '0')")
        for table in REVISION_TABLES:
            for op in ("INSERT", "UPDATE", "DELETE"):
                name = "revision_%s_%s" % (table, op.lower())
                c.execute(
                    "CREATE TRIGGER IF NOT EXISTS %s AFTER %s ON %s "
                    "BEGIN UPDATE meta SET v=CAST(v AS INTEGER)+1 WHERE k='_revision'; END"
                    % (name, op, table)
                )


def db_revision() -> str:
    with db() as c:
        row = c.execute("SELECT v FROM meta WHERE k='_revision'").fetchone()
    return row["v"] if row else "0"


def _migrate() -> None:
    """Догоняем схему на старых базах (ALTER TABLE, если колонок нет)."""
    adds = {
        "requests": {"dfrom_iso": "TEXT DEFAULT ''", "dto_iso": "TEXT DEFAULT ''",
                     "tfrom": "TEXT DEFAULT ''", "tto": "TEXT DEFAULT ''",
                     "created_ts": "REAL DEFAULT 0", "notif": "TEXT DEFAULT '{}'",
                     "escalated": "INTEGER DEFAULT 0", "nums": "TEXT DEFAULT '{}'",
                     "issued_by": "INTEGER", "returned_by": "INTEGER"},
        "b626": {"created_ts": "REAL DEFAULT 0", "notif": "TEXT DEFAULT '{}'"},
        "users": {"block_until": "TEXT DEFAULT ''"},
        "messages": {"role": "TEXT DEFAULT ''"},
    }
    # миграция для новой таблицы actions (полностью новые таблицы не мигрируют, но проверим на всякий случай)
    with db() as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "actions" not in tables:
            c.execute("CREATE TABLE actions(id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, kind TEXT, ref INTEGER, action TEXT, ts TEXT)")
        if "extra_admins" not in tables:
            c.execute("CREATE TABLE extra_admins(user_id INTEGER PRIMARY KEY, added_by INTEGER, added_ts TEXT)")
        if "score_events" not in tables:
            c.execute("""CREATE TABLE score_events(
              event_id TEXT PRIMARY KEY, happened_at TEXT, fio TEXT, admin_id INTEGER,
              kind TEXT, object_id TEXT, points TEXT, details TEXT DEFAULT '',
              status TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0,
              next_retry REAL DEFAULT 0, sent_at TEXT DEFAULT '', last_error TEXT DEFAULT '')""")
        if "equipment_units" not in tables:
            c.execute("""CREATE TABLE equipment_units(
              short TEXT, num INTEGER, serial TEXT DEFAULT '', note TEXT DEFAULT '',
              state TEXT DEFAULT 'ready', updated_at TEXT DEFAULT '', updated_by INTEGER,
              PRIMARY KEY(short, num))""")
    with db() as c:
        for table, cols in adds.items():
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            for k, v in cols.items():
                if k not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {k} {v}")
        c.executescript("""
        CREATE INDEX IF NOT EXISTS idx_requests_user_id ON requests(user_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_requests_status_dates ON requests(status, dfrom_iso, dto_iso);
        CREATE INDEX IF NOT EXISTS idx_b626_user_id ON b626(user_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_b626_status_day ON b626(status, day);
        CREATE INDEX IF NOT EXISTS idx_messages_ref ON messages(kind, ref, id);
        CREATE INDEX IF NOT EXISTS idx_actions_ref ON actions(kind, ref, action, admin_id);
        CREATE INDEX IF NOT EXISTS idx_actions_ts ON actions(ts, admin_id);
        CREATE INDEX IF NOT EXISTS idx_score_events_due ON score_events(status, next_retry);
        CREATE INDEX IF NOT EXISTS idx_equipment_units_state ON equipment_units(short, state, num);
        """)
    _ensure_revision_triggers()


# ---- каталог на сервере: общее кол-во по позициям (для проверки занятости) ----
TOTALS = {}
CATALOG_META = {}
BOOKING_LOCK = asyncio.Lock()


def _item_numbers(item: dict) -> list[int]:
    total = max(1, int(item.get("total") or 1))
    raw = item.get("numbers")
    if not isinstance(raw, list):
        return list(range(1, total + 1))
    numbers = []
    for value in raw:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in numbers:
            numbers.append(number)
    return sorted(numbers) or list(range(1, total + 1))


def load_catalog() -> None:
    """Загрузить каталог, включая допустимые номера экземпляров."""
    global TOTALS, CATALOG_META
    try:
        raw = (WEBAPP_DIR / "catalog.js").read_text(encoding="utf-8")
        data = json.loads(raw[raw.index("["):raw.rindex("]") + 1])
        items = [(c, i) for c in data for i in c["items"]]
        shorts = [item["short"] for _, item in items]
        if len(shorts) != len(set(shorts)):
            raise ValueError("короткие имена позиций должны быть уникальны")
        TOTALS = {
            item["short"]: int(item.get("total") or 1) for _, item in items
        }
        CATALOG_META = {
            item["short"]: {
                "cat": cat["cat"],
                "total": int(item.get("total") or 1),
                "level": item.get("level") or "",
                "numbers": _item_numbers(item),
            }
            for cat, item in items
        }
    except Exception as exc:
        TOTALS, CATALOG_META = {}, {}
        log.warning(
            "prototype/catalog.js не прочитан (%s) — проверка наличия ограничена",
            exc,
        )
    try:
        with db() as connection:
            for row in connection.execute(
                "SELECT cat, short, total, level FROM extra_items"
            ).fetchall():
                total = int(row["total"] or 1)
                TOTALS[row["short"]] = total
                CATALOG_META[row["short"]] = {
                    "cat": row["cat"],
                    "total": total,
                    "level": row["level"] or "",
                    "numbers": list(range(1, total + 1)),
                }
            for row in connection.execute(
                "SELECT short FROM removed_items"
            ).fetchall():
                TOTALS.pop(row["short"], None)
                CATALOG_META.pop(row["short"], None)
    except Exception as exc:
        log.warning("extra_items/removed_items не прочитаны: %s", exc)
    log.info("Каталог: %s позиций", len(TOTALS))


def sync_equipment_units() -> None:
    """Создать паспорта для всех допустимых номеров, не удаляя историю."""
    stamp = datetime.now(MSK).strftime("%Y-%m-%d %H:%M")
    with db() as connection:
        for short, meta in CATALOG_META.items():
            for number in meta.get("numbers") or []:
                connection.execute(
                    "INSERT OR IGNORE INTO equipment_units(short, num, updated_at) "
                    "VALUES(?,?,?)",
                    (short, number, stamp),
                )


def ready_numbers(short: str) -> list[int]:
    """Исправные номера из допустимого для позиции пула."""
    meta = CATALOG_META.get(short) or {}
    allowed = set(meta.get("numbers") or [])
    if not allowed:
        return []
    with db() as connection:
        rows = connection.execute(
            "SELECT num FROM equipment_units "
            "WHERE short=? AND state='ready' ORDER BY num",
            (short,),
        ).fetchall()
    return [row["num"] for row in rows if row["num"] in allowed]


def ready_capacity(short: str) -> int:
    """Фактическая ёмкость не превышает общее количество из таблицы."""
    meta = CATALOG_META.get(short) or {}
    return min(int(meta.get("total") or 0), len(ready_numbers(short)))


# ---- автосверка Media BMSTU по опубликованной таблице (лист 'список ребят') ----
_MB_CACHE = {"ts": 0.0, "names": None}


def _norm_name(s: str) -> str:
    return " ".join((s or "").lower().replace("ё", "е").split())

def clean_text(value, limit):
    """Очистить пользовательский текст от опасных символов и ограничить длину."""
    return str(value or "").replace("<", "").replace(">", "").replace('"', "").replace("'", "").strip()[:limit]


async def mb_members():
    """Множество нормализованных ФИО из таблицы; None - сверка выключена (URL не задан)."""
    if not MB_SHEET_URL:
        return None
    if _MB_CACHE["names"] is not None and time.time() - _MB_CACHE["ts"] < 600:
        return _MB_CACHE["names"]
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(MB_SHEET_URL, timeout=aiohttp.ClientTimeout(total=10)) as r:
                text = await r.text()
        names = set()
        for line in text.splitlines():
            for cell in line.split(","):
                n = _norm_name(cell.strip().strip('"'))
                if len(n.split()) >= 2:  # похоже на ФИО (повторы схлопнутся в set)
                    names.add(n)
        _MB_CACHE["names"] = names
        _MB_CACHE["ts"] = time.time()
        log.info("Список Media BMSTU: %s имён", len(names))
        return names
    except Exception as e:
        log.warning("MB_SHEET_URL не прочитан (%s) - регистрация MB уйдёт к старшим", e)
        return _MB_CACHE["names"] or set()


async def mb_ok(name: str) -> bool:
    members = await mb_members()
    if members is None:
        return True  # сверка выключена - MB авто-ok (как раньше)
    return _norm_name(name) in members


_ORG_CACHE = {"ts": 0.0, "names": None}


def org_members():
    """Множество нормализованных ФИО из локального файла организаций (bot/make_members.py); None - файла нет."""
    p = Path(ORG_MEMBERS_FILE)
    if not ORG_MEMBERS_FILE or not p.is_file():
        return None
    mtime = p.stat().st_mtime
    if _ORG_CACHE["names"] is not None and _ORG_CACHE["ts"] == mtime:
        return _ORG_CACHE["names"]
    names = set()
    try:
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            for cell in line.split(","):
                n = _norm_name(cell.strip().strip('"'))
                if len(n.split()) >= 2:
                    names.add(n)
    except Exception as e:
        log.warning("org_members не прочитан (%s)", e)
        return _ORG_CACHE["names"] or set()
    _ORG_CACHE["names"] = names
    _ORG_CACHE["ts"] = mtime
    log.info("Список организаций: %s имён", len(names))
    return names


def org_ok(name: str) -> bool:
    members = org_members()
    if members is None:
        return False  # файла нет - организации проверяет старший вручную (как раньше)
    return _norm_name(name) in members


# ---- справочник для автозаполнения по username ----
_DIR_CACHE = {"ts": 0.0, "data": None}


def directory() -> dict:
    """Словарь username -> {name, deps: [], role}. None - справочник не настроен."""
    p = Path(DIRECTORY_FILE)
    if not DIRECTORY_FILE or not p.is_file():
        return {}
    mtime = p.stat().st_mtime
    if _DIR_CACHE["data"] is not None and _DIR_CACHE["ts"] == mtime:
        return _DIR_CACHE["data"]
    data = {}
    try:
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            parts = line.split(";")
            if len(parts) >= 3:
                username = parts[0].strip()
                if not username:
                    continue
                name = parts[1].strip()
                deps = [d.strip() for d in parts[2].split(",") if d.strip()]
                role = parts[3].strip() if len(parts) > 3 else ""
                data[username] = {"name": name, "deps": deps, "role": role}
    except Exception as e:
        log.warning("directory не прочитан (%s)", e)
    _DIR_CACHE["data"] = data
    _DIR_CACHE["ts"] = mtime
    log.info("Справочник: %s записей", len(data))
    return data


_MEMBERS_CACHE = {
    "ts": 0.0,
    "by_name": None,
    "by_username": None,
    "error": "",
}


def _split_sheet_values(value: str) -> list[str]:
    return [
        part.strip()
        for part in str(value or "").split(",")
        if part.strip() and part.strip() != "-"
    ]


def _norm_username(value: str) -> str:
    value = str(value or "").strip()
    if "t.me/" in value.casefold():
        value = value.rstrip("/").rsplit("/", 1)[-1]
    return value.lstrip("@").strip().casefold()


def _member_rows(values: list[list]) -> list[dict]:
    if not values:
        return []
    headers = {str(value).strip(): index for index, value in enumerate(values[0])}
    required = {
        "ФИО", "ТГ", "Отделы Media BMSTU", "Роль Media BMSTU", "Организации"
    }
    missing = required - set(headers)
    if missing:
        raise RuntimeError(
            "В листе люди нет колонок: " + ", ".join(sorted(missing))
        )
    department_map = {"SMM": "СММ"}
    members = []
    for source in values[1:]:
        row = list(source) + [""] * len(headers)
        name = str(row[headers["ФИО"]]).strip()
        if not name:
            continue
        deps = [
            department_map.get(value, value)
            for value in _split_sheet_values(
                row[headers["Отделы Media BMSTU"]]
            )
        ]
        external_orgs = _split_sheet_values(row[headers["Организации"]])
        orgs = (["Media BMSTU"] if deps else []) + external_orgs
        role_label = str(
            row[headers["Роль Media BMSTU"]]
        ).strip().casefold()
        if role_label == "активист":
            role = "активист"
        elif role_label in ("стажёр", "стажер"):
            role = "стажёр"
        elif external_orgs:
            role = "СО/ССФ"
        else:
            role = ""
        members.append({
            "name": name,
            "telegram": str(row[headers["ТГ"]]).strip(),
            "orgs": list(dict.fromkeys(orgs)),
            "deps": list(dict.fromkeys(deps)),
            "role": role,
        })
    return members


def _build_member_directory(values: list[list]) -> dict[str, list[dict]]:
    by_name: dict[str, list[dict]] = {}
    for member in _member_rows(values):
        by_name.setdefault(_norm_name(member["name"]), []).append(member)
    return by_name


def _merge_members(matches: list[dict]) -> dict:
    role_order = {"": 0, "СО/ССФ": 1, "стажёр": 2, "активист": 3}
    merged = {
        "name": matches[0]["name"],
        "telegram": matches[0]["telegram"],
        "orgs": [],
        "deps": [],
        "role": "",
    }
    for member in matches:
        for key in ("orgs", "deps"):
            for value in member[key]:
                if value not in merged[key]:
                    merged[key].append(value)
        if role_order.get(member["role"], 0) > role_order.get(merged["role"], 0):
            merged["role"] = member["role"]
    if not merged["role"]:
        merged["role"] = (
            "активист" if "Media BMSTU" in merged["orgs"] else "СО/ССФ"
        )
    return merged


def _build_member_username_directory(values: list[list]) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = {}
    for member in _member_rows(values):
        username = _norm_username(member["telegram"])
        if username:
            grouped.setdefault(username, []).append(member)
    return {
        username: _merge_members(matches)
        for username, matches in grouped.items()
    }


def _members_snapshot(force: bool = False) -> dict[str, list[dict]]:
    if not MEMBERS_SHEET_ID:
        return {}
    if (
        not force
        and _MEMBERS_CACHE["by_name"] is not None
        and time.time() - _MEMBERS_CACHE["ts"] < 600
    ):
        return _MEMBERS_CACHE["by_name"]
    try:
        service = _google_service(readonly=True)
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=MEMBERS_SHEET_ID,
                range=_score_tab_range(MEMBERS_SHEET_TAB, "A:E"),
            )
            .execute()
        )
        values = result.get("values", [])
        by_name = _build_member_directory(values)
        by_username = _build_member_username_directory(values)
        _MEMBERS_CACHE.update({
            "ts": time.time(),
            "by_name": by_name,
            "by_username": by_username,
            "error": "",
        })
        log.info(
            "Лист люди: %s ФИО, %s Telegram-ников",
            len(by_name),
            len(by_username),
        )
        return by_name
    except Exception as exc:
        _MEMBERS_CACHE["error"] = str(exc)
        if _MEMBERS_CACHE["by_name"] is not None:
            log.warning(
                "Лист люди временно недоступен, используется кэш: %s", exc
            )
            return _MEMBERS_CACHE["by_name"]
        raise


def _lookup_member_sync(name: str, force: bool = False) -> dict:
    if not MEMBERS_SHEET_ID:
        return {"status": "disabled", "member": None}
    try:
        matches = _members_snapshot(force).get(_norm_name(name), [])
    except Exception as exc:
        return {"status": "error", "member": None, "error": str(exc)}
    if not matches:
        return {"status": "not_found", "member": None}
    if len(matches) != 1:
        return {"status": "duplicate", "member": None}
    return {"status": "found", "member": matches[0]}


def _lookup_member_by_username_sync(
    username: str, force: bool = False
) -> dict:
    if not MEMBERS_SHEET_ID:
        return {"status": "disabled", "member": None}
    normalized = _norm_username(username)
    if not normalized:
        return {"status": "no_username", "member": None}
    try:
        _members_snapshot(force)
        member = (_MEMBERS_CACHE["by_username"] or {}).get(normalized)
    except Exception as exc:
        return {"status": "error", "member": None, "error": str(exc)}
    if not member:
        return {"status": "not_found", "member": None}
    return {"status": "found", "member": member}


async def lookup_member(name: str, force: bool = False) -> dict:
    return await asyncio.to_thread(_lookup_member_sync, name, force)


async def lookup_member_by_username(
    username: str, force: bool = False
) -> dict:
    return await asyncio.to_thread(
        _lookup_member_by_username_sync, username, force
    )


ACTIVE_STS = ("new", "curator", "approved", "issued", "ret")


def busy_map(d1: str, d2: str, exclude_rid: int = 0) -> dict:
    """Сколько единиц каждой позиции занято на пересечении с [d1, d2] (ISO-даты)."""
    out = {}
    if not d1 or not d2:
        return out
    with db() as c:
        rows = c.execute(
            "SELECT id, items FROM requests WHERE status IN (%s) AND dfrom_iso<>'' "
            "AND dfrom_iso<=? AND dto_iso>=? AND id<>?" % ",".join("?" * len(ACTIVE_STS)),
            (*ACTIVE_STS, d2, d1, exclude_rid)).fetchall()
    for r in rows:
        for s, q in json.loads(r["items"]):
            out[s] = out.get(s, 0) + int(q)
    return out


def check_availability(items, d1, d2, exclude_rid=0):
    """None, если всё свободно; иначе текст ошибки."""
    if not TOTALS or not d1 or not d2:
        return None
    busy = busy_map(d1, d2, exclude_rid)
    bad = [s for s, q in items
           if s in CATALOG_META and busy.get(s, 0) + int(q) > ready_capacity(s)]
    if bad:
        return "На выбранные даты не хватает исправных экземпляров: " + ", ".join(bad) + ". Уберите позиции или смените даты."
    return None


def _parse_iso_day(value):
    try: return datetime.strptime(value or "", "%Y-%m-%d").date()
    except (TypeError, ValueError): return None


def _valid_slot(value):
    try: parsed = datetime.strptime(value or "", "%H:%M")
    except (TypeError, ValueError): return False
    return parsed.minute in (0, 30) and 9 <= parsed.hour <= 21


def validate_request_window(d1, d2, t1, t2):
    first, last = _parse_iso_day(d1), _parse_iso_day(d2)
    if not first or not last or not _valid_slot(t1) or not _valid_slot(t2): return "Укажите корректные даты и время с шагом 30 минут (09:00–21:30)."
    if last < first or (last == first and t2 <= t1): return "Дата возврата должна быть позже даты получения."
    if (last - first).days > 61: return "Максимальный срок бронирования — 62 дня."
    if first < datetime.now(MSK).date() + timedelta(days=2): return "Оборудование можно забронировать минимум за 2 дня до получения."
    if first.weekday() == 6 or last.weekday() == 6: return "Получение и возврат в воскресенье запрещены."
    return None


def _active_cat_blocks():
    with db() as c: rows = c.execute("SELECT cat, until FROM cat_blocks").fetchall()
    return {r["cat"] for r in rows if not r["until"] or not _cat_until_passed(r["until"])}


def validate_items(uid, raw_items, media=False, allow_restricted=False):
    if not isinstance(raw_items, list) or not raw_items: return None, "Добавьте хотя бы одну позицию в заявку."
    if len(raw_items) > 50: return None, "В одной заявке может быть не больше 50 позиций."
    blocks, user, out, seen = _active_cat_blocks(), get_user(uid), [], set()
    role = user["role"] if user else ""
    for pair in raw_items:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2: return None, "Некорректный формат позиции."
        short, qty = pair
        if not isinstance(short, str): return None, "Некорректное название позиции."
        short = short.strip()
        if not short or short in seen or short not in CATALOG_META: return None, "В заявке есть неизвестная или повторяющаяся позиция."
        if isinstance(qty, bool): return None, "Некорректное количество экземпляров."
        try: qty = int(qty)
        except (TypeError, ValueError): return None, "Некорректное количество экземпляров."
        meta = CATALOG_META[short]
        if qty < 1 or qty > meta["total"]: return None, "Количество экземпляров превышает доступное в каталоге."
        if meta["cat"] in blocks: return None, "Категория «%s» временно недоступна." % meta["cat"]
        if meta["level"] == "none":
            return None, "Эта позиция сейчас не выдаётся."
        if not allow_restricted:
            if meta["level"] == "глава" and not is_senior(uid): return None, "Эта позиция доступна только старшим администраторам."
            if meta["level"] == "акт" and role not in ("активист", "production") and not media: return None, "Эта позиция доступна активистам или ответственному за медиа."
        out.append([short, qty]); seen.add(short)
    return out, None


def _slot_bounds(slot):
    try:
        a, b = (slot or "").replace("–", "-").replace("—", "-").split("-", 1); a, b = a.strip(), b.strip()
        return (a, b) if _valid_slot(a) and _valid_slot(b) and b > a else None
    except (AttributeError, ValueError): return None


def validate_626_window(day, slot):
    date, bounds = _parse_iso_day(day), _slot_bounds(slot)
    if not date or not bounds: return None, "Укажите корректную дату и время для 626 (09:00–21:30, шаг 30 минут)."
    if date < datetime.now(MSK).date() + timedelta(days=2): return None, "Аудиторию 626 можно забронировать минимум за 2 дня."
    return bounds[0] + "–" + bounds[1], None


def _numbers_from_value(value):
    vals, out = (value if isinstance(value, list) else [value]), []
    for value in vals:
        try: out.append(int(value))
        except (TypeError, ValueError): pass
    return out


def used_numbers(short, d1, d2, exclude_rid=0):
    used = set()
    with db() as c:
        rows = c.execute("SELECT nums FROM requests WHERE status IN (%s) AND dfrom_iso<>'' AND dfrom_iso<=? AND dto_iso>=? AND id<>?" % ",".join("?" * len(ACTIVE_STS)), (*ACTIVE_STS, d2, d1, exclude_rid)).fetchall()
    for row in rows:
        try: nums = json.loads(row["nums"] or "{}")
        except (TypeError, ValueError): nums = {}
        used.update(_numbers_from_value(nums.get(short)))
    return used


def assign_numbers(items, d1, d2, exclude_rid=0, preferred=None):
    """Назначить только исправные и свободные номера, проверив выбор администратора."""
    result, preferred = {}, preferred or {}
    for short, qty in items:
        used = used_numbers(short, d1, d2, exclude_rid)
        free = [num for num in ready_numbers(short) if num not in used]
        wanted = _numbers_from_value(preferred.get(short))
        chosen = wanted if len(wanted) == int(qty) else free[:int(qty)]
        if len(set(chosen)) != int(qty) or any(num not in free for num in chosen):
            return None, "Не хватает исправных свободных экземпляров позиции «%s»." % short
        result[short] = chosen
    return result, None


def dayload_map() -> dict:
    """Сколько активных заявок пересекает каждый день (для подсветки календаря)."""
    out = {}
    with db() as c:
        rows = c.execute(
            "SELECT dfrom_iso, dto_iso FROM requests WHERE status IN (%s) AND dfrom_iso<>''"
            % ",".join("?" * len(ACTIVE_STS)), ACTIVE_STS).fetchall()
    for r in rows:
        try:
            d = datetime.strptime(r["dfrom_iso"], "%Y-%m-%d")
            end = datetime.strptime(r["dto_iso"], "%Y-%m-%d")
        except ValueError:
            continue
        for _ in range(62):  # защита от кривых диапазонов
            iso = d.strftime("%Y-%m-%d")
            out[iso] = out.get(iso, 0) + 1
            if d >= end:
                break
            d += timedelta(days=1)
    return out


def slot_expand(slot: str):
    """Развернуть интервал 626 по получасам; результат включает начало."""
    bounds = _slot_bounds(slot)
    if not bounds: return []
    t, end = datetime.strptime(bounds[0], "%H:%M"), datetime.strptime(bounds[1], "%H:%M")
    out = []
    while t < end:
        out.append(t.strftime("%H:%M")); t += timedelta(minutes=30)
    return out


def busy626_map() -> dict:
    """{день: [занятые получасовые слоты]} по активным броням 626."""
    out = {}
    with db() as c:
        rows = c.execute("SELECT day, slot FROM b626 WHERE status IN ('new','approved')").fetchall()
    for r in rows:
        out.setdefault(r["day"], []).extend(slot_expand(r["slot"]))
    return out


def parse_dt(iso: str, hm: str):
    try:
        return datetime.strptime(iso + " " + (hm or "23:59"), "%Y-%m-%d %H:%M").replace(tzinfo=MSK)
    except Exception:
        return None


def now_str() -> str:
    return datetime.now(MSK).strftime("%d.%m, %H:%M")


def get_user(uid: int):
    with db() as c:
        return c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def is_senior(uid: int) -> bool:
    return uid in SENIOR_ADMIN_IDS


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS or uid in SENIOR_ADMIN_IDS or uid in EXTRA_ADMIN_IDS


# ================= initData =================

def check_init_data(raw: str):
    """Проверка подписи Telegram WebApp initData. Возвращает dict user или None."""
    try:
        data = dict(parse_qsl(raw, keep_blank_values=True))
        got_hash = data.pop("hash", "")
        dcs = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, got_hash):
            return None
        if time.time() - int(data.get("auth_date", "0")) > 86400:
            return None
        return json.loads(data["user"])
    except Exception:
        return None


def touch_user(tg_user: dict):
    """Обновить username/фото/короткое имя из initData при каждом входе."""
    uid = tg_user["id"]
    uname = tg_user.get("username", "")
    photo = tg_user.get("photo_url", "")
    with db() as c:
        if not c.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
            c.execute("INSERT INTO users(id, username, photo, created) VALUES(?,?,?,?)",
                      (uid, uname, photo, now_str()))
        else:
            c.execute("""UPDATE users SET username=?, photo=?
                         WHERE id=? AND (username<>? OR photo<>?)""",
                      (uname, photo, uid, uname, photo))


# ================= Сериализация для фронта =================

def _disp_user(uid) -> str:
    u = get_user(uid) if uid else None
    if not u:
        return "админ"
    return ("@" + u["username"]) if u["username"] else (u["name"] or "админ")


def _disp_user_from(users: dict, uid) -> str:
    u = users.get(uid) if uid else None
    if not u:
        return "админ"
    return ("@" + u["username"]) if u["username"] else (u["name"] or "админ")


def _shape_chat(rows, owner_id: int, curator_id=None):
    out = []
    for m in rows:
        role = m["role"] or ""
        if m["sender"] == owner_id:
            label = "Пользователь"
        elif role == "senior":            # красным - только если писали из панели старшего
            label = "Старший"
        elif curator_id and m["sender"] == curator_id:
            label = "Куратор"
        else:
            label = "Админ"
        out.append({"who": "me" if m["sender"] == owner_id else "them", "text": m["text"], "tm": m["tm"],
                    "senior": role == "senior", "label": label})
    return out


def _unread_from(rows, seen: int, viewer: int) -> int:
    return sum(1 for row in rows if row["id"] > seen and row["sender"] != viewer)


def shape_req(r, viewer: int, users=None, messages=None, seen=None) -> dict:
    users = users or {}
    messages = messages or {}
    seen = seen or {}
    author = users.get(r["user_id"]) if users else get_user(r["user_id"])
    deps = json.loads(author["deps"]) if author else []
    can_chat = viewer == r["user_id"] or viewer == r["curator"] or is_senior(viewer)
    chat_rows = messages.get(("req", r["id"]), []) if can_chat else []
    return {
        "id": r["id"], "me": r["user_id"] == viewer, "curMe": r["curator"] == viewer,
        "author": (author["name"] or _disp_user_from(users, r["user_id"])) if author else "?",
        "dep": deps[0] if deps else "",
        "items": json.loads(r["items"]), "event": r["event"], "comment": r["comment"],
        "from": r["dfrom"], "to": r["dto"], "status": r["status"],
        "d1Iso": r["dfrom_iso"], "d2Iso": r["dto_iso"], "t1": r["tfrom"], "t2": r["tto"],
        "curator": _disp_user_from(users, r["curator"]) if r["curator"] else None,
        "pwUsed": bool(r["pw"]), "media": bool(r["media"]), "escalated": bool(r["escalated"]),
        "lateNote": late_note(r),
        "takenAt": r["taken_at"], "returnedAt": r["returned_at"],
        "history": json.loads(r["history"]),
        "chat": _shape_chat(chat_rows, r["user_id"], r["curator"]) if can_chat else [],
        "unread": _unread_from(chat_rows, seen.get(("req", r["id"]), 0), viewer) if can_chat else 0,
        "nums": json.loads(r["nums"] or "{}") if is_admin(viewer) else {},
        "issuedBy": _disp_user_from(users, r["issued_by"]) if r["issued_by"] else None,
        "returnedBy": _disp_user_from(users, r["returned_by"]) if r["returned_by"] else None,
    }


def shape_626(b, viewer: int, users=None, messages=None, seen=None) -> dict:
    users = users or {}
    messages = messages or {}
    seen = seen or {}
    author = users.get(b["user_id"]) if users else get_user(b["user_id"])
    can_chat = viewer == b["user_id"] or viewer == b["curator"] or is_senior(viewer)
    chat_rows = messages.get(("626", b["id"]), []) if can_chat else []
    return {
        "id": b["id"], "me": b["user_id"] == viewer, "curMe": b["curator"] == viewer,
        "author": (author["name"] or _disp_user_from(users, b["user_id"])) if author else "?",
        "when": b["day"], "slot": b["slot"], "goal": b["goal"],
        "needs": json.loads(b["needs"]), "status": b["status"],
        "curator": _disp_user_from(users, b["curator"]) if b["curator"] else None,
        "history": json.loads(b["history"]),
        "chat": _shape_chat(chat_rows, b["user_id"], b["curator"]) if can_chat else [],
        "unread": _unread_from(chat_rows, seen.get(("626", b["id"]), 0), viewer) if can_chat else 0,
    }


def _block_expired(until: str) -> bool:
    if not until:
        return False
    try:
        return datetime.now(MSK).date() >= datetime.strptime(until, "%Y-%m-%d").date()
    except ValueError:
        return False


def _cat_until_passed(s: str) -> bool:
    """Истёк ли срок блокировки категории. Понимает "YYYY-MM-DD HH:MM" (новый формат, час-точный)
    и старые ISO/ДД.ММ.ГГГГ без времени (только по дате, для обратной совместимости)."""
    s = (s or "").strip()
    try:
        return datetime.now(MSK) >= datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=MSK)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.now(MSK).date() > datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return False


def unit_summary() -> list:
    """Краткие паспорта только для позиций, которые существуют в текущем каталоге."""
    with db() as c:
        rows = c.execute("SELECT * FROM equipment_units ORDER BY short COLLATE NOCASE, num").fetchall()
    return [{
        "short": row["short"], "num": row["num"], "serial": row["serial"],
        "note": row["note"], "state": row["state"], "updatedAt": row["updated_at"],
        "updatedBy": _disp_user(row["updated_by"]) if row["updated_by"] else "система",
    } for row in rows
      if row["short"] in CATALOG_META
      and row["num"] in CATALOG_META[row["short"]].get("numbers", [])]


def unit_passport(short: str, num: int):
    with db() as c:
        unit = c.execute(
            "SELECT * FROM equipment_units WHERE short=? AND num=?", (short, num)
        ).fetchone()
        reqs = c.execute(
            "SELECT * FROM requests WHERE nums<>'{}' ORDER BY id DESC"
        ).fetchall()
    if (not unit or short not in CATALOG_META
            or num not in CATALOG_META[short].get("numbers", [])):
        return None
    history = []
    for row in reqs:
        try:
            nums = json.loads(row["nums"] or "{}")
        except (TypeError, ValueError):
            nums = {}
        if num not in _numbers_from_value(nums.get(short)):
            continue
        history.append({
            "requestId": row["id"], "user": _disp_user(row["user_id"]),
            "from": row["dfrom"], "to": row["dto"], "status": row["status"],
            "issuedBy": _disp_user(row["issued_by"]) if row["issued_by"] else "—",
            "returnedBy": _disp_user(row["returned_by"]) if row["returned_by"] else "—",
            "takenAt": row["taken_at"] or "—", "returnedAt": row["returned_at"] or "—",
        })
    return {
        "short": unit["short"], "num": unit["num"], "serial": unit["serial"],
        "note": unit["note"], "state": unit["state"], "updatedAt": unit["updated_at"],
        "updatedBy": _disp_user(unit["updated_by"]) if unit["updated_by"] else "система",
        "history": history,
    }


def boot_payload(uid: int) -> dict:
    with db() as c:
        users = {row["id"]: row for row in c.execute("SELECT * FROM users").fetchall()}
    u = users.get(uid)
    if u and u["verified"] == "blocked" and _block_expired(u["block_until"]):
        with db() as c:  # срок блокировки истёк - снимаем сами
            c.execute("UPDATE users SET verified='ok', block_reason='', block_until='' WHERE id=?", (uid,))
        with db() as c:
            users = {row["id"]: row for row in c.execute("SELECT * FROM users").fetchall()}
        u = users.get(uid)
    adm, sen = is_admin(uid), is_senior(uid)
    with db() as c:
        if adm:
            reqs = c.execute("SELECT * FROM requests ORDER BY id DESC").fetchall()
            b626s = c.execute("SELECT * FROM b626 ORDER BY id DESC").fetchall()
        else:
            reqs = c.execute("SELECT * FROM requests WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()
            b626s = c.execute("SELECT * FROM b626 WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()
        message_rows = c.execute("SELECT * FROM messages ORDER BY id").fetchall()
        read_rows = c.execute("SELECT kind, ref, seen FROM reads WHERE user_id=?", (uid,)).fetchall()
        extra_items = c.execute("SELECT * FROM extra_items ORDER BY id").fetchall()
        cat_blocks = c.execute("SELECT * FROM cat_blocks").fetchall()
        removed_items = c.execute("SELECT short FROM removed_items").fetchall()
        fav_sets = c.execute("SELECT * FROM fav_sets WHERE user_id=? ORDER BY id", (uid,)).fetchall()
        pend = c.execute("SELECT * FROM users WHERE verified='pending'").fetchall() if sen else []
        allu = c.execute("SELECT * FROM users WHERE agreed=1 ORDER BY name").fetchall() if sen else []
    messages = {}
    for row in message_rows:
        messages.setdefault((row["kind"], row["ref"]), []).append(row)
    seen = {(row["kind"], row["ref"]): row["seen"] for row in read_rows}
    out = {
        "ok": True, "isAdmin": adm, "isSenior": sen,
        "revision": db_revision(),
        "features": {"productionRole": ENABLE_PRODUCTION_ROLE},
        "registered": bool(u and u["agreed"]),
        "verified": u["verified"] if u else "none",
        "blockReason": (u["block_reason"] if u else "") or "",
        "requests": [shape_req(r, uid, users, messages, seen) for r in reqs],
        "bookings626": [shape_626(b, uid, users, messages, seen) for b in b626s],
        "dayload": dayload_map(),
        "busy626": busy626_map(),
    }
    out["extraItems"] = [{"cat": r["cat"], "short": r["short"], "full": r["full"],
                          "total": r["total"], "level": r["level"] or None} for r in extra_items]
    out["catBlocks"] = {r["cat"]: {"until": r["until"], "term": r["term"]} for r in cat_blocks}
    out["removedItems"] = [r["short"] for r in removed_items]
    out["favSets"] = [{"id": r["id"], "name": r["name"], "items": json.loads(r["items"])} for r in fav_sets]
    if adm:
        out["equipmentUnits"] = unit_summary()
    if u:
        orgs = json.loads(u["orgs"])
        out["profile"] = {
            "name": u["name"], "short": short_name(u["name"]) or _disp_user_from(users, uid),
            "tg": ("@" + u["username"]) if u["username"] else "",
            "photo": u["photo"], "orgs": orgs, "deps": json.loads(u["deps"]),
            "status": u["role"],
        }
    if sen:
        out["verifQueue"] = [{
            "id": p["id"], "name": p["name"] or _disp_user_from(users, p["id"]),
            "org": ", ".join(json.loads(p["orgs"])), "role": p["role"],
            "tg": "@" + p["username"] if p["username"] else "id " + str(p["id"]),
        } for p in pend]
        out["users"] = [{
            "id": x["id"], "name": x["name"], "org": ", ".join(json.loads(x["orgs"])) or "-",
            "dep": ", ".join(json.loads(x["deps"])) or "-", "role": x["role"],
            "tg": "@" + x["username"] if x["username"] else "", "ok": x["verified"] == "ok",
            "verified": x["verified"], "reason": x["block_reason"] or "",
        } for x in allu]
    return out


def short_name(full: str) -> str:
    p = (full or "").split()
    return (p[1] + " " + p[0]) if len(p) >= 2 else full


# ================= Уведомления =================

async def notify(uid: int, text: str) -> None:
    if bot is None or not uid:
        return
    try:
        await bot.send_message(uid, text)
    except Exception as e:
        log.warning("notify %s failed: %s", uid, e)


async def notify_seniors(text: str) -> None:
    for uid in SENIOR_ADMIN_IDS:
        await notify(uid, text)


def app_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=tx.APP_BUTTON_TEXT, web_app=WebAppInfo(url=WEBAPP_URL)),
    ]])


def deeplink_kb() -> InlineKeyboardMarkup:
    """Для групп/каналов web_app-кнопки запрещены - даём t.me-ссылку."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=tx.DEEPLINK_BUTTON_TEXT, url=f"https://t.me/{BOT_USERNAME}?startapp"),
    ]])


ST_LABEL = tx.STATUS_LABELS


def late_note(r) -> str:
    """Пометка для команды: поздняя выдача/возврат (сб после 18:00) - команда может отказать."""
    notes = []
    try:
        if r["dto_iso"] and datetime.strptime(r["dto_iso"], "%Y-%m-%d").weekday() == 5 and (r["tto"] or "") >= "18:00":
            notes.append("поздний возврат (сб после 18:00)")
    except (ValueError, KeyError):
        pass
    try:
        if r["dfrom_iso"] and datetime.strptime(r["dfrom_iso"], "%Y-%m-%d").weekday() == 5 and (r["tfrom"] or "") >= "18:00":
            notes.append("поздняя выдача (сб после 18:00)")
    except (ValueError, KeyError):
        pass
    return "; ".join(notes)


def req_card_text(r) -> str:
    author = get_user(r["user_id"])
    return tx.request_card_message(
        r["id"], r["status"], author["name"] if author else "",
        _disp_user(r["user_id"]), r["dfrom"], r["dto"], r["event"],
        json.loads(r["items"]), r["comment"], late_note(r),
        _disp_user(r["curator"]) if r["curator"] else "",
    )


def b626_card_text(b) -> str:
    author = get_user(b["user_id"])
    return tx.studio_card_message(
        b["id"], b["status"], author["name"] if author else "",
        _disp_user(b["user_id"]), b["day"], b["slot"], b["goal"],
        json.loads(b["needs"]), _disp_user(b["curator"]) if b["curator"] else "",
    )


async def send_or_update_card(table: str, row) -> None:
    """Карточка в админ-канале: создаётся при новой заявке, редактируется при смене статуса."""
    if not ADMIN_CHAT_ID or bot is None:
        return
    text = req_card_text(row) if table == "requests" else b626_card_text(row)
    try:
        if row["admin_msg"]:
            await bot.edit_message_text(
                text, chat_id=ADMIN_CHAT_ID, message_id=row["admin_msg"],
                reply_markup=deeplink_kb(), parse_mode="MarkdownV2",
            )
        else:
            m = await bot.send_message(
                ADMIN_CHAT_ID, text, reply_markup=deeplink_kb(), parse_mode="MarkdownV2",
            )
            with db() as c:
                c.execute(f"UPDATE {table} SET admin_msg=? WHERE id=?", (m.message_id, row["id"]))
    except Exception as e:
        log.warning("admin card failed: %s", e)


# ================= API =================

def jerr(msg: str, status: int = 400) -> web.Response:
    return web.json_response({"error": msg}, status=status)


async def sse_broadcast() -> None:
    dead = []
    for queue in tuple(SSE_CLIENTS):
        try:
            if queue.empty():
                queue.put_nowait(db_revision())
        except (asyncio.QueueFull, RuntimeError):
            dead.append(queue)
    for queue in dead:
        SSE_CLIENTS.discard(queue)


def auth(handler):
    async def wrapped(request: web.Request):
        before = db_revision()
        body = await request.json()
        tg_user = check_init_data(body.get("initData", ""))
        if not tg_user and DEV_USER_ID:
            tg_user = {"id": DEV_USER_ID, "username": "dev", "first_name": "Dev"}
        if not tg_user:
            return jerr("Не удалось проверить подпись Telegram. Откройте приложение из Telegram.", 401)
        touch_user(tg_user)
        response = await handler(request, body, tg_user["id"])
        if db_revision() != before:
            await sse_broadcast()
        return response
    return wrapped


PHOTO_MAX = 5


def _decode_photos(photos) -> list:
    """base64 data-URL с фронта -> список bytes. На диск НЕ пишем (фото не хранятся на сервере)."""
    import base64
    out = []
    for p in (photos or [])[:PHOTO_MAX]:
        try:
            raw = base64.b64decode(p.split(",", 1)[1] if "," in p else p)
            if len(raw) > 4 * 1024 * 1024:
                continue
            out.append(raw)
        except Exception as e:
            log.warning("photo decode failed: %s", e)
    return out


async def _send_blobs(chat_id: int, blobs, caption: str, parse_mode=None) -> None:
    """Список bytes -> в чат одним сообщением (media group), подпись на первом."""
    if not chat_id or bot is None or not blobs:
        return
    try:
        if len(blobs) == 1:
            await bot.send_photo(
                chat_id, BufferedInputFile(blobs[0], tx.PHOTO_FILENAME),
                caption=caption or None, parse_mode=parse_mode,
            )
        else:
            media = [InputMediaPhoto(media=BufferedInputFile(b, f"photo{i + 1}.jpg"),
                                     caption=(caption if (i == 0 and caption) else None),
                                     parse_mode=(parse_mode if i == 0 else None))
                     for i, b in enumerate(blobs)]
            await bot.send_media_group(chat_id, media=media)
    except Exception as e:
        log.warning("send_photos %s failed: %s", chat_id, e)


async def send_photos_b64(chat_id: int, photos, caption: str) -> None:
    """Фото (base64 с фронта) -> в чат, без хранения на сервере."""
    await _send_blobs(chat_id, _decode_photos(photos), caption)


@auth
async def api_me(request, body, uid):
    started = time.perf_counter()
    response = web.json_response(boot_payload(uid))
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["Server-Timing"] = "boot;dur=%.1f" % elapsed_ms
    if elapsed_ms >= 300:
        log.warning("slow /api/me for %s: %.1f ms", uid, elapsed_ms)
    return response


@auth
async def api_revision(request, body, uid):
    return web.json_response({"ok": True, "revision": db_revision()})


async def api_events(request: web.Request):
    """Авторизованный SSE-сигнал: клиент сам проверяет revision и запрашивает /api/me."""
    tg_user = check_init_data(request.query.get("initData", ""))
    if not tg_user and DEV_USER_ID:
        tg_user = {"id": DEV_USER_ID, "username": "dev", "first_name": "Dev"}
    if not tg_user:
        raise web.HTTPUnauthorized(text="Telegram initData required")
    touch_user(tg_user)
    response = web.StreamResponse(status=200, headers={
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })
    await response.prepare(request)
    queue = asyncio.Queue(maxsize=1)
    SSE_CLIENTS.add(queue)
    try:
        await response.write(("event: ready\ndata: %s\n\n" % db_revision()).encode())
        while True:
            try:
                revision = await asyncio.wait_for(queue.get(), timeout=20)
                await response.write(("event: change\ndata: %s\n\n" % revision).encode())
            except asyncio.TimeoutError:
                await response.write(b": keepalive\n\n")
    except (ConnectionResetError, asyncio.CancelledError, RuntimeError):
        pass
    finally:
        SSE_CLIENTS.discard(queue)
    return response


def _apply_sheet_member(uid: int, member: dict) -> None:
    with db() as connection:
        connection.execute(
            "UPDATE users SET name=?, orgs=?, deps=?, agreed=1, "
            "verified='ok', role=? WHERE id=?",
            (
                member["name"],
                json.dumps(member["orgs"], ensure_ascii=False),
                json.dumps(member["deps"], ensure_ascii=False),
                member["role"],
                uid,
            ),
        )


@auth
async def api_agree(request, body, uid):
    user = get_user(uid)
    result = await lookup_member_by_username(
        user["username"] if user else ""
    )
    if result["status"] == "found":
        _apply_sheet_member(uid, result["member"])
        payload = boot_payload(uid)
        payload["autoRegistered"] = True
        payload["memberStatus"] = "found"
        return web.json_response(payload)
    payload = boot_payload(uid)
    payload["autoRegistered"] = False
    payload["memberStatus"] = result["status"]
    return web.json_response(payload)


@auth
async def api_member_lookup(request, body, uid):
    name = clean_text(body.get("name"), 80)
    if len(name.split()) < 3:
        return jerr("Введите ФИО полностью — фамилия, имя и отчество.")
    result = await lookup_member(name)
    messages = {
        "found": "Нашли вас в списке. Данные заполнятся автоматически.",
        "not_found": "ФИО не найдено. Заполните данные вручную.",
        "duplicate": "Найдено несколько одинаковых ФИО. Нужна ручная проверка.",
        "disabled": "Лист людей не подключён. Заполните данные вручную.",
        "error": "Лист людей временно недоступен. Заполните данные вручную.",
    }
    return web.json_response({
        "ok": True,
        "status": result["status"],
        "found": result["status"] == "found",
        "member": result.get("member"),
        "message": messages[result["status"]],
    })


@auth
async def api_register(request, body, uid):
    name = clean_text(body.get("name"), 80)
    if not name:
        return jerr("Укажите ФИО — без него регистрация невозможна.")
    if len(name.split()) < 3:
        return jerr(
            "Введите ФИО полностью — фамилия, имя и отчество (три слова)."
        )

    member_result = await lookup_member(name)
    member = member_result.get("member")
    if member:
        name = member["name"]
        orgs = member["orgs"]
        deps = member["deps"]
        want_role = member["role"]
    else:
        orgs = [clean_text(value, 100) for value in (body.get("orgs") or [])]
        deps = [clean_text(value, 40) for value in (body.get("deps") or [])]
        if not orgs:
            return jerr("Выберите организацию.")
        if "Media BMSTU" in orgs and not deps:
            return jerr("Выберите хотя бы один отдел Media BMSTU.")
        want_role = str(body.get("role") or "").strip()

    allowed_roles = ("активист", "стажёр", "СО/ССФ")
    if want_role not in allowed_roles:
        want_role = "активист" if "Media BMSTU" in orgs else "СО/ССФ"

    user = get_user(uid)
    verified = user["verified"]
    role = user["role"]
    name_changed = _norm_name(name) != _norm_name(user["name"] or "")

    if member:
        verified = "ok"
        role = want_role
    else:
        dir_info = (
            directory().get(user["username"] or "")
            if user and user["username"]
            else None
        )
        if dir_info:
            if dir_info.get("role") in allowed_roles:
                role = dir_info["role"]
            if "Media BMSTU" in orgs and dir_info.get("deps"):
                deps = dir_info["deps"]
        if verified != "ok" or name_changed:
            if MEMBERS_SHEET_ID and member_result["status"] in (
                "not_found", "duplicate"
            ):
                found = False
            else:
                found = (
                    await mb_ok(name)
                    if "Media BMSTU" in orgs
                    else org_ok(name)
                )
            verified = "ok" if found else "pending"
            role = want_role or role
        elif want_role:
            role = want_role

    with db() as connection:
        connection.execute(
            "UPDATE users SET name=?, orgs=?, deps=?, agreed=1, "
            "verified=?, role=? WHERE id=?",
            (
                name,
                json.dumps(orgs, ensure_ascii=False),
                json.dumps(deps if "Media BMSTU" in orgs else [], ensure_ascii=False),
                verified,
                role,
                uid,
            ),
        )
    if verified == "pending":
        reason = {
            "not_found": "ФИО не найдено в листе люди",
            "duplicate": "в листе люди несколько одинаковых ФИО",
        }.get(member_result["status"], "нужна ручная проверка")
        text = (
            f"⏳ Заявка на верификацию: {name} ({_disp_user(uid)}), "
            f"орг.: {', '.join(orgs)} · {reason}. Решение — в приложении."
        )
        if ADMIN_CHAT_ID and bot is not None:
            try:
                await bot.send_message(ADMIN_CHAT_ID, text)
            except Exception as exc:
                log.warning("verif card failed: %s", exc)
                await notify_seniors(text)
        else:
            await notify_seniors(text)
    return web.json_response(boot_payload(uid))


@auth
async def api_req_create(request, body, uid):
    u = get_user(uid)
    if not (u and u["agreed"] and u["verified"] == "ok"):
        return jerr("Сначала завершите регистрацию и верификацию.")
    d1, d2, t1, t2 = body.get("d1") or "", body.get("d2") or "", body.get("t1") or "", body.get("t2") or ""
    err = validate_request_window(d1, d2, t1, t2)
    if err:
        return jerr(err)
    items, err = validate_items(uid, body.get("items"), bool(body.get("media")))
    if err:
        return jerr(err)
    event = clean_text(body.get("event"), 100)
    if not event:
        return jerr("Укажите название мероприятия.")
    hist = [["new", now_str()]]
    async with BOOKING_LOCK:
        err = check_availability(items, d1, d2)
        if err:
            return jerr(err)
        with db() as c:
            cur = c.execute(
                "INSERT INTO requests(user_id, items, dfrom, dto, event, comment, media, pw, history, dfrom_iso, dto_iso, tfrom, tto, created_ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (uid, json.dumps(items, ensure_ascii=False), body.get("from", ""), body.get("to", ""), event,
                 clean_text(body.get("comment"), 500), int(bool(body.get("media"))), int(bool(body.get("pw"))),
                 json.dumps(hist, ensure_ascii=False), d1, d2, t1, t2, time.time()))
            rid = cur.lastrowid
            row = c.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    await send_or_update_card("requests", row)
    return web.json_response(boot_payload(uid))

@auth
async def api_req_update(request, body, uid):
    rid = body.get("id")
    with db() as c:
        r = c.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    if not r:
        return jerr("Заявка не найдена.", 404)
    if r["user_id"] != uid or r["status"] not in ("new", "curator"):
        return jerr("Эту заявку уже нельзя изменить или отменить.")
    d1, d2, t1, t2 = body.get("d1") or "", body.get("d2") or "", body.get("t1") or "", body.get("t2") or ""
    err = validate_request_window(d1, d2, t1, t2)
    if err:
        return jerr(err)
    items, err = validate_items(uid, body.get("items"), bool(body.get("media")))
    if err:
        return jerr(err)
    event = clean_text(body.get("event"), 100)
    if not event:
        return jerr("Укажите название мероприятия.")
    async with BOOKING_LOCK:
        err = check_availability(items, d1, d2, exclude_rid=rid)
        if err:
            return jerr(err)
        with db() as c:
            c.execute("UPDATE requests SET items=?, dfrom=?, dto=?, event=?, comment=?, media=?, pw=?, dfrom_iso=?, dto_iso=?, tfrom=?, tto=? WHERE id=?",
                      (json.dumps(items, ensure_ascii=False), body.get("from", ""), body.get("to", ""), event,
                       clean_text(body.get("comment"), 500), int(bool(body.get("media"))), int(bool(body.get("pw")) or r["pw"]), d1, d2, t1, t2, rid))
    _push_hist("requests", rid, r["status"], "данные обновлены")
    if r["curator"]:
        await notify(r["curator"], f"✏️ В заявке ID {rid} изменены данные — проверьте даты и оборудование.")
    with db() as c:
        row = c.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    await send_or_update_card("requests", row)
    return web.json_response(boot_payload(uid))

@auth
async def api_availability(request, body, uid):
    """Занятость и свободные исправные номера на диапазон дат."""
    d1, d2 = body.get("d1") or "", body.get("d2") or ""
    exclude = int(body.get("exclude") or 0)
    free_nums = {}
    for item in body.get("items") or []:
        short = item[0] if isinstance(item, (list, tuple)) and item else ""
        if short in CATALOG_META:
            used = used_numbers(short, d1, d2, exclude)
            free_nums[short] = [num for num in ready_numbers(short) if num not in used]
    return web.json_response({
        "ok": True,
        "busy": busy_map(d1, d2, exclude),
        "capacity": {
            short: ready_capacity(short) for short in CATALOG_META
        },
        "freeNums": free_nums,
    })


@auth
async def api_equipment_unit(request, body, uid):
    if not is_admin(uid):
        return jerr("Только для администраторов.", 403)
    short = clean_text(body.get("short"), 80)
    try:
        num = int(body.get("num"))
    except (TypeError, ValueError):
        return jerr("Некорректный номер экземпляра.")
    passport = unit_passport(short, num)
    if not passport:
        return jerr("Экземпляр не найден.", 404)
    return web.json_response({"ok": True, "unit": passport})


@auth
async def api_equipment_unit_update(request, body, uid):
    if not is_admin(uid):
        return jerr("Только для администраторов.", 403)
    short = clean_text(body.get("short"), 80)
    try:
        num = int(body.get("num"))
    except (TypeError, ValueError):
        return jerr("Некорректный номер экземпляра.")
    state = clean_text(body.get("state") or "ready", 20)
    if state not in ("ready", "repair", "retired"):
        return jerr("Некорректное состояние экземпляра.")
    if not unit_passport(short, num):
        return jerr("Экземпляр не найден.", 404)
    with db() as c:
        c.execute(
            "UPDATE equipment_units SET serial=?, note=?, state=?, updated_at=?, updated_by=? "
            "WHERE short=? AND num=?",
            (clean_text(body.get("serial"), 120), clean_text(body.get("note"), 1000),
             state, datetime.now(MSK).strftime("%Y-%m-%d %H:%M"), uid, short, num),
        )
    return web.json_response(boot_payload(uid))


def _push_hist(table: str, rid: int, status: str, note: str = "") -> None:
    with db() as c:
        row = c.execute(f"SELECT history FROM {table} WHERE id=?", (rid,)).fetchone()
        h = json.loads(row["history"])
        h.append([status, now_str() + (" · " + note if note else "")])
        c.execute(f"UPDATE {table} SET history=? WHERE id=?", (json.dumps(h, ensure_ascii=False), rid))


def _log_action(admin_id: int, kind: str, ref: int, action: str) -> None:
    """Записывает действие админа в журнал админ-активности."""
    with db() as c:
        c.execute("INSERT INTO actions(admin_id, kind, ref, action, ts) VALUES (?,?,?,?,?)",
                  (admin_id, kind, ref, action, datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S")))


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def enqueue_score(event_id: str, admin_id: int, kind: str, object_id, points: Decimal, details: str) -> bool:
    """Persist one idempotent score event. Google can be configured later."""
    user = get_user(admin_id)
    fio = (user["name"] or "").strip() if user else ""
    if not fio:
        log.warning("score %s skipped: admin %s has no full name", event_id, admin_id)
        return False
    with db() as c:
        cur = c.execute("""INSERT OR IGNORE INTO score_events(
            event_id, happened_at, fio, admin_id, kind, object_id, points, details,
            status, attempts, next_retry) VALUES(?,?,?,?,?,?,?,?, 'pending',0,0)""",
            (event_id, datetime.now(MSK).isoformat(timespec="seconds"), fio, admin_id,
             kind, str(object_id), _decimal_text(points), details))
    return cur.rowcount > 0


def enqueue_request_scores(request_id: int) -> int:
    """After close, award every unique admin who issued or accepted the request."""
    with db() as c:
        rows = c.execute("""SELECT DISTINCT admin_id FROM actions
                            WHERE kind='requests' AND ref=?
                              AND action IN ('issue','return_closed')""", (request_id,)).fetchall()
    return sum(1 for row in rows if enqueue_score(
        "request:%s:%s" % (request_id, row["admin_id"]), row["admin_id"],
        "request", request_id, SCORE_REQUEST, "Выдача или приём оборудования"))


def _score_tab_range(tab: str, cells: str) -> str:
    return "'%s'!%s" % (tab.replace("'", "''"), cells)


def _pending_scores(force: bool = False):
    with db() as c:
        if force:
            return c.execute("SELECT * FROM score_events WHERE status='pending' ORDER BY happened_at").fetchall()
        return c.execute("""SELECT * FROM score_events
                            WHERE status='pending' AND next_retry<=?
                            ORDER BY happened_at""", (time.time(),)).fetchall()


def score_status() -> dict:
    with db() as c:
        counts = {row["status"]: row["n"] for row in c.execute(
            "SELECT status, COUNT(*) n FROM score_events GROUP BY status").fetchall()}
        failed = c.execute("SELECT COUNT(*) n FROM score_events WHERE status='pending' AND last_error<>''").fetchone()["n"]
        last_error = c.execute("""SELECT last_error FROM score_events
                                  WHERE last_error<>'' ORDER BY happened_at DESC LIMIT 1""").fetchone()
    return {
        "enabled": GOOGLE_SHEETS_ENABLED,
        "googleEnabled": GOOGLE_SHEETS_ENABLED, "failed": failed,
        "pending": counts.get("pending", 0),
        "sent": counts.get("sent", 0),
        "last_error": last_error["last_error"] if last_error else "",
    }


def _google_credentials(scopes: list[str]):
    try:
        from google.oauth2.service_account import Credentials
    except Exception as exc:
        raise RuntimeError("Не установлены Google API зависимости: %s" % exc) from exc
    try:
        if GOOGLE_SERVICE_ACCOUNT_JSON_B64:
            raw = base64.b64decode(GOOGLE_SERVICE_ACCOUNT_JSON_B64).decode("utf-8")
            return Credentials.from_service_account_info(
                json.loads(raw), scopes=scopes
            )
        if GOOGLE_SERVICE_ACCOUNT_FILE:
            return Credentials.from_service_account_file(
                GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes
            )
    except Exception as exc:
        raise RuntimeError("Не удалось прочитать ключ Google: %s" % exc) from exc
    raise RuntimeError(
        "Не заполнены GOOGLE_SERVICE_ACCOUNT_JSON_B64 "
        "или GOOGLE_SERVICE_ACCOUNT_FILE"
    )


def _google_service(readonly: bool = False):
    try:
        from googleapiclient.discovery import build
    except Exception as exc:
        raise RuntimeError("Не установлены Google API зависимости: %s" % exc) from exc
    scope = (
        "https://www.googleapis.com/auth/spreadsheets.readonly"
        if readonly
        else "https://www.googleapis.com/auth/spreadsheets"
    )
    return build(
        "sheets",
        "v4",
        credentials=_google_credentials([scope]),
        cache_discovery=False,
    )


def _ensure_google_tabs(service) -> None:
    meta = service.spreadsheets().get(
        spreadsheetId=GOOGLE_SHEET_ID, fields="sheets.properties.title").execute()
    existing = {s["properties"]["title"] for s in meta.get("sheets", [])}
    requests = []
    for title in (GOOGLE_SHEET_EVENTS_TAB, GOOGLE_SHEET_SUMMARY_TAB):
        if title not in existing:
            requests.append({"addSheet": {"properties": {"title": title}}})
    if requests:
        service.spreadsheets().batchUpdate(
            spreadsheetId=GOOGLE_SHEET_ID, body={"requests": requests}).execute()
    values = service.spreadsheets().values()
    values.update(
        spreadsheetId=GOOGLE_SHEET_ID,
        range=_score_tab_range(GOOGLE_SHEET_EVENTS_TAB, "A1:H1"),
        valueInputOption="RAW",
        body={"values": [["event_id", "дата и время", "ФИО", "Telegram ID", "тип",
                           "ID заявки/брони", "баллы", "описание"]]},
    ).execute()
    values.update(
        spreadsheetId=GOOGLE_SHEET_ID,
        range=_score_tab_range(GOOGLE_SHEET_SUMMARY_TAB, "A1:D1"),
        valueInputOption="RAW",
        body={"values": [["ФИО", "Telegram ID", "итоговые баллы", "последнее начисление"]]},
    ).execute()


def _mark_score_retry(event_ids, error: str) -> None:
    delays = (60, 300, 900, 3600)
    with db() as c:
        for event_id in event_ids:
            row = c.execute("SELECT attempts FROM score_events WHERE event_id=?", (event_id,)).fetchone()
            attempts = (row["attempts"] if row else 0) + 1
            delay = delays[min(attempts - 1, len(delays) - 1)]
            c.execute("""UPDATE score_events SET attempts=?, next_retry=?, last_error=?
                         WHERE event_id=?""", (attempts, time.time() + delay, error[:500], event_id))


def sync_scores_once(force: bool = False) -> dict:
    rows = _pending_scores(force)
    if not rows:
        return {"sent": 0, "pending": score_status()["pending"]}
    event_ids = [row["event_id"] for row in rows]
    try:
        service = _google_service()
        _ensure_google_tabs(service)
        values = service.spreadsheets().values()
        existing_result = values.get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=_score_tab_range(GOOGLE_SHEET_EVENTS_TAB, "A2:A"),
        ).execute()
        existing_ids = {str(row[0]) for row in existing_result.get("values", []) if row}
        append_rows = [[row["event_id"], row["happened_at"], row["fio"], str(row["admin_id"]),
                        row["kind"], row["object_id"], row["points"], row["details"]]
                       for row in rows if row["event_id"] not in existing_ids]
        if append_rows:
            values.append(
                spreadsheetId=GOOGLE_SHEET_ID,
                range=_score_tab_range(GOOGLE_SHEET_EVENTS_TAB, "A:H"),
                valueInputOption="RAW", insertDataOption="INSERT_ROWS",
                body={"values": append_rows},
            ).execute()

        ledger = values.get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=_score_tab_range(GOOGLE_SHEET_EVENTS_TAB, "A2:H"),
        ).execute().get("values", [])
        totals = {}
        for row in ledger:
            if len(row) < 7:
                continue
            fio = str(row[2]).strip()
            if not fio:
                continue
            try:
                points = Decimal(str(row[6]).replace(",", "."))
            except InvalidOperation:
                continue
            item = totals.setdefault(fio, {"admin_id": str(row[3]) if len(row) > 3 else "",
                                           "points": Decimal("0"), "last": ""})
            item["points"] += points
            happened = str(row[1]) if len(row) > 1 else ""
            if happened >= item["last"]:
                item["last"] = happened
                item["admin_id"] = str(row[3]) if len(row) > 3 else item["admin_id"]
        summary = [[fio, data["admin_id"], _decimal_text(data["points"]), data["last"]]
                   for fio, data in sorted(totals.items())]
        values.clear(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=_score_tab_range(GOOGLE_SHEET_SUMMARY_TAB, "A2:D"), body={},
        ).execute()
        if summary:
            values.update(
                spreadsheetId=GOOGLE_SHEET_ID,
                range=_score_tab_range(GOOGLE_SHEET_SUMMARY_TAB, "A2:D"),
                valueInputOption="RAW", body={"values": summary},
            ).execute()
        with db() as c:
            now = datetime.now(MSK).isoformat(timespec="seconds")
            c.executemany("""UPDATE score_events SET status='sent', sent_at=?, last_error=''
                           WHERE event_id=?""", [(now, event_id) for event_id in event_ids])
        return {"sent": len(event_ids), "pending": score_status()["pending"]}
    except Exception as exc:
        _mark_score_retry(event_ids, str(exc))
        raise


async def sync_scores(force: bool = False) -> dict:
    if not GOOGLE_SHEETS_ENABLED:
        raise RuntimeError("Google Sheets выключен в .env")
    return await asyncio.to_thread(sync_scores_once, force)


async def score_worker() -> None:
    while True:
        if GOOGLE_SHEETS_ENABLED:
            try:
                await sync_scores()
            except Exception as exc:
                log.warning("Google Sheets score sync failed: %s", exc)
        await asyncio.sleep(60)


@auth
async def api_req_action(request, body, uid):
    rid, action = body.get("id"), body.get("action")
    comment = clean_text(body.get("comment"), 500)
    with db() as c:
        r = c.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    if not r:
        return jerr("Заявка не найдена.", 404)
    owner = r["user_id"]
    curator_or_senior = r["curator"] == uid or is_senior(uid)

    if action == "cancel":
        if uid != owner or r["status"] not in ("new", "curator"):
            return jerr("Отменить заявку может только её владелец до согласования.")
        with db() as c:
            c.execute("UPDATE requests SET status='canceled' WHERE id=?", (rid,))
        _push_hist("requests", rid, "canceled")
        if r["curator"]:
            await notify(r["curator"], f"Заявка ID {rid} отменена пользователем.")
    elif action == "userret":
        if uid != owner or r["status"] != "issued":
            return jerr("Сдать можно только выданную заявку.")
        photos = _decode_photos(body.get("photos"))
        if not photos:
            return jerr("Для сдачи приложите хотя бы одну фотографию.")
        with db() as c:
            c.execute("UPDATE requests SET status='ret' WHERE id=?", (rid,))
        _push_hist("requests", rid, "ret", "фото отправлены" + (" · " + comment if comment else ""))
        caption = tx.request_return_caption(rid, comment)
        if r["curator"]:
            await notify(
                r["curator"],
                f"📷 Сдача по заявке ID {rid} отправлена — проверьте оборудование в приложении.",
            )
            await _send_blobs(r["curator"], photos, caption)
        await _send_blobs(ADMIN_CHAT_ID, photos, caption)
    elif not is_admin(uid):
        return jerr("Недостаточно прав.", 403)
    elif action == "curator":
        if r["curator"] or r["status"] not in ("new", "issued", "ret"):
            return jerr("Эту заявку сейчас нельзя принять в кураторство.")
        new_status = "curator" if r["status"] == "new" else r["status"]
        with db() as c:
            c.execute("UPDATE requests SET status=?, curator=? WHERE id=?", (new_status, uid, rid))
        _push_hist("requests", rid, new_status, "новый куратор")
        _log_action(uid, "requests", rid, "curator")
        await notify(
            owner,
            f"По заявке ID {rid} назначен куратор {_disp_user(uid)}. "
            "Откройте Оборудыш, чтобы посмотреть детали.",
        )
    elif action == "uncurator":
        if r["curator"] != uid or r["status"] not in ("curator", "approved", "issued", "ret"):
            return jerr("Снять кураторство может только текущий куратор активной заявки.")
        new_status = "new" if r["status"] in ("curator", "approved") else r["status"]
        with db() as c:
            c.execute("UPDATE requests SET status=?, curator=NULL WHERE id=?", (new_status, rid))
        _push_hist("requests", rid, new_status, "куратор снял себя")
        await notify(owner, f"По заявке ID {rid} куратор снял себя.")
        if ADMIN_CHAT_ID and bot is not None:
            await notify(ADMIN_CHAT_ID, f"Заявка ID {rid} снова без куратора — возьмите её в работу.")
    elif action in ("approved", "rejected"):
        if r["status"] != "curator" or not curator_or_senior:
            return jerr("Согласовать или отклонить заявку может только её куратор или старший.", 403)
        new_status = "approved" if action == "approved" else "rejected"
        with db() as c:
            c.execute("UPDATE requests SET status=? WHERE id=?", (new_status, rid))
        _push_hist("requests", rid, new_status, comment if action == "rejected" else "")
        _log_action(uid, "requests", rid, action)
        if action == "approved":
            await notify(owner, f"✅ Заявка ID {rid} согласована. Получение: {r['dfrom']}.")
        else:
            await notify(
                owner,
                f"⛔ Заявка ID {rid} отклонена."
                + (f" Причина: {comment}" if comment else ""),
            )
    elif action == "issue":
        if r["status"] != "approved" or not curator_or_senior:
            return jerr("Выдать оборудование может только куратор заявки или старший.", 403)
        raw_items = body.get("items") if body.get("items") is not None else json.loads(r["items"])
        items, err = validate_items(uid, raw_items, allow_restricted=True)
        if err:
            return jerr(err)
        async with BOOKING_LOCK:
            err = check_availability(items, r["dfrom_iso"], r["dto_iso"], exclude_rid=rid)
            if err:
                return jerr(err)
            nums, err = assign_numbers(
                items, r["dfrom_iso"], r["dto_iso"], exclude_rid=rid,
                preferred=body.get("nums"),
            )
            if err:
                return jerr(err)
            with db() as c:
                c.execute(
                    "UPDATE requests SET items=?, status='issued', taken_at=?, nums=?, issued_by=? WHERE id=?",
                    (json.dumps(items, ensure_ascii=False), now_str(),
                     json.dumps(nums, ensure_ascii=False), uid, rid),
                )
        note = "состав изменён" if items != json.loads(r["items"]) else ""
        _push_hist("requests", rid, "issued", (note + (" · " + comment if comment else "")).strip(" ·"))
        _log_action(uid, "requests", rid, "issue")
        await notify(owner, tx.equipment_issued_message(rid, items, r["dto"], comment, CATALOG_META))
    elif action == "return":
        if r["status"] != "ret":
            return jerr("Принять возврат можно только после сдачи пользователем.")
        if not curator_or_senior:
            return jerr("Принять возврат может только куратор заявки или старший.", 403)
        if comment and not is_senior(uid):
            with db() as c:
                c.execute("UPDATE requests SET escalated=1 WHERE id=?", (rid,))
                c.execute(
                    "INSERT INTO messages(kind, ref, sender, text, tm, role) "
                    "VALUES('req',?,?,?,?,'admin')",
                    (rid, uid, "Проблема при возврате: " + comment,
                     datetime.now(MSK).strftime("%H:%M")),
                )
            _push_hist("requests", rid, "ret", "проблемный возврат → старшим: " + comment)
            _log_action(uid, "requests", rid, "return_escalated")
            await notify_seniors(
                f"⚠️ Проблемный возврат по заявке ID {rid}: «{comment}». Подробности в приложении."
            )
        else:
            if r["escalated"] and not is_senior(uid):
                return jerr("Этот возврат уже передан старшим.")
            with db() as c:
                c.execute(
                    "UPDATE requests SET status='closed', escalated=0, "
                    "returned_at=COALESCE(returned_at, ?), returned_by=? WHERE id=?",
                    (now_str(), uid, rid),
                )
            _push_hist("requests", rid, "closed")
            _log_action(uid, "requests", rid, "return_closed")
            enqueue_request_scores(rid)
            await notify(owner, f"✅ Возврат по заявке ID {rid} принят, заявка закрыта. Спасибо!")
    else:
        return jerr("Действие недоступно.")
    with db() as c:
        row = c.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    await send_or_update_card("requests", row)
    return web.json_response(boot_payload(uid))

@auth
async def api_626_create(request, body, uid):
    u = get_user(uid)
    if not (u and u["agreed"] and u["verified"] == "ok"):
        return jerr("Сначала завершите регистрацию и верификацию.")
    day = body.get("day") or ""
    slot, err = validate_626_window(day, body.get("slot") or "")
    if err: return jerr(err)
    goal = clean_text(body.get("goal"), 100)
    if not goal: return jerr("Укажите цель бронирования.")
    needs = body.get("needs") or []
    if not isinstance(needs, list) or len(needs) > 10 or any(not isinstance(item, str) for item in needs):
        return jerr("Некорректный список дополнительного оборудования.")
    async with BOOKING_LOCK:
        taken = set(busy626_map().get(day, []))
        if taken & set(slot_expand(slot)): return jerr("Этот слот уже занят — выберите другое время.")
        hist = [["new", now_str()]]
        with db() as c:
            cur = c.execute("INSERT INTO b626(user_id, day, slot, goal, needs, history, created_ts) VALUES(?,?,?,?,?,?,?)", (uid, day, slot, goal, json.dumps([clean_text(item, 200) for item in needs], ensure_ascii=False), json.dumps(hist, ensure_ascii=False), time.time()))
            bid = cur.lastrowid; row = c.execute("SELECT * FROM b626 WHERE id=?", (bid,)).fetchone()
    await send_or_update_card("b626", row)
    await notify_seniors(f"🏛 Новая бронь 626 №{bid}: {day} {slot} — требуется согласование.")
    return web.json_response(boot_payload(uid))

@auth
async def api_626_action(request, body, uid):
    bid, action = body.get("id"), body.get("action")
    comment = clean_text(body.get("comment"), 500)
    with db() as c:
        b = c.execute("SELECT * FROM b626 WHERE id=?", (bid,)).fetchone()
    if not b:
        return jerr("Бронь не найдена.", 404)
    owner = b["user_id"]
    curator_or_senior = b["curator"] == uid or is_senior(uid)
    if action == "cancel":
        if uid != owner or b["status"] not in ("new", "approved"):
            return jerr("Отменить бронь может только её владелец до начала.")
        with db() as c:
            c.execute("UPDATE b626 SET status='canceled' WHERE id=?", (bid,))
        _push_hist("b626", bid, "canceled")
    elif action == "handover":
        if uid != owner or b["status"] != "approved":
            return jerr("Сдать можно только согласованную бронь.")
        photos = _decode_photos(body.get("photos"))
        if not photos:
            return jerr("Для сдачи аудитории приложите хотя бы одну фотографию.")
        with db() as c:
            c.execute("UPDATE b626 SET status='ret' WHERE id=?", (bid,))
        _push_hist("b626", bid, "ret", "фото отправлены" + (" · " + comment if comment else ""))
        caption = tx.studio_return_caption(bid, comment)
        if b["curator"]:
            await notify(
                b["curator"],
                f"📷 Бронь 626 №{bid}: пользователь отправил фото сдачи, проверьте аудиторию.",
            )
            await _send_blobs(b["curator"], photos, caption)
        await _send_blobs(ADMIN_CHAT_ID, photos, caption)
    elif action in ("approved", "rejected"):
        if not is_senior(uid):
            return jerr("Брони 626 согласуют только старшие администраторы.", 403)
        if b["status"] != "new":
            return jerr("Решение по этой брони уже принято.")
        with db() as c:
            c.execute("UPDATE b626 SET status=? WHERE id=?", (action, bid))
        _push_hist("b626", bid, action, comment if action == "rejected" else "")
        _log_action(uid, "b626", bid, action)
        if action == "approved":
            await notify(
                owner,
                f"✅ Бронь 626 №{bid} ({b['day']} {b['slot']}) согласована. "
                "Дождитесь назначения куратора.",
            )
        else:
            await notify(
                owner,
                f"⛔ Бронь 626 №{bid} отклонена."
                + (f" Причина: {comment}" if comment else ""),
            )
    elif action == "curator":
        if not is_admin(uid):
            return jerr("Недостаточно прав.", 403)
        if b["status"] != "approved" or b["curator"]:
            return jerr("Куратором можно стать только у согласованной свободной брони.")
        with db() as c:
            c.execute("UPDATE b626 SET curator=? WHERE id=?", (uid, bid))
        _log_action(uid, "b626", bid, "curator")
        await notify(owner, f"По брони 626 №{bid} назначен куратор {_disp_user(uid)}.")
    elif action == "closed":
        if b["status"] != "ret":
            return jerr("Завершить можно только бронь после сдачи.")
        if not curator_or_senior:
            return jerr("Завершить бронь может её куратор или старший.", 403)
        with db() as c:
            c.execute("UPDATE b626 SET status='closed' WHERE id=?", (bid,))
        _push_hist("b626", bid, "closed", comment)
        _log_action(uid, "b626", bid, "closed")
        if b["curator"]:
            enqueue_score(
                "626:%s:%s" % (bid, b["curator"]), b["curator"], "626", bid,
                SCORE_626, "Куратор брони 626",
            )
        await notify(owner, f"✅ Бронь 626 №{bid} завершена. Спасибо, приходите ещё!")
    else:
        return jerr("Действие недоступно.")
    with db() as c:
        row = c.execute("SELECT * FROM b626 WHERE id=?", (bid,)).fetchone()
    await send_or_update_card("b626", row)
    return web.json_response(boot_payload(uid))

@auth
async def api_chat(request, body, uid):
    kind = body.get("kind")
    ref = body.get("id")
    text = clean_text(body.get("text"), 1000)
    if kind not in ("req", "626") or not text:
        return jerr("Пустое сообщение.")
    table = "requests" if kind == "req" else "b626"
    with db() as c:
        row = c.execute(f"SELECT * FROM {table} WHERE id=?", (ref,)).fetchone()
    if not row:
        return jerr("Не найдено.", 404)
    if uid != row["user_id"] and uid != row["curator"] and not is_admin(uid):
        return jerr("Нет доступа к переписке.", 403)
    # роль, из которой пишут (для подписи и красного цвета старшего) - с проверкой прав
    role = body.get("asRole") or ""
    if uid == row["user_id"]:
        role = "user"
    elif role == "senior" and not is_senior(uid):
        role = "admin" if is_admin(uid) else "user"
    elif role == "admin" and not is_admin(uid):
        role = "user"
    with db() as c:
        c.execute("INSERT INTO messages(kind, ref, sender, text, tm, role) VALUES(?,?,?,?,?,?)",
                  (kind, ref, uid, text, datetime.now(MSK).strftime("%H:%M"), role))
    label = f"заявке ID {ref}" if kind == "req" else f"брони 626 №{ref}"
    if uid == row["user_id"]:
        if row["curator"]:
            await notify(row["curator"], f"💬 Сообщение по {label} от {_disp_user(uid)}:\n'{text}'")
    else:
        who = "Старший" if role == "senior" else "Куратор"
        await notify(row["user_id"], f"💬 {who} по {label}:\n'{text}'\nОтветить можно в приложении.")
        # пишут из панели старшего - уведомить и куратора
        if role == "senior" and row["curator"] and row["curator"] != uid:
            await notify(row["curator"], f"💬 Старший подключился к {label}:\n'{text}'")
    return web.json_response(boot_payload(uid))


@auth
async def api_read(request, body, uid):
    """Отметить переписку прочитанной: seen = последний id сообщения."""
    kind = body.get("kind")
    ref = body.get("id")
    if kind not in ("req", "626") or not ref:
        return web.json_response({"ok": True})
    with db() as c:
        last = c.execute("SELECT MAX(id) m FROM messages WHERE kind=? AND ref=?", (kind, ref)).fetchone()["m"] or 0
        c.execute("INSERT OR REPLACE INTO reads(user_id, kind, ref, seen) VALUES(?,?,?,?)", (uid, kind, ref, last))
    return web.json_response({"ok": True})


@auth
async def api_verify(request, body, uid):
    if not is_senior(uid):
        return jerr("Только для старших админов.", 403)
    target = body.get("userId")
    action = body.get("action")
    tu = get_user(target)
    if not tu:
        return jerr("Пользователь не найден.", 404)
    if action == "ok":
        role = body.get("role") or "активист"
        if role == "production" and not ENABLE_PRODUCTION_ROLE:
            return jerr("Роль production временно отключена.", 400)
        with db() as c:
            c.execute("UPDATE users SET verified='ok', role=? WHERE id=?", (role, target))
        await notify(target, f"✅ Верификация пройдена! Роль: {role}. Приложение открыто - можно бронировать.")
    elif action == "no":
        reason = (body.get("reason") or "").strip()[:200]
        with db() as c:
            c.execute("UPDATE users SET verified='rejected', block_reason=? WHERE id=?", (reason, target))
        await notify(target, "Заявка на верификацию отклонена."
                     + (f" Причина: {reason}." if reason else "")
                     + " Можно исправить данные и подать заново.")
    elif action == "block":
        reason = (body.get("reason") or "").strip()[:200]
        # срок: days (число) приоритетнее term (день/неделя/месяц/навсегда)
        term_days = {"день": 1, "неделя": 7, "месяц": 30, "навсегда": 0}
        try:
            days = int(body.get("days") or 0)
        except (TypeError, ValueError):
            days = 0
        if not days:
            days = term_days.get((body.get("term") or "").strip(), 0)
        until = (datetime.now(MSK) + timedelta(days=days)).strftime("%Y-%m-%d") if days > 0 else ""
        note = reason + (f" · до {until}" if until else " · навсегда")
        with db() as c:
            c.execute("UPDATE users SET verified='blocked', block_reason=?, block_until=? WHERE id=?",
                      (note.strip(" ·"), until, target))
        await notify(target, "Вы заблокированы в Оборудыше" + (f" до {until}" if until else "")
                     + (f". Причина: {reason}" if reason else "") + ". По вопросам - @Kyuller")
    elif action == "unblock":
        with db() as c:
            c.execute("UPDATE users SET verified='ok', block_reason='', block_until='' WHERE id=?", (target,))
        await notify(target, "✅ Вас разблокировали в Оборудыше - доступ снова открыт.")
    else:
        return jerr("Неизвестное действие.")
    return web.json_response(boot_payload(uid))


@auth
async def api_appeal(request, body, uid):
    """Обращение в команду оборудыша (свободный текст, можно анонимно) -> карточка в админ-канал."""
    text = clean_text(body.get("text"), 1000)
    if not text:
        return jerr("Пустое обращение.")
    anon = bool(body.get("anon"))
    photos = [] if anon else _decode_photos(body.get("photos"))  # аноним - без фото
    u = get_user(uid)
    who = "аноним" if anon else f"{(u['name'] if u and u['name'] else _disp_user(uid))} ({_disp_user(uid)})"
    card = f"💬 Обращение в команду Оборудыша\nОт: {who}\n\n{text}"
    delivered = False
    if ADMIN_CHAT_ID and bot is not None:
        try:
            if photos:
                await _send_blobs(ADMIN_CHAT_ID, photos, card[:1024])
            else:
                await bot.send_message(ADMIN_CHAT_ID, card)
            delivered = True
        except Exception as e:
            log.warning("appeal card failed: %s", e)
    if not delivered:
        await notify_seniors(card)  # фолбэк: канал не задан/недоступен - старшим в личку
        for sid in (SENIOR_ADMIN_IDS if photos else set()):
            await _send_blobs(sid, photos, card[:1024])
    return web.json_response({"ok": True})


@auth
async def api_user_role(request, body, uid):
    """Старший меняет назначенную роль пользователю в любой момент."""
    if not is_senior(uid):
        return jerr("Только для старших админов.", 403)
    target = body.get("userId")
    role = (body.get("role") or "").strip()
    allowed_roles = ("активист", "стажёр", "СО/ССФ") + (("production",) if ENABLE_PRODUCTION_ROLE else ())
    if role not in allowed_roles:
        return jerr("Неизвестная роль.")
    if not get_user(target):
        return jerr("Пользователь не найден.", 404)
    with db() as c:
        c.execute("UPDATE users SET role=? WHERE id=?", (role, target))
    await notify(target, f"Ваша роль обновлена: {role}.")
    return web.json_response(boot_payload(uid))


@auth
async def api_user_delete(request, body, uid):
    """Старший удаляет пользователя. Его заявки/брони остаются (автор станет '?')."""
    if not is_senior(uid):
        return jerr("Только для старших админов.", 403)
    target = body.get("userId")
    if target in SENIOR_ADMIN_IDS:
        return jerr("Старшего админа удалить нельзя.")
    if not get_user(target):
        return jerr("Пользователь не найден.", 404)
    with db() as c:
        c.execute("DELETE FROM users WHERE id=?", (target,))
    return web.json_response(boot_payload(uid))


@auth
async def api_category_block(request, body, uid):
    """Старший блокирует/разблокирует категорию каталога."""
    if not is_senior(uid):
        return jerr("Только для старших админов.", 403)
    cat = (body.get("cat") or "").strip()[:80]
    if not cat:
        return jerr("Не указана категория.")
    unblock = bool(body.get("unblock"))
    until = ""
    term_label = ""
    if not unblock:
        term = (body.get("term") or "").strip()[:20]
        hours = {"1h": 1, "6h": 6, "12h": 12}.get(term)
        if hours:
            until = (datetime.now(MSK) + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
            term_label = f"на {hours} " + ("час" if hours == 1 else "часов")
        elif term == "period":
            raw_until = (body.get("until") or "").strip()[:20]
            try:
                until_dt = datetime.strptime(raw_until, "%Y-%m-%d")
            except ValueError:
                return jerr("Некорректная дата.")
            until = raw_until + " 23:59"
            term_label = "до " + until_dt.strftime("%d.%m.%Y")
        elif term == "forever":
            term_label = "навсегда"
        else:
            return jerr("Не указан срок блокировки.")
    with db() as c:
        if unblock:
            c.execute("DELETE FROM cat_blocks WHERE cat=?", (cat,))
        else:
            c.execute("INSERT OR REPLACE INTO cat_blocks(cat, until, term) VALUES(?,?,?)",
                      (cat, until, term_label))
    if not unblock and ADMIN_CHAT_ID and bot is not None:
        text = f"🔒 Категория «{cat}» заблокирована " + term_label
        try:
            await bot.send_message(ADMIN_CHAT_ID, text)
        except Exception as e:
            log.warning("cat block notify failed: %s", e)
    return web.json_response(boot_payload(uid))


@auth
async def api_equip_add(request, body, uid):
    """Старший добавляет позицию в рентал (живёт в БД, домержится в каталог/тоталы)."""
    if not is_senior(uid):
        return jerr("Только для старших админов.", 403)
    cat = (body.get("cat") or "").strip()[:80]
    short = (body.get("short") or "").strip()[:80]
    full = (body.get("full") or "").strip()[:160]
    level = (body.get("level") or "").strip()
    if level not in ("", "акт", "глава"):
        level = ""
    try:
        total = max(1, int(body.get("total") or 1))
    except (TypeError, ValueError):
        total = 1
    if not cat or not short:
        return jerr("Укажите категорию и короткое название.")
    if short in TOTALS:
        return jerr("Позиция с таким названием уже есть.")
    with db() as c:
        c.execute("INSERT INTO extra_items(cat, short, full, total, level, created) VALUES(?,?,?,?,?,?)",
                  (cat, short, full, total, level, now_str()))
    load_catalog()
    sync_equipment_units()
    return web.json_response(boot_payload(uid))


@auth
async def api_equip_del(request, body, uid):
    if not is_senior(uid):
        return jerr("Только для старших админов.", 403)
    short = (body.get("short") or "").strip()
    with db() as c:
        c.execute("DELETE FROM extra_items WHERE short=?", (short,))
    load_catalog()
    sync_equipment_units()
    return web.json_response(boot_payload(uid))


@auth
async def api_equip_remove(request, body, uid):
    """Скрыть любую позицию каталога (базовую или добавленную) - обратимо."""
    if not is_senior(uid):
        return jerr("Только для старших админов.", 403)
    short = (body.get("short") or "").strip()
    if not short:
        return jerr("Не указана позиция.")
    with db() as c:
        c.execute("INSERT OR IGNORE INTO removed_items(short) VALUES(?)", (short,))
    load_catalog()
    sync_equipment_units()
    return web.json_response(boot_payload(uid))


@auth
async def api_equip_restore(request, body, uid):
    if not is_senior(uid):
        return jerr("Только для старших админов.", 403)
    short = (body.get("short") or "").strip()
    with db() as c:
        c.execute("DELETE FROM removed_items WHERE short=?", (short,))
    load_catalog()
    sync_equipment_units()
    return web.json_response(boot_payload(uid))


@auth
async def api_favset_add(request, body, uid):
    """Сохранить избранный набор оборудки (свой)."""
    name = (body.get("name") or "").strip()[:60]
    items = body.get("items") or []
    if not name or not items:
        return jerr("Укажите название и состав набора.")
    with db() as c:
        n = c.execute("SELECT COUNT(*) c FROM fav_sets WHERE user_id=?", (uid,)).fetchone()["c"]
        if n >= 20:
            return jerr("Слишком много наборов (максимум 20).")
        c.execute("INSERT INTO fav_sets(user_id, name, items, created) VALUES(?,?,?,?)",
                  (uid, name, json.dumps(items, ensure_ascii=False), now_str()))
    return web.json_response(boot_payload(uid))


@auth
async def api_favset_del(request, body, uid):
    fid = body.get("id")
    with db() as c:
        c.execute("DELETE FROM fav_sets WHERE id=? AND user_id=?", (fid, uid))
    return web.json_response(boot_payload(uid))


def admin_activity(limit=None):
    with db() as c:
        rows = c.execute("SELECT admin_id, kind, action FROM actions").fetchall()
    data = {}
    for row in rows:
        name = _disp_user(row["admin_id"])
        item = data.setdefault(name, {"name": name, "curated": 0, "issued": 0, "returned": 0, "rejected": 0, "studio": 0})
        if row["kind"] == "requests":
            if row["action"] == "curator": item["curated"] += 1
            elif row["action"] == "issue": item["issued"] += 1
            elif row["action"] == "return_closed": item["returned"] += 1
            elif row["action"] == "rejected": item["rejected"] += 1
        elif row["kind"] == "b626":
            item["studio"] += 1
    result = sorted(data.values(), key=lambda item: (-item["curated"], -item["issued"], item["name"]))
    return result[:limit] if limit else result


def build_export_text(kind):
    """Собирает текст выгрузки блоками записей (читаемо в открытом .md на телефоне,
    без markdown-таблиц). Три типа: requests, 626, admins. Возвращает (fname, text)."""
    with db() as c:
        if kind == "admins":
            admin_stats = admin_activity()
            top_rejecters = [a for a in sorted(admin_stats, key=lambda a: -a["rejected"]) if a["rejected"] > 0]

            lines = ["АДМИНИСТРАТОРЫ ОБОРУДЫША", ""]
            for a in admin_stats:
                lines.append(f"{a['name']}\nКурировал: {a['curated']}\nВыдал: {a['issued']}\n"
                             f"Принял: {a['returned']}\nОтказал: {a['rejected']}\n---")
            if top_rejecters:
                lines.append("")
                lines.append("ТОП ПО ОТКАЗАМ")
                for i, a in enumerate(top_rejecters, 1):
                    lines.append(f"{i}. {a['name']} — {a['rejected']}")
            fname = "admins.md"
        elif kind == "626":
            lines = ["БРОНИ 626", ""]
            for b in c.execute("SELECT * FROM b626 ORDER BY id").fetchall():
                au = get_user(b["user_id"])
                author = au["name"] if au else "?"
                curator = _disp_user(b["curator"]) if b["curator"] else "—"
                lines.append(f"Бронь #{b['id']}\nАвтор: {author}\nДень: {b['day']}\nСлот: {b['slot']}\n"
                             f"Цель: {b['goal']}\nСтатус: {ST_LABEL.get(b['status'], b['status'])}\n"
                             f"Куратор: {curator}\n---")
            fname = "studio626.md"
        else:
            lines = ["ЗАЯВКИ ОБОРУДЫША", ""]
            for r in c.execute("SELECT * FROM requests ORDER BY id").fetchall():
                au = get_user(r["user_id"])
                items = "; ".join(f"{s}×{q}" for s, q in json.loads(r["items"]))
                curator = _disp_user(r["curator"]) if r["curator"] else "—"
                lines.append(f"Заявка #{r['id']}\nАвтор: {(au['name'] if au else '?')}\n"
                             f"Мероприятие: {r['event']}\nДаты: {r['dfrom']} → {r['dto']}\n"
                             f"Статус: {ST_LABEL.get(r['status'], r['status'])}\nКуратор: {curator}\n"
                             f"Состав: {items}\n---")
            fname = "requests.md"
    return fname, "\n".join(lines)


MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|>])")


def md_escape(value) -> str:
    return MD_SPECIAL.sub(r"\\\1", str(value or ""))


def _rich_chunks(sections, limit=30000):
    chunks, current = [], ""
    for section in sections:
        section = str(section).strip()
        if not section:
            continue
        candidate = (current + "\n\n" + section).strip()
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(section) > limit:
            cut = section.rfind("\n", 0, limit)
            if cut < limit // 2:
                cut = limit
            chunks.append(section[:cut].strip())
            section = section[cut:].strip()
        current = section
    if current:
        chunks.append(current)
    return chunks


async def send_rich_markdown(chat_id: int, sections) -> None:
    if bot is None or not chat_id:
        return
    for chunk in _rich_chunks(sections):
        try:
            await bot.send_rich_message(chat_id, rich_message=InputRichMessage(markdown=chunk))
        except Exception as exc:
            log.warning("rich message failed, plain fallback: %s", exc)
            rest = chunk
            while rest:
                cut = rest.rfind("\n", 0, 3900)
                if cut < 1000:
                    cut = min(3900, len(rest))
                await bot.send_message(chat_id, rest[:cut])
                rest = rest[cut:].lstrip()


def build_export_text(kind):
    """Build a mobile-friendly Markdown document without tables."""
    generated = datetime.now(MSK).strftime("%d.%m.%Y %H:%M")
    stamp = datetime.now(MSK).strftime("%Y-%m-%d")
    with db() as c:
        users = {row["id"]: row for row in c.execute("SELECT * FROM users").fetchall()}
        requests_rows = c.execute("SELECT * FROM requests ORDER BY id").fetchall() if kind == "requests" else []
        studio_rows = c.execute("SELECT * FROM b626 ORDER BY id").fetchall() if kind == "626" else []
    if kind == "admins":
        stats = admin_activity()
        lines = ["# Администраторы Оборудыша", "", "_Сформировано: %s_" % generated]
        for item in stats:
            lines.extend(["", "## %s" % md_escape(item["name"]),
                          "- Курировал: **%s**" % item["curated"],
                          "- Выдал: **%s**" % item["issued"],
                          "- Принял: **%s**" % item["returned"],
                          "- Отказал: **%s**" % item["rejected"]])
        rejecters = [item for item in sorted(stats, key=lambda x: -x["rejected"]) if item["rejected"]]
        if rejecters:
            lines.extend(["", "---", "", "## Топ по отказам"])
            lines.extend("%s. %s — **%s**" % (i, md_escape(item["name"]), item["rejected"])
                         for i, item in enumerate(rejecters, 1))
        filename = "oborudysh-admins-%s.md" % stamp
    elif kind == "626":
        lines = ["# Брони аудитории 626", "", "_Сформировано: %s_" % generated]
        for row in studio_rows:
            author = users.get(row["user_id"])
            curator = _disp_user_from(users, row["curator"]) if row["curator"] else "—"
            lines.extend(["", "## Бронь №%s" % row["id"],
                          "- Автор: **%s**" % md_escape(author["name"] if author else "?"),
                          "- День: `%s`" % md_escape(row["day"]), "- Слот: `%s`" % md_escape(row["slot"]),
                          "- Цель: %s" % md_escape(row["goal"]),
                          "- Статус: **%s**" % md_escape(ST_LABEL.get(row["status"], row["status"])),
                          "- Куратор: %s" % md_escape(curator)])
        filename = "oborudysh-626-%s.md" % stamp
    else:
        lines = ["# Заявки Оборудыша", "", "_Сформировано: %s_" % generated]
        for row in requests_rows:
            author = users.get(row["user_id"])
            curator = _disp_user_from(users, row["curator"]) if row["curator"] else "—"
            lines.extend(["", "## Заявка №%s" % row["id"],
                          "- Автор: **%s**" % md_escape(author["name"] if author else "?"),
                          "- Мероприятие: %s" % md_escape(row["event"]),
                          "- Даты: `%s` → `%s`" % (md_escape(row["dfrom"]), md_escape(row["dto"])),
                          "- Статус: **%s**" % md_escape(ST_LABEL.get(row["status"], row["status"])),
                          "- Куратор: %s" % md_escape(curator), "", "### Состав"])
            lines.extend("- %s × %s" % (md_escape(short), qty) for short, qty in json.loads(row["items"]))
        filename = "oborudysh-requests-%s.md" % stamp
    return filename, "\n".join(lines).rstrip() + "\n"


@auth
async def api_export(request, body, uid):
    """Выгрузка статистики текстом (файлом от бота). Три типа: requests, 626, admins."""
    if not is_senior(uid):
        return jerr("Статистика - только старшим админам.", 403)
    kind = body.get("kind") or "requests"
    fname, text = build_export_text(kind)
    if bot is not None:
        try:
            await bot.send_document(uid, BufferedInputFile(text.encode("utf-8"), fname),
                                   caption=f"📊 {kind} из Оборудыша")
        except Exception as e:
            log.warning("export send failed: %s", e)
            return jerr("Не удалось отправить файл. Напишите боту /start и повторите.")
    return web.json_response({"ok": True, "md": text})


async def _broadcast_run(ids, text, blobs):
    sent = 0
    cap = ("📣 " + text)[:1024]
    for i in ids:
        try:
            if blobs:
                await _send_blobs(i, blobs, cap)
            else:
                await notify(i, "📣 " + text)
        except Exception as e:
            log.warning("broadcast to %s failed: %s", i, e)
        else:
            sent += 1
        await asyncio.sleep(0.06)  # лимиты Telegram: ~30 сообщений/с, идём с запасом
    log.info("Рассылка завершена: %s из %s", sent, len(ids))


@auth
async def api_broadcast(request, body, uid):
    if not is_senior(uid):
        return jerr("Рассылки - только старшим админам.", 403)
    text = (body.get("text") or "").strip()
    if not text:
        return jerr("Пустой текст рассылки.")
    blobs = _decode_photos(body.get("photos"))
    with db() as c:
        ids = [r["id"] for r in c.execute(
            "SELECT id FROM users WHERE agreed=1 AND verified='ok'").fetchall()]
    asyncio.get_event_loop().create_task(_broadcast_run(ids, text, blobs))
    out = boot_payload(uid)
    out["broadcast"] = len(ids)
    return web.json_response(out)


@auth
async def api_stats(request, body, uid):
    if not is_senior(uid):
        return jerr("Статистика - только старшим админам.", 403)
    fmt = (body.get("format") or "").strip()
    with db() as c:
        reqs = c.execute("SELECT * FROM requests WHERE status NOT IN ('canceled','rejected')").fetchall()
        b626s = c.execute("SELECT * FROM b626 WHERE status NOT IN ('canceled','rejected')").fetchall()
        allreq = c.execute("SELECT * FROM requests").fetchall()
    top, months, admins, users_top = {}, {}, {}, {}
    for r in reqs:
        for s, q in json.loads(r["items"]):
            top[s] = top.get(s, 0) + int(q)
        if r["dfrom_iso"]:
            m = r["dfrom_iso"][5:7] + "." + r["dfrom_iso"][:4]
            months[m] = months.get(m, 0) + 1
        u = get_user(r["user_id"])
        nm = (u["name"] or _disp_user(r["user_id"])) if u else "?"
        users_top[nm] = users_top.get(nm, 0) + 1
    months626 = {}
    for b in b626s:
        m = b["day"][5:7] + "." + b["day"][:4] if b["day"] else "?"
        months626[m] = months626.get(m, 0) + 1
    admin_stats = admin_activity(12)
    admins = {a["name"]: a["curated"] + a["issued"] + a["returned"] + a["rejected"] + a["studio"] for a in admin_stats}

    # подписи "лучший по..." для статистики
    best_curator = max(admin_stats, key=lambda a: a["curated"]) if admin_stats else None
    best_issuer = max(admin_stats, key=lambda a: a["issued"]) if admin_stats else None
    best_returner = max(admin_stats, key=lambda a: a["returned"]) if admin_stats else None
    top_rejecters = [a for a in sorted(admin_stats, key=lambda a: -a["rejected"]) if a["rejected"] > 0][:5]

    srt = lambda d, n=10: sorted(d.items(), key=lambda x: -x[1])[:n]
    if fmt == "md":
        # markdown формат для красивого вывода в чат
        lines = [
            "# Статистика Оборудыша",
            "",
            f"**Всего:** {len(reqs)} заявок · {len(b626s)} броней 626",
            "",
            "## Топ оборудования",
        ]
        for item, cnt in srt(top, 12):
            lines.append(f"- {item}: {cnt} шт")
        lines.append("")
        lines.append("## Заявки по месяцам")
        for m, cnt in sorted(months.items()):
            lines.append(f"- {m}: {cnt}")
        lines.append("")
        lines.append("## 626 по месяцам")
        for m, cnt in sorted(months626.items()):
            lines.append(f"- {m}: {cnt}")
        lines.append("")
        lines.append("## Активность админов")
        lines.append("| Админ | Курир. | Выдал | Принял | Откл. |")
        lines.append("|-------|-------|-------|-------|------|")
        for a in admin_stats:
            lines.append(f"| {a['name']} | {a['curated']} | {a['issued']} | {a['returned']} | {a['rejected']} |")
        lines.append("")
        # подписи лучших
        if best_curator:
            lines.append(f"• Лучший по курированию: {best_curator['name']} ({best_curator['curated']} заявок)")
        if best_issuer:
            lines.append(f"• Лучший по выдачам: {best_issuer['name']} ({best_issuer['issued']} выдач)")
        if best_returner:
            lines.append(f"• Лучший по возвратам: {best_returner['name']} ({best_returner['returned']} возвратов)")
        if top_rejecters:
            lines.append("")
            lines.append("## Топ по отказам")
            for i, a in enumerate(top_rejecters, 1):
                lines.append(f"{i}. {a['name']} — {a['rejected']}")
        lines.append("")
        lines.append("## Топ пользователей")
        for u, cnt in srt(users_top):
            lines.append(f"- {u}: {cnt}")
        return web.json_response({"ok": True, "md": "\n".join(lines)})
    # вывод best_* в JSON для красивого UI
    best = {}
    if best_curator:
        best["curator"] = best_curator["name"]
    if best_issuer:
        best["issuer"] = best_issuer["name"]
    if best_returner:
        best["returner"] = best_returner["name"]

    return web.json_response({"ok": True, "stats": {
        "top": srt(top, 12), "months": sorted(months.items()), "months626": sorted(months626.items()),
        "admins": srt(admins), "adminStats": admin_stats, "users": srt(users_top),
        "totals": {"requests": len(reqs), "b626": len(b626s)},
        "best": best,
        "topRejecters": [{"name": a["name"], "rejected": a["rejected"]} for a in top_rejecters],
    }})


# ================= resync: пересверка людей =================
@auth
async def api_resync(request, body, uid):
    """Старший: пересверить всех верифицированных по справочникам MB/org + обновить роли/отделы."""
    if not is_senior(uid):
        return jerr("Только для старших админов.", 403)
    reloaded = 0
    pending = 0
    changed_roles = 0
    with db() as c:
        users = c.execute("SELECT * FROM users WHERE agreed=1").fetchall()
    for u in users:
        name = u["name"] or ""
        mb = "Media BMSTU" in json.loads(u["orgs"] or "[]")
        # пересверяем
        if mb:
            found = await mb_ok(name)
        else:
            found = org_ok(name)
        if not found:
            # пропал из списка -> pending
            with db() as c:
                c.execute("UPDATE users SET verified='pending' WHERE id=?", (u["id"],))
            pending += 1
            if ADMIN_CHAT_ID and bot is not None:
                try:
                    await bot.send_message(ADMIN_CHAT_ID,
                        f"⚠️ {_disp_user(u['id'])} пропал из списка верификации - статус 'pending'")
                except Exception:
                    pass
        elif DIRECTORY_FILE:
            # если есть справочник - проверяем/обновляем роль и отделы
            info = directory().get(u["username"] or "") if u["username"] else None
            if info:
                new_role = info.get("role") or ""
                new_deps = info.get("deps", [])
                updates = []
                if new_role and new_role != u["role"]:
                    updates.append(f"role='{new_role}'")
                    changed_roles += 1
                if mb and new_deps and json.loads(u["deps"] or "[]") != new_deps:
                    updates.append(f"deps='{json.dumps(new_deps, ensure_ascii=False)}'")
                if updates:
                    with db() as c:
                        c.execute(f"UPDATE users SET {', '.join(updates)} WHERE id=?", (u["id"],))
        reloaded += 1
    return web.json_response({"ok": True, "reloaded": reloaded, "pending": pending, "changed_roles": changed_roles})

def _get_notif(table, row):
    try:
        return json.loads(row["notif"] or "{}")
    except Exception:
        return {}


def _set_notif(table, rid, notif):
    with db() as c:
        c.execute(f"UPDATE {table} SET notif=? WHERE id=?", (json.dumps(notif), rid))


def _meta_get(k):
    with db() as c:
        r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r["v"] if r else None


def _meta_set(k, v):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO meta(k, v) VALUES(?,?)", (k, v))


async def monthly_digest() -> None:
    """Сводка в общий канал (1-го числа в 12:00): итоги прошлого месяца."""
    if bot is None or not ADMIN_CHAT_ID:
        return
    now = datetime.now(MSK)
    # Получаем предыдущий месяц
    first_day = now.replace(day=1)
    prev_month_date = first_day - timedelta(days=1)
    prev_month = prev_month_date.strftime("%m.%Y")
    prev_iso = prev_month_date.strftime("%Y-%m")

    with db() as c:
        reqs_month = c.execute("SELECT COUNT(*) n FROM requests WHERE status NOT IN ('canceled','rejected') AND dfrom_iso LIKE ?", (prev_iso + '%',)).fetchone()["n"]
        b626_month = c.execute("SELECT COUNT(*) n FROM b626 WHERE status NOT IN ('canceled','rejected') AND day LIKE ?", (prev_iso + '%',)).fetchone()["n"]
        # топ оборудования за месяц
        top_items = c.execute("SELECT items FROM requests WHERE status NOT IN ('canceled','rejected') AND dfrom_iso LIKE ?", (prev_iso + '%',)).fetchall()

    top_counts = {}
    for r in top_items:
        for s, q in json.loads(r["items"]):
            top_counts[s] = top_counts.get(s, 0) + int(q)
    top_sorted = sorted(top_counts.items(), key=lambda x: -x[1])[:5]

    text = f"📈 ИТОГИ МЕСЯЦА {prev_month}\n• Заявки: {reqs_month}\n• Брони 626: {b626_month}"
    if top_sorted:
        text += "\n• Топ оборудования:\n" + "\n".join(f"  · {item}: {cnt} шт" for item, cnt in top_sorted)
    try:
        await send_rich_markdown(ADMIN_CHAT_ID, [text])
    except Exception as e:
        log.warning("monthly digest failed: %s", e)


async def daily_digest(award_score: bool = False) -> None:
    """Send a Rich Message report; only the scheduled run awards admin-of-day."""
    if bot is None or not ADMIN_CHAT_ID:
        return
    now = datetime.now(MSK)
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    with db() as c:
        counts = {status: c.execute(
            "SELECT COUNT(*) n FROM requests WHERE status=?", (status,)
        ).fetchone()["n"] for status in ("new", "curator", "approved", "issued", "ret")}
        actions = c.execute(
            "SELECT admin_id, kind, action, COUNT(*) n FROM actions "
            "WHERE ts LIKE ?||'%' GROUP BY admin_id, kind, action", (today,)
        ).fetchall()
        tomorrow_requests = c.execute(
            "SELECT * FROM requests WHERE (status='approved' AND dfrom_iso=?) OR "
            "(status='issued' AND dto_iso=?) ORDER BY id", (tomorrow, tomorrow)
        ).fetchall()
        tomorrow_626 = c.execute(
            "SELECT * FROM b626 WHERE status IN ('new','approved') AND day=? ORDER BY slot", (tomorrow,)
        ).fetchall()
        users = {row["id"]: row for row in c.execute("SELECT id,name,username FROM users").fetchall()}

    totals = {}
    for row in actions:
        stats = totals.setdefault(row["admin_id"], {"k": 0, "v": 0, "p": 0, "o": 0, "a": 0})
        key = ({"curator": "k", "issue": "v", "return_closed": "p", "rejected": "o"}.get(row["action"])
               if row["kind"] == "requests" else ("a" if row["kind"] == "b626" else None))
        if key:
            stats[key] += row["n"]
    admin_text = "_\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u0439 \u0441\u0435\u0433\u043e\u0434\u043d\u044f \u043d\u0435 \u0431\u044b\u043b\u043e_\n"
    if totals:
        best_id, best = max(totals.items(), key=lambda item: (sum(item[1].values()), -item[0]))
        name = _disp_user_from(users, best_id)
        admin_text = (f"*{md_escape(name)}*\n"
                      f"\u041a\u0443\u0440\u0438\u0440\u043e\u0432\u0430\u043b: {best['k']} \u00b7 \u0412\u044b\u0434\u0430\u043b: {best['v']} \u00b7 "
                      f"\u041f\u0440\u0438\u043d\u044f\u043b: {best['p']} \u00b7 \u041e\u0442\u043a\u0430\u0437\u0430\u043b: {best['o']} \u00b7 626: {best['a']}\n")
        if award_score:
            enqueue_score(f"daily_admin:{today}", best_id, "daily_admin", today,
                          SCORE_DAILY_ADMIN, f"Админ дня {today}")

    request_lines = []
    for row in tomorrow_requests:
        direction = ("\u0412\u044b\u0434\u0430\u0447\u0430" if row["status"] == "approved" and row["dfrom_iso"] == tomorrow
                     else "\u0412\u043e\u0437\u0432\u0440\u0430\u0442")
        owner = _disp_user_from(users, row["user_id"])
        items = ", ".join(f"{md_escape(short)} \u00d7 {qty}" for short, qty in json.loads(row["items"] or "[]"))
        request_lines.append(f"*{direction}, ID {row['id']}* \u2014 {md_escape(owner)}\n{items}\n")
    room_lines = []
    for row in tomorrow_626:
        start, end = _slot_bounds(row["slot"]) or ("", "")
        owner = _disp_user_from(users, row["user_id"])
        room_lines.append(f"*{md_escape(start.strip())}\u2013{md_escape(end.strip())}* \u2014 {md_escape(owner)}\n{md_escape(row['goal'])}\n")

    sections = [
        "# \u0415\u0436\u0435\u0434\u043d\u0435\u0432\u043d\u0430\u044f \u0441\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430 \u041e\u0431\u043e\u0440\u0443\u0434\u044b\u0448\u0430\n" + now.strftime("%d.%m.%Y, %H:%M") + "\n",
        "## \u0417\u0430\u044f\u0432\u043a\u0438\n"
        f"- \u041d\u043e\u0432\u044b\u0435: {counts['new']}\n- \u041d\u0430 \u0441\u043e\u0433\u043b\u0430\u0441\u043e\u0432\u0430\u043d\u0438\u0438: {counts['curator']}\n"
        f"- \u041e\u0436\u0438\u0434\u0430\u044e\u0442 \u0432\u044b\u0434\u0430\u0447\u0438: {counts['approved']}\n- \u0412\u044b\u0434\u0430\u043d\u044b: {counts['issued']}\n"
        f"- \u041e\u0436\u0438\u0434\u0430\u044e\u0442 \u043f\u0440\u0438\u0451\u043c\u0430: {counts['ret']}\n",
        "## \u0410\u0434\u043c\u0438\u043d \u0434\u043d\u044f\n" + admin_text,
        "## \u041e\u0431\u043e\u0440\u0443\u0434\u043e\u0432\u0430\u043d\u0438\u0435 \u043d\u0430 \u0437\u0430\u0432\u0442\u0440\u0430\n" + ("\n".join(request_lines) or "_\u041d\u0435\u0442 \u0432\u044b\u0434\u0430\u0447 \u0438 \u0432\u043e\u0437\u0432\u0440\u0430\u0442\u043e\u0432_\n"),
        "## \u0410\u0443\u0434\u0438\u0442\u043e\u0440\u0438\u044f 626 \u043d\u0430 \u0437\u0430\u0432\u0442\u0440\u0430\n" + ("\n".join(room_lines) or "_\u0421\u0432\u043e\u0431\u043e\u0434\u043d\u043e_\n"),
    ]
    await send_rich_markdown(ADMIN_CHAT_ID, sections)


def weekly_backup() -> None:
    """Consistent SQLite snapshot; keep the last three local copies."""
    try:
        folder = BASE / "backup" / "auto"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (datetime.now(MSK).strftime("%Y-%m-%d") + ".db")
        temp = target.with_suffix(".tmp")
        source = db()
        destination = sqlite3.connect(temp)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        temp.replace(target)
        for old in sorted(folder.glob("*.db"))[:-3]: old.unlink()
        log.info("SQLite backup created")
    except Exception as e:
        log.warning("backup failed: %s", e)

async def run_checks() -> None:
    now = datetime.now(MSK)
    ts = time.time()
    with db() as c:
        rows = c.execute("SELECT * FROM requests WHERE status IN ('new','curator','approved','issued')").fetchall()
    for r in rows:
        rid = r["id"]
        notif = _get_notif("requests", r)
        start_at = parse_dt(r["dfrom_iso"], r["tfrom"])
        deadline = parse_dt(r["dto_iso"], r["tto"])
        changed = False

        if r["status"] == "issued" and deadline:
            left = (deadline - now).total_seconds()
            if 0 < left <= 3600 and not notif.get("pre"):
                await notify(r["user_id"], f"⏰ Через час - срок сдачи по заявке ID {rid} ({r['dto']}). Не опаздывайте!")
                notif["pre"] = 1; changed = True
            elif left <= 0 and ts - notif.get("over", 0) > 7200:  # просрочка: раз в 2 часа
                await notify(r["user_id"], f"❗ Просрочка сдачи по заявке ID {rid} (срок был {r['dto']}). "
                                           f"Верните оборудование как можно скорее.")
                notif["over"] = ts; changed = True

        if r["curator"] and r["status"] == "approved" and start_at:
            left = (start_at - now).total_seconds()
            if 3600 < left <= 86400 and not notif.get("cur_issue_24"):
                await notify(r["curator"], f"📦 Завтра выдача по заявке ID {rid} ({r['dfrom']}). Проверьте состав и время.")
                notif["cur_issue_24"] = 1; changed = True
            if 0 < left <= 3600 and not notif.get("cur_issue_1"):
                await notify(r["curator"], f"⏰ Через час выдача по заявке ID {rid} ({r['dfrom']}).")
                notif["cur_issue_1"] = 1; changed = True

        if r["curator"] and r["status"] == "issued" and deadline:
            left = (deadline - now).total_seconds()
            if 3600 < left <= 86400 and not notif.get("cur_return_24"):
                await notify(r["curator"], f"📦 Завтра возврат по заявке ID {rid} ({r['dto']}).")
                notif["cur_return_24"] = 1; changed = True
            if 0 < left <= 3600 and not notif.get("cur_return_1"):
                await notify(r["curator"], f"⏰ Через час возврат по заявке ID {rid} ({r['dto']}).")
                notif["cur_return_1"] = 1; changed = True

        # напоминания в общий канал о зависших (порог 6 ч, повтор раз в 6 ч)
        STALE = 6 * 3600
        if r["status"] == "new" and r["created_ts"] and ts - r["created_ts"] > STALE and ts - notif.get("nocur", 0) > STALE:
            await notify(ADMIN_CHAT_ID, f"🕓 Заявка ID {rid} без куратора уже {int((ts - r['created_ts']) // 3600)} ч - возьмите в работу.")
            notif["nocur"] = ts; changed = True
        if r["status"] == "curator" and r["created_ts"] and ts - r["created_ts"] > STALE and ts - notif.get("noappr", 0) > STALE:
            await notify(ADMIN_CHAT_ID, f"🕓 Заявка ID {rid} у куратора {_disp_user(r['curator'])} не согласована - проверьте.")
            notif["noappr"] = ts; changed = True

        auto_cancel = None
        if r["status"] in ("new", "curator") and r["created_ts"] and ts - r["created_ts"] > 3 * 86400:
            auto_cancel = "не рассмотрена за 3 дня"
        elif r["status"] == "approved" and start_at and now > start_at:
            auto_cancel = "срок получения истёк"
        if auto_cancel:
            with db() as c:
                c.execute("UPDATE requests SET status='canceled' WHERE id=?", (rid,))
            _push_hist("requests", rid, "canceled", "автоотмена: " + auto_cancel)
            await notify(r["user_id"], f"⏳ Заявка ID {rid} отменена автоматически: {auto_cancel}. "
                                       f"Оборудование освобождено - можно подать заново.")
            with db() as c:
                row = c.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
            await send_or_update_card("requests", row)
            continue
        if changed:
            _set_notif("requests", rid, notif)

    with db() as c:
        rows = c.execute("SELECT * FROM b626 WHERE status='approved'").fetchall()
    for b in rows:
        notif = _get_notif("b626", b)
        bounds = _slot_bounds(b["slot"])
        start = parse_dt(b["day"], bounds[0] if bounds else "00:00")
        end = parse_dt(b["day"], bounds[1] if bounds else "23:59")
        changed = False
        if start and end and start <= now < end and not notif.get("start_wish"):
            await notify(b["user_id"], tx.studio_626_start_message(b["id"]))
            notif["start_wish"] = 1; changed = True
        if end and now > end and not notif.get("handover_user"):
            await notify(b["user_id"], f"🏛 Бронь 626 №{b['id']} закончилась — не забудьте сдать аудиторию "
                                       f"(фото в приложении).")
            notif["handover_user"] = 1; changed = True
        if end and now > end and b["curator"] and not notif.get("handover_curator"):
            await notify(b["curator"], f"🏛 Бронь 626 №{b['id']} закончилась ({b['day']} {b['slot']}). "
                                       "Проверьте фото сдачи.")
            notif["handover_curator"] = 1; changed = True
        if changed:
            _set_notif("b626", b["id"], notif)

    # 626 без согласования >6 ч - напоминание в канал
    with db() as c:
        rows = c.execute("SELECT * FROM b626 WHERE status='new'").fetchall()
    for b in rows:
        notif = _get_notif("b626", b)
        if b["created_ts"] and ts - b["created_ts"] > 6 * 3600 and ts - notif.get("noappr", 0) > 6 * 3600:
            await notify(ADMIN_CHAT_ID, f"🕓 Бронь 626 №{b['id']} ждёт согласования старшими ({b['day']} {b['slot']}).")
            notif["noappr"] = ts
            _set_notif("b626", b["id"], notif)

    # ежедневная сводка в 22:00 (раз в день) + автобэкап раз в неделю (храним 3)
    today = now.strftime("%Y-%m-%d")
    if now.hour >= 22 and _meta_get("digest_date") != today:
        _meta_set("digest_date", today)
        await daily_digest(award_score=True)
    last_bk = _meta_get("backup_date")
    stale_bk = True
    if last_bk:
        try:
            stale_bk = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(last_bk, "%Y-%m-%d")).days >= 7
        except ValueError:
            stale_bk = True
    if stale_bk:
        _meta_set("backup_date", today)
        weekly_backup()

    # месячная сводка в 1-го числа в 12:00
    if now.day == 1 and now.hour >= 12 and _meta_get("monthly_digest") != today:
        _meta_set("monthly_digest", today)
        await monthly_digest()

    # авто-снятие истёкших блокировок: пользователи и категории
    with db() as c:
        for row in c.execute("SELECT id, block_until FROM users WHERE verified='blocked' AND block_until<>''").fetchall():
            if _block_expired(row["block_until"]):
                c.execute("UPDATE users SET verified='ok', block_reason='', block_until='' WHERE id=?", (row["id"],))
        for row in c.execute("SELECT cat, until FROM cat_blocks WHERE until<>''").fetchall():
            if _cat_until_passed(row["until"]):
                c.execute("DELETE FROM cat_blocks WHERE cat=?", (row["cat"],))


def _seconds_to_next_check(now=None) -> float:
    """Секунды до ближайшей московской границы :00/:05/:10…"""
    current = now or datetime.now(MSK)
    passed = (current.minute % 5) * 60 + current.second + current.microsecond / 1000000.0
    return max(0.05, 300.0 - passed)


async def scheduler_loop() -> None:
    while True:
        before = db_revision()
        try:
            await run_checks()
        except Exception as e:
            log.warning("scheduler: %s", e)
        if db_revision() != before:
            await sse_broadcast()
        await asyncio.sleep(_seconds_to_next_check())


async def api_dev_tick(request: web.Request):
    """Ручной прогон планировщика - только в DEV-режиме, для тестов."""
    if not DEV_USER_ID:
        raise web.HTTPNotFound()
    await run_checks()
    return web.json_response({"ok": True})


# ================= Статика =================

async def serve_static(request: web.Request):
    rel = request.match_info.get("path") or "index.html"
    file = (WEBAPP_DIR / rel).resolve()

    try:
        file.relative_to(WEBAPP_DIR)
    except ValueError:
        raise web.HTTPNotFound()

    if not file.is_file():
        raise web.HTTPNotFound()

    resp = web.FileResponse(file)
    if file.suffix == ".html":
        resp.headers["Cache-Control"] = "no-cache"  # чтобы правки долетали без очистки кэша
    elif file.suffix in (".css", ".js", ".woff2", ".png", ".jpg", ".jpeg", ".svg") and request.query_string:
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif file.suffix in (".css", ".js", ".woff2", ".png", ".jpg", ".jpeg", ".svg"):
        resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


# ================= Бот =================



def read_legacy_recipients() -> list[dict]:
    """Read recipients without changing either database."""
    if not LEGACY_DB_PATH.is_file():
        raise RuntimeError(f"Старая база не найдена: {LEGACY_DB_PATH}")
    source = sqlite3.connect(
        "file:%s?mode=ro" % LEGACY_DB_PATH.resolve(), uri=True
    )
    source.row_factory = sqlite3.Row
    try:
        columns = {
            row["name"] for row in source.execute("PRAGMA table_info(users)")
        }
        required = {"user_id", "username", "full_name"}
        if not required.issubset(columns):
            raise RuntimeError("В старой базе таблица users имеет другой формат")
        rows = source.execute(
            "SELECT user_id, username, full_name FROM users "
            "WHERE user_id IS NOT NULL ORDER BY user_id"
        ).fetchall()
    finally:
        source.close()
    return [
        {
            "user_id": int(row["user_id"]),
            "username": str(row["username"] or "").lstrip("@"),
            "name": str(row["full_name"] or "").strip(),
        }
        for row in rows
    ]


async def send_legacy_invites() -> dict:
    """Send directly from the old read-only DB without touching the new DB."""
    if bot is None:
        raise RuntimeError("Telegram-бот не запущен")
    rows = read_legacy_recipients()
    sent = 0
    failed = 0
    for row in rows:
        try:
            await bot.send_message(row["user_id"], tx.LEGACY_MIGRATION_MESSAGE)
        except Exception as exc:
            failed += 1
            log.warning(
                "legacy invite to %s failed: %s", row["user_id"], exc
            )
        else:
            sent += 1
        await asyncio.sleep(0.06)
    return {"source": len(rows), "sent": sent, "failed": failed}


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Это 'Оборудыш' - бронирование съёмочного оборудования и студии 626 Media BMSTU.\n\n"
        "Всё происходит в приложении - открывай:",
        reply_markup=app_button(),
    )


@dp.message(Command("chatid"))
async def cmd_chatid(message: Message) -> None:
    """Прислать id чата - чтобы вписать ADMIN_CHAT_ID в .env."""
    await message.answer(f"chat_id этого чата: <code>{message.chat.id}</code>", parse_mode="HTML")


# Скрытые служебные команды для старших админов (не в меню бота - только знающий напишет руками).
@dp.message(Command("digest"))
async def cmd_digest(message: Message) -> None:
    if not is_senior(message.from_user.id):
        return
    await daily_digest()
    await message.answer("Сводка отправлена в канал.")


@dp.message(Command("scorestatus"))
async def cmd_scorestatus(message: Message) -> None:
    if not is_senior(message.from_user.id):
        return
    status = score_status()
    state = "включена" if status["googleEnabled"] else "выключена"
    await message.answer(
        f"Google Sheets: {state}\nОжидают отправки: {status['pending']}\n"
        f"С ошибкой: {status['failed']}\nОтправлено: {status['sent']}"
    )


@dp.message(Command("scoresync"))
async def cmd_scoresync(message: Message) -> None:
    if not is_senior(message.from_user.id):
        return
    try:
        result = await sync_scores(force=True)
    except Exception as exc:
        await message.answer(str(exc))
        return
    await message.answer(f"Отправлено: {result['sent']}; ошибок: {result.get('failed', 0)}.")


@dp.message(Command("backup"))
async def cmd_backup(message: Message) -> None:
    if not is_senior(message.from_user.id):
        return
    weekly_backup()
    await message.answer("Бэкап базы сделан.")


@dp.message(Command("checks"))
async def cmd_checks(message: Message) -> None:
    if not is_senior(message.from_user.id):
        return
    await run_checks()
    await message.answer("Плановые проверки прогнаны.")


@dp.message(Command("export_requests"))
async def cmd_export_requests(message: Message) -> None:
    if not is_senior(message.from_user.id):
        return
    fname, text = build_export_text("requests")
    await message.answer_document(BufferedInputFile(text.encode("utf-8"), fname))


@dp.message(Command("export_626"))
async def cmd_export_626(message: Message) -> None:
    if not is_senior(message.from_user.id):
        return
    fname, text = build_export_text("626")
    await message.answer_document(BufferedInputFile(text.encode("utf-8"), fname))


@dp.message(Command("export_admins"))
async def cmd_export_admins(message: Message) -> None:
    if not is_senior(message.from_user.id):
        return
    fname, text = build_export_text("admins")
    await message.answer_document(BufferedInputFile(text.encode("utf-8"), fname))


def _parse_id_arg(message: Message):
    parts = (message.text or "").split()
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


@dp.message(Command("addadmin"))
async def cmd_addadmin(message: Message) -> None:
    if not is_senior(message.from_user.id):
        return
    target = _parse_id_arg(message)
    if target is None:
        await message.answer("Использование: /addadmin <id>")
        return
    with db() as c:
        c.execute("INSERT OR IGNORE INTO extra_admins(user_id, added_by, added_ts) VALUES(?,?,?)",
                  (target, message.from_user.id, datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S")))
    EXTRA_ADMIN_IDS.add(target)
    await message.answer(f"{target} теперь админ.")


@dp.message(Command("deladmin"))
async def cmd_deladmin(message: Message) -> None:
    if not is_senior(message.from_user.id):
        return
    target = _parse_id_arg(message)
    if target is None:
        await message.answer("Использование: /deladmin <id>")
        return
    with db() as c:
        c.execute("DELETE FROM extra_admins WHERE user_id=?", (target,))
    EXTRA_ADMIN_IDS.discard(target)
    await message.answer(f"{target} больше не админ.")


@dp.message(Command("admins"))
async def cmd_admins(message: Message) -> None:
    if not is_senior(message.from_user.id):
        return
    lines = [
        "Старшие (.env): " + (", ".join(map(str, sorted(SENIOR_ADMIN_IDS))) or "—"),
        "Админы (.env): " + (", ".join(map(str, sorted(ADMIN_IDS))) or "—"),
        "Админы (добавлены /addadmin): " + (", ".join(map(str, sorted(EXTRA_ADMIN_IDS))) or "—"),
    ]
    await message.answer("\n".join(lines))


@dp.message(Command("migrateold_preview"))
async def cmd_migrateold_preview(message: Message) -> None:
    if not is_senior(message.from_user.id):
        return
    try:
        recipients = read_legacy_recipients()
    except Exception as exc:
        await message.answer(f"Не удалось прочитать старую базу: {exc}")
        return
    lines = [
        "Получатели миграционной рассылки",
        "Всего: %s" % len(recipients),
        "",
    ]
    for index, recipient in enumerate(recipients, start=1):
        username = (
            "@" + recipient["username"] if recipient["username"] else "без username"
        )
        name = recipient["name"] or "без ФИО"
        lines.append(
            f"{index}. {name} — {username} — ID {recipient['user_id']}"
        )
    document = "\n".join(lines)
    await message.answer_document(
        BufferedInputFile(
            document.encode("utf-8"),
            "legacy-migration-recipients.txt",
        ),
        caption=(
            f"Проверка завершена: рассылка пойдёт {len(recipients)} людям. "
            "Ничего не импортировано и не отправлено."
        ),
    )


@dp.message(Command("migrateold"))
async def cmd_migrateold(message: Message) -> None:
    if not is_senior(message.from_user.id):
        return
    if not LEGACY_MIGRATION_PASSWORD:
        await message.answer(
            "Сначала задайте LEGACY_MIGRATION_PASSWORD в bot/.env и перезапустите бота."
        )
        return
    LEGACY_MIGRATION_WAITING.add(message.from_user.id)
    await message.answer(
        "Введите пароль миграции отдельным сообщением. Сообщение с паролем "
        "будет удалено после проверки."
    )


@dp.message(F.chat.type == "private")
async def any_private(message: Message) -> None:
    user_id = message.from_user.id
    if user_id in LEGACY_MIGRATION_WAITING:
        LEGACY_MIGRATION_WAITING.discard(user_id)
        password = message.text or ""
        try:
            await message.delete()
        except Exception:
            pass
        if not hmac.compare_digest(password, LEGACY_MIGRATION_PASSWORD):
            await message.answer("Неверный пароль. Миграция не запущена.")
            return
        await message.answer(
            "Пароль принят. Начинаю рассылку напрямую по старой базе."
        )
        try:
            result = await send_legacy_invites()
        except Exception as exc:
            await message.answer(f"Миграция остановлена: {exc}")
            return
        await message.answer(
            "Готово. Адресатов в старой базе: {source}; "
            "отправлено: {sent}; ошибок: {failed}. "
            "Новая база не изменялась.".format(**result)
        )
        return
    # переслали пост из канала - подсказываем его id для ADMIN_CHAT_ID
    fo = getattr(message, "forward_origin", None)
    fchat = getattr(fo, "chat", None) if fo else None
    if fchat is not None:
        await message.answer(f"id этого канала/чата: <code>{fchat.id}</code>\n"
                             f"Впишите его в ADMIN_CHAT_ID в .env и перезапустите бота.", parse_mode="HTML")
        return
    await message.answer("Я только открываю приложение и присылаю уведомления. Всё остальное - внутри:",
                         reply_markup=app_button())


# ================= main =================

async def main() -> None:
    global bot, BOT_USERNAME, EXTRA_ADMIN_IDS
    dev_mode = bool(DEV_USER_ID) and not BOT_TOKEN
    if not BOT_TOKEN and not dev_mode:
        raise SystemExit("BOT_TOKEN не задан. Скопируйте .env.example в .env и впишите токен ТЕСТОВОГО бота.")
    if not dev_mode and not WEBAPP_URL.startswith("https://"):
        raise SystemExit(f"WEBAPP_URL должен быть https-адресом. Сейчас: {WEBAPP_URL or '<пусто>'}")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_db()
    _migrate()
    load_catalog()
    sync_equipment_units()
    with db() as c:
        EXTRA_ADMIN_IDS = {r["user_id"] for r in c.execute("SELECT user_id FROM extra_admins")}
    for bad in [x for x in (ADMIN_IDS | SENIOR_ADMIN_IDS) if x < 0]:
        log.warning("В ADMIN_IDS/SENIOR_ADMIN_IDS попал id чата (%s) - там должны быть ЛИЧНЫЕ id людей, "
                    "иначе уведомления о верификации и т.п. полетят в общий чат.", bad)

    # base64-фото в JSON: поднимаем лимит тела запроса (дефолт aiohttp - 1 МБ)
    app = web.Application(client_max_size=32 * 1024 * 1024)
    app.router.add_post("/api/me", api_me)
    app.router.add_post("/api/revision", api_revision)
    app.router.add_post("/api/register", api_register)
    app.router.add_post("/api/agree", api_agree)
    app.router.add_post("/api/member/lookup", api_member_lookup)
    app.router.add_post("/api/request/create", api_req_create)
    app.router.add_post("/api/request/update", api_req_update)
    app.router.add_post("/api/request/action", api_req_action)
    app.router.add_post("/api/availability", api_availability)
    app.router.add_post("/api/equipment/unit", api_equipment_unit)
    app.router.add_post("/api/equipment/unit/update", api_equipment_unit_update)
    app.router.add_post("/api/626/create", api_626_create)
    app.router.add_post("/api/626/action", api_626_action)
    app.router.add_post("/api/chat", api_chat)
    app.router.add_post("/api/read", api_read)
    app.router.add_post("/api/appeal", api_appeal)
    app.router.add_post("/api/verify", api_verify)
    app.router.add_post("/api/user/role", api_user_role)
    app.router.add_post("/api/user/delete", api_user_delete)
    app.router.add_post("/api/category/block", api_category_block)
    app.router.add_post("/api/equip/add", api_equip_add)
    app.router.add_post("/api/equip/del", api_equip_del)
    app.router.add_post("/api/equip/remove", api_equip_remove)
    app.router.add_post("/api/equip/restore", api_equip_restore)
    app.router.add_post("/api/favset/add", api_favset_add)
    app.router.add_post("/api/favset/del", api_favset_del)
    app.router.add_post("/api/export", api_export)
    app.router.add_post("/api/broadcast", api_broadcast)
    app.router.add_post("/api/stats", api_stats)
    app.router.add_post("/api/resync", api_resync)
    app.router.add_post("/api/dev/tick", api_dev_tick)
    app.router.add_get("/api/events", api_events)
    app.router.add_get("/{path:.*}", serve_static)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("Статика+API: http://localhost:%s -> %s", PORT, WEBAPP_DIR)

    sched = asyncio.get_event_loop().create_task(scheduler_loop())
    scores = asyncio.get_event_loop().create_task(score_worker())

    if dev_mode:
        log.warning("DEV-режим: бот не запущен (нет BOT_TOKEN), все запросы = пользователь %s. "
                    "Только для локальных тестов!", DEV_USER_ID)
        try:
            await asyncio.Event().wait()
        finally:
            sched.cancel()
            scores.cancel()
            await runner.cleanup()
        return

    bot = Bot(BOT_TOKEN)
    me = await bot.get_me()
    BOT_USERNAME = me.username
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text=tx.MENU_BUTTON_TEXT, web_app=WebAppInfo(url=WEBAPP_URL))
    )
    if not ADMIN_CHAT_ID:
        log.warning("ADMIN_CHAT_ID не задан - карточки заявок в админ-канал не пойдут. "
                    "Создайте канал, добавьте бота админом, перешлите пост из канала боту в личку - он скажет id.")
    if not (ADMIN_IDS or SENIOR_ADMIN_IDS):
        log.warning("ADMIN_IDS / SENIOR_ADMIN_IDS пусты - панели админа в приложении никому не видны.")

    try:
        await dp.start_polling(bot)
    finally:
        sched.cancel()
        scores.cancel()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())

