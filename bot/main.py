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
import csv
import hashlib
import hmac
import json
import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)
import aiohttp
from aiohttp import web
from dotenv import load_dotenv

try:  # импорт как bot.main из корня проекта или тестов
    from . import texts as tx
except ImportError:  # прямой запуск python main.py из папки bot
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

MSK = timezone(timedelta(hours=3))
log = logging.getLogger("oborudka")

bot: Bot = None  # type: ignore  # создаётся в main()
BOT_USERNAME = ""
dp = Dispatcher()

# Открытые SSE-клиенты получают только сигнал «данные изменились».
SSE_CLIENTS = set()
MUTATING_API = {
    "/api/register", "/api/request/create", "/api/request/update", "/api/request/action",
    "/api/626/create", "/api/626/action", "/api/chat", "/api/read", "/api/verify",
    "/api/user/role", "/api/user/delete", "/api/category/block", "/api/equip/add",
    "/api/equip/del", "/api/equip/remove", "/api/equip/restore", "/api/favset/add",
    "/api/favset/del", "/api/resync", "/api/equipment/unit/update",
}


async def sse_broadcast() -> None:
    for queue in list(SSE_CLIENTS):
        try:
            if queue.empty():
                queue.put_nowait("change")
        except (asyncio.QueueFull, RuntimeError):
            SSE_CLIENTS.discard(queue)


# ================= БД =================

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as c:
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
        """)


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
        if "equipment_units" not in tables:
            c.execute("CREATE TABLE equipment_units(short TEXT, num INTEGER, serial TEXT DEFAULT '', note TEXT DEFAULT '', state TEXT DEFAULT 'ready', updated_at TEXT DEFAULT '', updated_by INTEGER, PRIMARY KEY(short, num))")
    with db() as c:
        for table, cols in adds.items():
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            for k, v in cols.items():
                if k not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {k} {v}")


# ---- каталог на сервере: общее кол-во по позициям (для проверки занятости) ----
TOTALS = {}
CATALOG_META = {}
BOOKING_LOCK = asyncio.Lock()


def load_catalog() -> None:
    """?????? prototype/catalog.js (??? ?? ????, ??? ????? ?????)."""
    global TOTALS, CATALOG_META
    try:
        raw = (WEBAPP_DIR / "catalog.js").read_text(encoding="utf-8")
        data = json.loads(raw[raw.index("["):raw.rindex("]") + 1])
        TOTALS = {i["short"]: int(i.get("total") or 1) for c in data for i in c["items"]}
        CATALOG_META = {i["short"]: {"cat": c["cat"], "total": int(i.get("total") or 1), "level": i.get("level") or ""} for c in data for i in c["items"]}
    except Exception as e:
        TOTALS, CATALOG_META = {}, {}
        log.warning("prototype/catalog.js ?? ???????? (%s) - ????????? ???????? ????????? ?????????", e)
    try:
        with db() as c:
            for r in c.execute("SELECT cat, short, total, level FROM extra_items").fetchall():
                TOTALS[r["short"]] = int(r["total"] or 1)
                CATALOG_META[r["short"]] = {"cat": r["cat"], "total": int(r["total"] or 1), "level": r["level"] or ""}
            for r in c.execute("SELECT short FROM removed_items").fetchall():
                TOTALS.pop(r["short"], None); CATALOG_META.pop(r["short"], None)
    except Exception as e:
        log.warning("extra_items/removed_items ?? ?????????: %s", e)
    log.info("???????: %s ???????", len(TOTALS))

# ---- автосверка Media BMSTU по опубликованной таблице (лист 'список ребят') ----
_MB_CACHE = {"ts": 0.0, "names": None}


def _norm_name(s: str) -> str:
    return " ".join((s or "").lower().replace("ё", "е").split())

def clean_text(value, limit):
    """????? ?? ???????? ??????? ?? ?????? ??????????? ????????? ?? ?????????."""
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


def sync_equipment_units() -> None:
    """Создаёт паспорта всех известных экземпляров, не стирая заполненные данные."""
    with db() as c:
        for short, meta in CATALOG_META.items():
            for num in range(1, int(meta.get("total") or 1) + 1):
                c.execute("INSERT OR IGNORE INTO equipment_units(short, num, updated_at) VALUES(?,?,?)", (short, num, datetime.now(MSK).strftime("%Y-%m-%d %H:%M")))


def ready_numbers(short: str) -> list:
    """Номера экземпляров в состоянии ready."""
    total = int(CATALOG_META.get(short, {}).get("total") or 0)
    if total < 1:
        return []
    with db() as c:
        rows = c.execute("SELECT num FROM equipment_units WHERE short=? AND num<=? AND state='ready' ORDER BY num", (short, total)).fetchall()
    return [r["num"] for r in rows]


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
           if s in TOTALS and busy.get(s, 0) + int(q) > len(ready_numbers(s))]
    if bad:
        return "На выбранные даты уже занято: " + ", ".join(bad) + ". Уберите позиции или смените даты."
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
    if not first or not last or not _valid_slot(t1) or not _valid_slot(t2): return "??????? ?????????? ???? ? ????? ? ????? 30 ????? (09:00?21:30)."
    if last < first or (last == first and t2 <= t1): return "??????? ?????? ???? ????? ?????????."
    if (last - first).days > 61: return "???????????? ???? ???????????? ? 62 ???."
    if first < datetime.now(MSK).date() + timedelta(days=2): return "???????????? ????? ??????????? ??????? ?? 2 ??? ?? ?????????."
    if first.weekday() == 6 or last.weekday() == 6: return "????????? ? ??????? ? ??????????? ??????????."
    return None


def _active_cat_blocks():
    with db() as c: rows = c.execute("SELECT cat, until FROM cat_blocks").fetchall()
    return {r["cat"] for r in rows if not r["until"] or not _cat_until_passed(r["until"])}


def validate_items(uid, raw_items, media=False, allow_restricted=False):
    if not isinstance(raw_items, list) or not raw_items: return None, "???????? ???? ?? ???? ??????? ? ???????."
    if len(raw_items) > 50: return None, "? ????? ?????? ????? ???? ?? ?????? 50 ???????."
    blocks, user, out, seen = _active_cat_blocks(), get_user(uid), [], set()
    role = user["role"] if user else ""
    for pair in raw_items:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2: return None, "???????????? ?????? ??????."
        short, qty = pair
        if not isinstance(short, str): return None, "???????????? ???????? ???????."
        short = short.strip()
        if not short or short in seen or short not in CATALOG_META: return None, "? ?????? ???? ??????????? ??? ????????????? ???????."
        if isinstance(qty, bool): return None, "???????????? ?????????? ???????."
        try: qty = int(qty)
        except (TypeError, ValueError): return None, "???????????? ?????????? ???????."
        meta = CATALOG_META[short]
        if qty < 1 or qty > meta["total"]: return None, "?????????? ??????? ??????? ?? ??????? ?????????? ???????."
        if meta["cat"] in blocks: return None, "????????? ?%s? ???????? ??????????." % meta["cat"]
        if not allow_restricted:
            if meta["level"] == "глава" and not is_senior(uid): return None, "??? ??????? ???????? ?????? ??????? ???????."
            if meta["level"] == "акт" and role not in ("активист", "production") and not media: return None, "??? ??????? ???????? ?????????? ??? ?????????????? ?? ?????."
        out.append([short, qty]); seen.add(short)
    return out, None


def _slot_bounds(slot):
    try:
        a, b = (slot or "").replace("–", "-").replace("—", "-").split("-", 1); a, b = a.strip(), b.strip()
        return (a, b) if _valid_slot(a) and _valid_slot(b) and b > a else None
    except (AttributeError, ValueError): return None


def validate_626_window(day, slot):
    date, bounds = _parse_iso_day(day), _slot_bounds(slot)
    if not date or not bounds: return None, "??????? ?????????? ???? ? ????? 626 (09:00?21:30, ??? 30 ?????)."
    if date < datetime.now(MSK).date() + timedelta(days=2): return None, "????????? 626 ????? ??????????? ??????? ?? 2 ???."
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
    """Назначает только исправные и незанятые номера; preferred приходит из чек-листа админа."""
    result, preferred = {}, preferred or {}
    for short, qty in items:
        used = used_numbers(short, d1, d2, exclude_rid)
        free = [n for n in ready_numbers(short) if n not in used]
        wanted = _numbers_from_value(preferred.get(short))
        chosen = wanted if len(wanted) == int(qty) else free[:int(qty)]
        if len(set(chosen)) != int(qty) or any(n not in free for n in chosen):
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
    """????????????? ???? 626 ?? ?????????; ????????? ? ??????? ????."""
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
            c.execute("UPDATE users SET username=?, photo=? WHERE id=?", (uname, photo, uid))


# ================= Сериализация для фронта =================

def _disp_user(uid) -> str:
    u = get_user(uid) if uid else None
    if not u:
        return "админ"
    return ("@" + u["username"]) if u["username"] else (u["name"] or "админ")


def _chat_for(kind: str, ref: int, owner_id: int, curator_id=None):
    with db() as c:
        rows = c.execute("SELECT * FROM messages WHERE kind=? AND ref=? ORDER BY id", (kind, ref)).fetchall()
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


def _seen(user_id: int, kind: str, ref: int) -> int:
    with db() as c:
        r = c.execute("SELECT seen FROM reads WHERE user_id=? AND kind=? AND ref=?", (user_id, kind, ref)).fetchone()
    return r["seen"] if r else 0


def _unread(kind: str, ref: int, viewer: int) -> int:
    with db() as c:
        r = c.execute("SELECT COUNT(*) n FROM messages WHERE kind=? AND ref=? AND id>? AND sender<>?",
                      (kind, ref, _seen(viewer, kind, ref), viewer)).fetchone()
    return r["n"]


def shape_req(r, viewer: int) -> dict:
    author = get_user(r["user_id"])
    deps = json.loads(author["deps"]) if author else []
    return {
        "id": r["id"], "me": r["user_id"] == viewer, "curMe": r["curator"] == viewer,
        "author": (author["name"] or _disp_user(r["user_id"])) if author else "?",
        "dep": deps[0] if deps else "",
        "items": json.loads(r["items"]), "event": r["event"], "comment": r["comment"],
        "from": r["dfrom"], "to": r["dto"], "status": r["status"],
        "d1Iso": r["dfrom_iso"], "d2Iso": r["dto_iso"], "t1": r["tfrom"], "t2": r["tto"],
        "curator": _disp_user(r["curator"]) if r["curator"] else None,
        "pwUsed": bool(r["pw"]), "media": bool(r["media"]), "escalated": bool(r["escalated"]),
        "lateNote": late_note(r),
        "takenAt": r["taken_at"], "returnedAt": r["returned_at"],
        "history": json.loads(r["history"]),
        "chat": _chat_for("req", r["id"], r["user_id"], r["curator"]) if (viewer == r["user_id"] or viewer == r["curator"] or is_senior(viewer)) else [],
        "unread": _unread("req", r["id"], viewer) if (viewer == r["user_id"] or viewer == r["curator"] or is_senior(viewer)) else 0,
        "nums": json.loads(r["nums"] or "{}") if is_admin(viewer) else {},
    }


def shape_626(b, viewer: int) -> dict:
    author = get_user(b["user_id"])
    return {
        "id": b["id"], "me": b["user_id"] == viewer, "curMe": b["curator"] == viewer,
        "author": (author["name"] or _disp_user(b["user_id"])) if author else "?",
        "when": b["day"], "slot": b["slot"], "goal": b["goal"],
        "needs": json.loads(b["needs"]), "status": b["status"],
        "curator": _disp_user(b["curator"]) if b["curator"] else None,
        "history": json.loads(b["history"]),
        "chat": _chat_for("626", b["id"], b["user_id"], b["curator"]) if (viewer == b["user_id"] or viewer == b["curator"] or is_senior(viewer)) else [],
        "unread": _unread("626", b["id"], viewer) if (viewer == b["user_id"] or viewer == b["curator"] or is_senior(viewer)) else 0,
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
    with db() as c:
        rows = c.execute("SELECT * FROM equipment_units ORDER BY short COLLATE NOCASE, num").fetchall()
    return [{"short": r["short"], "num": r["num"], "serial": r["serial"], "note": r["note"],
             "state": r["state"], "updatedAt": r["updated_at"],
             "updatedBy": _disp_user(r["updated_by"]) if r["updated_by"] else "система"} for r in rows]


def unit_passport(short: str, num: int):
    with db() as c:
        unit = c.execute("SELECT * FROM equipment_units WHERE short=? AND num=?", (short, num)).fetchone()
        reqs = c.execute("SELECT * FROM requests WHERE nums<>'{}' ORDER BY id DESC").fetchall()
    if not unit:
        return None
    history = []
    for r in reqs:
        try:
            nums = json.loads(r["nums"] or "{}")
        except (TypeError, ValueError):
            nums = {}
        if num not in _numbers_from_value(nums.get(short)):
            continue
        history.append({
            "requestId": r["id"], "user": _disp_user(r["user_id"]),
            "from": r["dfrom"], "to": r["dto"], "status": r["status"],
            "issuedBy": _disp_user(r["issued_by"]) if r["issued_by"] else "—",
            "returnedBy": _disp_user(r["returned_by"]) if r["returned_by"] else "—",
            "takenAt": r["taken_at"] or "—", "returnedAt": r["returned_at"] or "—",
        })
    return {"short": unit["short"], "num": unit["num"], "serial": unit["serial"],
            "note": unit["note"], "state": unit["state"], "updatedAt": unit["updated_at"],
            "updatedBy": _disp_user(unit["updated_by"]) if unit["updated_by"] else "система",
            "history": history}


def boot_payload(uid: int) -> dict:
    u = get_user(uid)
    if u and u["verified"] == "blocked" and _block_expired(u["block_until"]):
        with db() as c:  # срок блокировки истёк - снимаем сами
            c.execute("UPDATE users SET verified='ok', block_reason='', block_until='' WHERE id=?", (uid,))
        u = get_user(uid)
    adm, sen = is_admin(uid), is_senior(uid)
    with db() as c:
        if adm:
            reqs = c.execute("SELECT * FROM requests ORDER BY id DESC").fetchall()
            b626s = c.execute("SELECT * FROM b626 ORDER BY id DESC").fetchall()
        else:
            reqs = c.execute("SELECT * FROM requests WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()
            b626s = c.execute("SELECT * FROM b626 WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()
    out = {
        "ok": True, "isAdmin": adm, "isSenior": sen,
        "registered": bool(u and u["agreed"]),
        "verified": u["verified"] if u else "none",
        "blockReason": (u["block_reason"] if u else "") or "",
        "requests": [shape_req(r, uid) for r in reqs],
        "bookings626": [shape_626(b, uid) for b in b626s],
        "dayload": dayload_map(),
        "busy626": busy626_map(),
    }
    if adm:
        out["equipmentUnits"] = unit_summary()
    with db() as c:  # каталог: добавленные позиции и блокировки категорий - всем (каталог у юзеров это учитывает)
        out["extraItems"] = [{"cat": r["cat"], "short": r["short"], "full": r["full"],
                              "total": r["total"], "level": r["level"] or None}
                             for r in c.execute("SELECT * FROM extra_items ORDER BY id").fetchall()]
        out["catBlocks"] = {r["cat"]: {"until": r["until"], "term": r["term"]}
                            for r in c.execute("SELECT * FROM cat_blocks").fetchall()}
        out["removedItems"] = [r["short"] for r in c.execute("SELECT short FROM removed_items").fetchall()]
        out["favSets"] = [{"id": r["id"], "name": r["name"], "items": json.loads(r["items"])}
                          for r in c.execute("SELECT * FROM fav_sets WHERE user_id=? ORDER BY id", (uid,)).fetchall()]
    if u:
        orgs = json.loads(u["orgs"])
        out["profile"] = {
            "name": u["name"], "short": short_name(u["name"]) or _disp_user(uid),
            "tg": ("@" + u["username"]) if u["username"] else "",
            "photo": u["photo"], "orgs": orgs, "deps": json.loads(u["deps"]),
            "status": u["role"],
        }
    if sen:
        with db() as c:
            pend = c.execute("SELECT * FROM users WHERE verified='pending'").fetchall()
            allu = c.execute("SELECT * FROM users WHERE agreed=1 ORDER BY name").fetchall()
        out["verifQueue"] = [{
            "id": p["id"], "name": p["name"] or _disp_user(p["id"]),
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




def late_note(r) -> list:
    """Машинные коды поздней выдачи/возврата для текста карточки."""
    notes = []
    try:
        if r["dto_iso"] and datetime.strptime(r["dto_iso"], "%Y-%m-%d").weekday() == 5 and (r["tto"] or "") >= "18:00":
            notes.append("return")
    except (ValueError, KeyError):
        pass
    try:
        if r["dfrom_iso"] and datetime.strptime(r["dfrom_iso"], "%Y-%m-%d").weekday() == 5 and (r["tfrom"] or "") >= "18:00":
            notes.append("issue")
    except (ValueError, KeyError):
        pass
    return notes


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
            await bot.edit_message_text(text, chat_id=ADMIN_CHAT_ID, message_id=row["admin_msg"],
                                        reply_markup=deeplink_kb(), parse_mode="MarkdownV2")
        else:
            m = await bot.send_message(ADMIN_CHAT_ID, text, reply_markup=deeplink_kb(),
                                       parse_mode="MarkdownV2")
            with db() as c:
                c.execute(f"UPDATE {table} SET admin_msg=? WHERE id=?", (m.message_id, row["id"]))
    except Exception as e:
        log.warning("admin card failed: %s", e)


# ================= API =================

def jerr(msg: str, status: int = 400) -> web.Response:
    # Старые/неправильно закодированные записи не должны попадать пользователю нечитаемым текстом.
    if "?" in msg:
        msg = "Не удалось выполнить действие. Проверьте условия заявки и повторите попытку."
    return web.json_response({"error": msg}, status=status)


def auth(handler):
    async def wrapped(request: web.Request):
        body = await request.json()
        tg_user = check_init_data(body.get("initData", ""))
        if not tg_user and DEV_USER_ID:
            tg_user = {"id": DEV_USER_ID, "username": "dev", "first_name": "Dev"}
        if not tg_user:
            return jerr("Не удалось проверить подпись Telegram. Откройте приложение из Telegram.", 401)
        touch_user(tg_user)
        response = await handler(request, body, tg_user["id"])
        if request.path in MUTATING_API and response.status < 400:
            await sse_broadcast()
        return response
    return wrapped


async def api_events(request: web.Request):
    """Авторизованный SSE: только сообщает клиенту, что пора заново запросить /api/me."""
    tg_user = check_init_data(request.query.get("initData", ""))
    if not tg_user and DEV_USER_ID:
        tg_user = {"id": DEV_USER_ID, "username": "dev", "first_name": "Dev"}
    if not tg_user:
        raise web.HTTPUnauthorized(text="Telegram initData required")
    touch_user(tg_user)
    response = web.StreamResponse(status=200, headers={
        "Content-Type": "text/event-stream", "Cache-Control": "no-cache",
        "Connection": "keep-alive", "X-Accel-Buffering": "no-cache",
    })
    await response.prepare(request)
    queue = asyncio.Queue(maxsize=1)
    SSE_CLIENTS.add(queue)
    try:
        await response.write(b"event: ready\ndata: connected\n\n")
        while True:
            try:
                await asyncio.wait_for(queue.get(), timeout=20)
                await response.write(b"event: change\ndata: refresh\n\n")
            except asyncio.TimeoutError:
                await response.write(b": keepalive\n\n")
    except (ConnectionResetError, asyncio.CancelledError, RuntimeError):
        pass
    finally:
        SSE_CLIENTS.discard(queue)
    return response


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


async def _send_blobs(chat_id: int, blobs, caption: str) -> None:
    """Список bytes -> в чат одним сообщением (media group), подпись на первом."""
    if not chat_id or bot is None or not blobs:
        return
    try:
        if len(blobs) == 1:
            await bot.send_photo(chat_id, BufferedInputFile(blobs[0], tx.PHOTO_FILENAME), caption=caption or None)
        else:
            media = [InputMediaPhoto(media=BufferedInputFile(b, tx.photo_filename(i + 1)),
                                     caption=(caption if (i == 0 and caption) else None))
                     for i, b in enumerate(blobs)]
            await bot.send_media_group(chat_id, media=media)
    except Exception as e:
        log.warning("send_photos %s failed: %s", chat_id, e)


async def send_photos_b64(chat_id: int, photos, caption: str) -> None:
    """Фото (base64 с фронта) -> в чат, без хранения на сервере."""
    await _send_blobs(chat_id, _decode_photos(photos), caption)


@auth
async def api_me(request, body, uid):
    return web.json_response(boot_payload(uid))


@auth
async def api_register(request, body, uid):
    name = clean_text(body.get("name"), 80)
    orgs = [clean_text(o, 100) for o in (body.get("orgs") or [])]
    deps = body.get("deps") or []
    if not name:
        return jerr("Укажите ФИО - без него регистрация невозможна.")
    if len(name.split()) < 3:
        return jerr("Введите ФИО полностью - фамилия, имя и отчество (три слова).")
    if not orgs:
        return jerr("Выберите организацию.")
    mb = "Media BMSTU" in orgs
    if mb and not deps:
        return jerr("Выберите хотя бы один отдел Media BMSTU.")
    # желаемая роль (пользователь выбирает при регистрации; старший подтвердит при верификации)
    ALLOWED_ROLES = ("активист", "стажёр", "СО/ССФ", "production")
    want_role = (body.get("role") or "").strip()
    if want_role not in ALLOWED_ROLES:
        want_role = ""
    u = get_user(uid)
    verified = u["verified"]
    role = u["role"]
    name_changed = _norm_name(name) != _norm_name(u["name"] or "")
    # автозаполнение по username из справочника (DIRECTORY_FILE)
    dir_info = directory().get(u["username"] or "") if u and u["username"] else None
    if dir_info:
        if dir_info.get("role") and dir_info["role"] in ALLOWED_ROLES:
            role = dir_info["role"]
        if mb and dir_info.get("deps"):
            deps = dir_info["deps"]
    # автопроверка при первой регистрации ИЛИ при смене имени: MB - по Google-таблице, организации - по файлу
    if verified != "ok" or name_changed:
        found = (await mb_ok(name)) if mb else org_ok(name)
        verified = "ok" if found else "pending"
        role = want_role or role or ("активист" if mb else "СО/ССФ")
    elif want_role:
        role = want_role
    with db() as c:
        c.execute("UPDATE users SET name=?, orgs=?, deps=?, agreed=1, verified=?, role=? WHERE id=?",
                  (name, json.dumps(orgs, ensure_ascii=False),
                   json.dumps(deps if mb else [], ensure_ascii=False), verified, role, uid))
    if verified == "pending":
        text = tx.verification_request_message(name, _disp_user(uid), orgs, mb)
        if ADMIN_CHAT_ID and bot is not None:
            try:
                await bot.send_message(ADMIN_CHAT_ID, text)
            except Exception as e:
                log.warning("verif card failed: %s", e)
                await notify_seniors(text)
        else:
            await notify_seniors(text)
    return web.json_response(boot_payload(uid))


@auth
async def api_req_create(request, body, uid):
    u = get_user(uid)
    if not (u and u["agreed"] and u["verified"] == "ok"):
        return jerr("??????? ?? ?????????????.")
    d1, d2, t1, t2 = body.get("d1") or "", body.get("d2") or "", body.get("t1") or "", body.get("t2") or ""
    err = validate_request_window(d1, d2, t1, t2)
    if err:
        return jerr(err)
    items, err = validate_items(uid, body.get("items"), bool(body.get("media")))
    if err:
        return jerr(err)
    event = clean_text(body.get("event"), 100)
    if not event:
        return jerr("??????? ???????????.")
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
        return jerr("?????? ?? ???????.", 404)
    if r["user_id"] != uid or r["status"] not in ("new", "curator"):
        return jerr("?????? ????? ?????? ???? ?????? ?? ????????????.")
    d1, d2, t1, t2 = body.get("d1") or "", body.get("d2") or "", body.get("t1") or "", body.get("t2") or ""
    err = validate_request_window(d1, d2, t1, t2)
    if err:
        return jerr(err)
    items, err = validate_items(uid, body.get("items"), bool(body.get("media")))
    if err:
        return jerr(err)
    event = clean_text(body.get("event"), 100)
    if not event:
        return jerr("??????? ???????????.")
    async with BOOKING_LOCK:
        err = check_availability(items, d1, d2, exclude_rid=rid)
        if err:
            return jerr(err)
        with db() as c:
            c.execute("UPDATE requests SET items=?, dfrom=?, dto=?, event=?, comment=?, media=?, pw=?, dfrom_iso=?, dto_iso=?, tfrom=?, tto=? WHERE id=?",
                      (json.dumps(items, ensure_ascii=False), body.get("from", ""), body.get("to", ""), event,
                       clean_text(body.get("comment"), 500), int(bool(body.get("media"))), int(bool(body.get("pw")) or r["pw"]), d1, d2, t1, t2, rid))
    _push_hist("requests", rid, r["status"], "???????? ?????????????")
    if r["curator"]:
        await notify(r["curator"], tx.request_updated_for_curator_message(rid))
    with db() as c:
        row = c.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    await send_or_update_card("requests", row)
    return web.json_response(boot_payload(uid))

@auth
async def api_availability(request, body, uid):
    """Занятость позиций на диапазон дат (для каталога в мастере)."""
    d1, d2, exclude = body.get("d1") or "", body.get("d2") or "", int(body.get("exclude") or 0)
    busy = busy_map(d1, d2, exclude)
    shorts = [pair[0] for pair in (body.get("items") or []) if isinstance(pair, list) and pair]
    free_nums = {}
    for short in shorts:
        if short in CATALOG_META:
            used = used_numbers(short, d1, d2, exclude)
            free_nums[short] = [n for n in ready_numbers(short) if n not in used]
    return web.json_response({"ok": True, "busy": busy, "freeNums": free_nums})


@auth
async def api_equipment_unit(request, body, uid):
    if not is_admin(uid):
        return jerr("Только для админов.", 403)
    short = (body.get("short") or "").strip()
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
        return jerr("Только для админов.", 403)
    short = (body.get("short") or "").strip()
    try:
        num = int(body.get("num"))
    except (TypeError, ValueError):
        return jerr("Некорректный номер экземпляра.")
    state = (body.get("state") or "ready").strip()
    if state not in ("ready", "repair", "retired"):
        return jerr("Некорректное состояние экземпляра.")
    if not unit_passport(short, num):
        return jerr("Экземпляр не найден.", 404)
    with db() as c:
        c.execute("UPDATE equipment_units SET serial=?, note=?, state=?, updated_at=?, updated_by=? WHERE short=? AND num=?",
                  (clean_text(body.get("serial"), 120), clean_text(body.get("note"), 1000),
                   state, datetime.now(MSK).strftime("%Y-%m-%d %H:%M"), uid, short, num))
    return web.json_response(boot_payload(uid))


def _push_hist(table: str, rid: int, status: str, note: str = "") -> None:
    if "?" in note:
        note = "статус обновлён"
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


@auth
async def api_req_action(request, body, uid):
    rid, action = body.get("id"), body.get("action")
    comment = clean_text(body.get("comment"), 500)
    with db() as c:
        r = c.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    if not r:
        return jerr("?????? ?? ???????.", 404)
    owner = r["user_id"]
    curator_or_senior = r["curator"] == uid or is_senior(uid)

    if action == "cancel":
        if uid != owner or r["status"] not in ("new", "curator"):
            return jerr("???????? ????? ?????? ???? ?????? ?? ????????????.")
        with db() as c: c.execute("UPDATE requests SET status='canceled' WHERE id=?", (rid,))
        _push_hist("requests", rid, "canceled")
        if r["curator"]: await notify(r["curator"], tx.request_canceled_for_curator_message(rid))
    elif action == "userret":
        if uid != owner or r["status"] != "issued":
            return jerr("????? ????? ?????? ???????? ??????.")
        photos = _decode_photos(body.get("photos"))
        if not photos:
            return jerr("??? ????? ????????? ???? ?? ???? ???? ?????????.")
        with db() as c: c.execute("UPDATE requests SET status='ret' WHERE id=?", (rid,))
        _push_hist("requests", rid, "ret", "???? ????????????" + (" ? " + comment if comment else ""))
        cap = tx.request_return_caption(rid, comment)
        if r["curator"]:
            await notify(r["curator"], tx.request_return_submitted_message(rid))
            await _send_blobs(r["curator"], photos, cap)
        await _send_blobs(ADMIN_CHAT_ID, photos, cap)
    elif not is_admin(uid):
        return jerr("?????? ??? ???????.", 403)
    elif action == "curator":
        # Заявку берут только без действующего куратора. После снятия с себя
        # кураторства передать можно и выданную/сданную заявку, не меняя её статус.
        if r["curator"] or r["status"] not in ("new", "issued", "ret"):
            return jerr("Эту заявку сейчас нельзя принять в кураторство.")
        new_status = "curator" if r["status"] == "new" else r["status"]
        with db() as c:
            c.execute("UPDATE requests SET status=?, curator=? WHERE id=?", (new_status, uid, rid))
        _push_hist("requests", rid, new_status, "новый куратор")
        _log_action(uid, "requests", rid, "curator")
        await notify(owner, tx.request_curator_assigned_message(rid, _disp_user(uid)))
    elif action == "uncurator":
        if r["curator"] != uid or r["status"] not in ("curator", "approved", "issued", "ret"):
            return jerr("????? ??????????? ????? ?????? ?? ????? ?????? ?? ????????.")
        new_status = "new" if r["status"] in ("curator", "approved") else r["status"]
        with db() as c: c.execute("UPDATE requests SET status=?, curator=NULL WHERE id=?", (new_status, rid))
        _push_hist("requests", rid, new_status, "??????? ???? ????")
        await notify(owner, tx.request_curator_left_message(rid))
        if ADMIN_CHAT_ID and bot is not None: await notify(ADMIN_CHAT_ID, tx.request_curator_left_channel_message(rid))
    elif action in ("approved", "rejected"):
        if r["status"] != "curator" or not curator_or_senior:
            return jerr("??????????? ??? ????????? ????? ??????? ?????? ???? ??????? ?????.", 403)
        with db() as c: c.execute("UPDATE requests SET status=? WHERE id=?", ("approved" if action == "approved" else "rejected", rid))
        _push_hist("requests", rid, action, comment if action == "rejected" else "")
        _log_action(uid, "requests", rid, action)
        await notify(owner, tx.request_approved_message(rid, r["dfrom"]) if action == "approved" else tx.request_rejected_message(rid, comment))
    elif action == "issue":
        if r["status"] != "approved" or not curator_or_senior:
            return jerr("?????? ???????????? ????? ??????? ?????? ???? ??????? ?????.", 403)
        raw_items = body.get("items") if body.get("items") is not None else json.loads(r["items"])
        items, err = validate_items(uid, raw_items, allow_restricted=True)
        if err: return jerr(err)
        async with BOOKING_LOCK:
            err = check_availability(items, r["dfrom_iso"], r["dto_iso"], exclude_rid=rid)
            if err: return jerr(err)
            nums, err = assign_numbers(items, r["dfrom_iso"], r["dto_iso"], exclude_rid=rid, preferred=body.get("nums"))
            if err: return jerr(err)
            with db() as c:
                c.execute("UPDATE requests SET items=?, status='issued', taken_at=?, nums=?, issued_by=? WHERE id=?", (json.dumps(items, ensure_ascii=False), now_str(), json.dumps(nums, ensure_ascii=False), uid, rid))
        note = "?????? ???????" if items != json.loads(r["items"]) else ""
        _push_hist("requests", rid, "issued", (note + (" ? " + comment if comment else "")).strip(" ?"))
        _log_action(uid, "requests", rid, "issue")
        await notify(owner, tx.equipment_issued_message(rid, items, r["dto"], comment, CATALOG_META))
    elif action == "return":
        if r["status"] != "ret":
            return jerr("??????? ???????????? ?????? ????? ???????????? ? ????.")
        if not curator_or_senior:
            return jerr("??????? ??????? ????? ??????? ?????? ???? ??????? ?????.", 403)
        if comment and not is_senior(uid):
            with db() as c:
                c.execute("UPDATE requests SET escalated=1 WHERE id=?", (rid,))
                c.execute("INSERT INTO messages(kind, ref, sender, text, tm, role) VALUES('req',?,?,?,?,'admin')", (rid, uid, "?? ???????? ? ?????????: " + comment, datetime.now(MSK).strftime("%H:%M")))
            _push_hist("requests", rid, "ret", "?????????? ??????? -> ???????: " + comment); _log_action(uid, "requests", rid, "return_escalated")
            await notify_seniors(tx.problem_return_message(rid, comment))
        else:
            if r["escalated"] and not is_senior(uid): return jerr("???? ??????? ??????? ??????? ???????.")
            with db() as c: c.execute("UPDATE requests SET status='closed', escalated=0, returned_at=COALESCE(returned_at, ?), returned_by=? WHERE id=?", (now_str(), uid, rid))
            _push_hist("requests", rid, "closed"); _log_action(uid, "requests", rid, "return_closed")
            await notify(owner, tx.request_closed_message(rid))
    else:
        return jerr("Действие недоступно.")
    with db() as c: row = c.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    await send_or_update_card("requests", row)
    return web.json_response(boot_payload(uid))

@auth
async def api_626_create(request, body, uid):
    u = get_user(uid)
    if not (u and u["agreed"] and u["verified"] == "ok"):
        return jerr("??????? ?? ?????????????.")
    day = body.get("day") or ""
    slot, err = validate_626_window(day, body.get("slot") or "")
    if err: return jerr(err)
    goal = clean_text(body.get("goal"), 100)
    if not goal: return jerr("????????? ???? ????????????.")
    needs = body.get("needs") or []
    if not isinstance(needs, list) or len(needs) > 10 or any(not isinstance(item, str) for item in needs):
        return jerr("???????????? ?????? ????????????.")
    async with BOOKING_LOCK:
        taken = set(busy626_map().get(day, []))
        if taken & set(slot_expand(slot)): return jerr("??? ????? ??? ?????? - ???????? ?????? ?????.")
        hist = [["new", now_str()]]
        with db() as c:
            cur = c.execute("INSERT INTO b626(user_id, day, slot, goal, needs, history, created_ts) VALUES(?,?,?,?,?,?,?)", (uid, day, slot, goal, json.dumps([clean_text(item, 200) for item in needs], ensure_ascii=False), json.dumps(hist, ensure_ascii=False), time.time()))
            bid = cur.lastrowid; row = c.execute("SELECT * FROM b626 WHERE id=?", (bid,)).fetchone()
    await send_or_update_card("b626", row)
    await notify_seniors(tx.new_studio_booking_message(bid, day, slot))
    return web.json_response(boot_payload(uid))

@auth
async def api_626_action(request, body, uid):
    bid, action = body.get("id"), body.get("action")
    comment = clean_text(body.get("comment"), 500)
    with db() as c: b = c.execute("SELECT * FROM b626 WHERE id=?", (bid,)).fetchone()
    if not b: return jerr("????? ?? ???????.", 404)
    owner, curator_or_senior = b["user_id"], b["curator"] == uid or is_senior(uid)
    if action == "cancel":
        if uid != owner or b["status"] not in ("new", "approved"): return jerr("???????? ????? ?????? ???? ???????? ?????.")
        with db() as c: c.execute("UPDATE b626 SET status='canceled' WHERE id=?", (bid,))
        _push_hist("b626", bid, "canceled")
    elif action == "handover":
        if uid != owner or b["status"] != "approved": return jerr("????? ????? ?????? ????????????? ?????.")
        photos = _decode_photos(body.get("photos"))
        if not photos: return jerr("??? ????? ????????? ????????? ???? ?? ???? ????.")
        with db() as c: c.execute("UPDATE b626 SET status='ret' WHERE id=?", (bid,))
        _push_hist("b626", bid, "ret", "???? ????????????" + (" ? " + comment if comment else ""))
        cap = tx.studio_return_caption(bid, comment)
        if b["curator"]:
            await notify(b["curator"], tx.studio_return_submitted_message(bid))
            await _send_blobs(b["curator"], photos, cap)
        await _send_blobs(ADMIN_CHAT_ID, photos, cap)
    elif action in ("approved", "rejected"):
        if not is_senior(uid): return jerr("626 ????????? ?????? ??????? ??????.", 403)
        if b["status"] != "new": return jerr("??????? ????? ??????? ?????? ?? ????? ?????.")
        with db() as c: c.execute("UPDATE b626 SET status=? WHERE id=?", (action, bid))
        _push_hist("b626", bid, action, comment if action == "rejected" else ""); _log_action(uid, "b626", bid, action)
        await notify(owner, tx.studio_approved_message(bid, b["day"], b["slot"]) if action == "approved" else tx.studio_rejected_message(bid, b["day"], b["slot"], comment))
    elif action == "curator":
        if not is_admin(uid): return jerr("?????? ??? ???????.", 403)
        if b["status"] != "approved" or b["curator"]: return jerr("??????????? ???????? ????? ???????????? ? ???? ????????.")
        with db() as c: c.execute("UPDATE b626 SET curator=? WHERE id=?", (uid, bid))
        _log_action(uid, "b626", bid, "curator"); await notify(owner, tx.studio_curator_assigned_message(bid, _disp_user(uid)))
    elif action == "closed":
        if b["status"] != "ret": return jerr("????????? ????? ?????? ??????? ????? (?? ????????).")
        if not curator_or_senior: return jerr("????????? ????? ????? ?? ??????? ??? ??????? ?????.", 403)
        with db() as c: c.execute("UPDATE b626 SET status='closed' WHERE id=?", (bid,))
        _push_hist("b626", bid, "closed", comment); _log_action(uid, "b626", bid, "closed")
        await notify(owner, tx.studio_closed_message(bid))
    else: return jerr("Действие недоступно.")
    with db() as c: row = c.execute("SELECT * FROM b626 WHERE id=?", (bid,)).fetchone()
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
    label = tx.conversation_label(kind, ref)
    if uid == row["user_id"]:
        if row["curator"]:
            await notify(row["curator"], tx.chat_from_user_message(label, _disp_user(uid), text))
    else:
        who = role
        await notify(row["user_id"], tx.chat_to_user_message(who, label, text))
        # пишут из панели старшего - уведомить и куратора
        if role == "senior" and row["curator"] and row["curator"] != uid:
            await notify(row["curator"], tx.chat_senior_joined_message(label, text))
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
        with db() as c:
            c.execute("UPDATE users SET verified='ok', role=? WHERE id=?", (role, target))
        await notify(target, tx.verification_approved_message(role))
    elif action == "no":
        reason = (body.get("reason") or "").strip()[:200]
        with db() as c:
            c.execute("UPDATE users SET verified='rejected', block_reason=? WHERE id=?", (reason, target))
        await notify(target, tx.verification_rejected_message(reason))


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
        await notify(target, tx.user_blocked_message(until, reason))

    elif action == "unblock":
        with db() as c:
            c.execute("UPDATE users SET verified='ok', block_reason='', block_until='' WHERE id=?", (target,))
        await notify(target, tx.user_unblocked_message())
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
    who = tx.appeal_sender(anon, u["name"] if u and u["name"] else _disp_user(uid), _disp_user(uid))
    card = tx.appeal_card_message(who, text)
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
    if role not in ("активист", "стажёр", "СО/ССФ", "production"):
        return jerr("Неизвестная роль.")
    if not get_user(target):
        return jerr("Пользователь не найден.", 404)
    with db() as c:
        c.execute("UPDATE users SET role=? WHERE id=?", (role, target))
    await notify(target, tx.user_role_updated_message(role))
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
            term_label = tx.category_block_term_label(hours=hours)
        elif term == "period":
            raw_until = (body.get("until") or "").strip()[:20]
            try:
                until_dt = datetime.strptime(raw_until, "%Y-%m-%d")
            except ValueError:
                return jerr("Некорректная дата.")
            until = raw_until + " 23:59"
            term_label = tx.category_block_term_label(date_text=until_dt.strftime("%d.%m.%Y"))
        elif term == "forever":
            term_label = tx.category_block_term_label(forever=True)
        else:
            return jerr("Не указан срок блокировки.")
    with db() as c:
        if unblock:
            c.execute("DELETE FROM cat_blocks WHERE cat=?", (cat,))
        else:
            c.execute("INSERT OR REPLACE INTO cat_blocks(cat, until, term) VALUES(?,?,?)",
                      (cat, until, term_label))
    if not unblock and ADMIN_CHAT_ID and bot is not None:
        text = tx.category_blocked_message(cat, term_label)
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
    """Собирает имя и содержимое Telegram-файла через bot/texts.py."""
    with db() as c:
        if kind == "admins":
            return tx.export_admins_file(admin_activity())
        if kind == "626":
            bookings = []
            for row in c.execute("SELECT * FROM b626 ORDER BY id").fetchall():
                author = get_user(row["user_id"])
                bookings.append({
                    "id": row["id"],
                    "author": author["name"] if author else tx.UNKNOWN_VALUE,
                    "day": row["day"],
                    "slot": row["slot"],
                    "goal": row["goal"],
                    "status": tx.STATUS_LABELS.get(row["status"], row["status"]),
                    "curator": _disp_user(row["curator"]) if row["curator"] else tx.EMPTY_VALUE,
                })
            return tx.export_studio_file(bookings)
        requests = []
        for row in c.execute("SELECT * FROM requests ORDER BY id").fetchall():
            author = get_user(row["user_id"])
            requests.append({
                "id": row["id"],
                "author": author["name"] if author else tx.UNKNOWN_VALUE,
                "event": row["event"],
                "date_from": row["dfrom"],
                "date_to": row["dto"],
                "status": tx.STATUS_LABELS.get(row["status"], row["status"]),
                "curator": _disp_user(row["curator"]) if row["curator"] else tx.EMPTY_VALUE,
                "items": tx.export_items_text(json.loads(row["items"])),
            })
        return tx.export_requests_file(requests)


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
                                   caption=tx.export_caption(kind))
        except Exception as e:
            log.warning("export send failed: %s", e)
            return jerr("Не удалось отправить файл. Напишите боту /start и повторите.")
    return web.json_response({"ok": True, "md": text})


async def _broadcast_run(ids, text, blobs):
    sent = 0
    cap = tx.broadcast_message(text)[:1024]
    for i in ids:
        try:
            if blobs:
                await _send_blobs(i, blobs, cap)
            else:
                await notify(i, tx.broadcast_message(text))
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
                    await bot.send_message(ADMIN_CHAT_ID, tx.verification_missing_after_resync_message(_disp_user(u["id"])))
                except Exception as e:
                    log.warning("resync verification notification failed: %s", e)
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


async def daily_digest() -> None:
    """Ежедневная статистика в общий канал (22:00)."""
    if bot is None or not ADMIN_CHAT_ID:
        return
    now = datetime.now(MSK)
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    with db() as c:
        issued_n = c.execute("SELECT COUNT(*) n FROM requests WHERE status='issued'").fetchone()["n"]
        approved_n = c.execute("SELECT COUNT(*) n FROM requests WHERE status='approved'").fetchone()["n"]
        curator_n = c.execute("SELECT COUNT(*) n FROM requests WHERE status='curator'").fetchone()["n"]
        ret_n = c.execute("SELECT COUNT(*) n FROM requests WHERE status='ret'").fetchone()["n"]
        tmr_rows = c.execute(
            "SELECT * FROM requests WHERE (status='approved' AND dfrom_iso=?) OR (status='issued' AND dto_iso=?) ORDER BY id",
            (tomorrow, tomorrow)).fetchall()
        b626_rows = c.execute(
            "SELECT * FROM b626 WHERE status IN ('new','approved') AND day=? ORDER BY slot", (tomorrow,)).fetchall()
        act_rows = c.execute(
            "SELECT admin_id, kind, action, COUNT(*) n FROM actions WHERE ts LIKE ?||'%' GROUP BY admin_id, kind, action",
            (today,)).fetchall()

    per_admin = {}
    for row in act_rows:
        stats = per_admin.setdefault(row["admin_id"], {"k": 0, "v": 0, "p": 0, "o": 0, "a": 0})
        if row["kind"] == "requests":
            key = {"curator": "k", "issue": "v", "return_closed": "p", "rejected": "o"}.get(row["action"])
            if key:
                stats[key] += row["n"]
        elif row["kind"] == "b626":
            stats["a"] += row["n"]
    admin_day = None
    if per_admin:
        best_id, best = max(per_admin.items(), key=lambda item: sum(item[1].values()))
        admin_day = dict(best, name=_disp_user(best_id))

    equipment_bookings = []
    for row in tmr_rows:
        nums = json.loads(row["nums"] or "{}")
        items = [{"short": short, "qty": qty, "num": nums.get(short)}
                 for short, qty in json.loads(row["items"])]
        try:
            date_from = datetime.strptime(row["dfrom_iso"], "%Y-%m-%d").strftime("%d.%m.%Y")
            date_to = datetime.strptime(row["dto_iso"], "%Y-%m-%d").strftime("%d.%m.%Y")
        except ValueError:
            date_from, date_to = row["dfrom_iso"], row["dto_iso"]
        equipment_bookings.append({
            "id": row["id"], "user": _disp_user(row["user_id"]), "items": items,
            "event": row["event"], "date_from": date_from, "time_from": row["tfrom"],
            "date_to": date_to, "time_to": row["tto"],
        })

    studio_bookings = []
    for row in b626_rows:
        start, end = (_slot_bounds(row["slot"]) or ("", ""))
        studio_bookings.append({
            "start": start.strip(), "end": end.strip(), "user": _disp_user(row["user_id"]),
            "goal": row["goal"],
        })
    text = tx.daily_digest_message(
        issued_n, approved_n, curator_n, ret_n, admin_day,
        equipment_bookings, studio_bookings,
    )
    try:
        await bot.send_message(ADMIN_CHAT_ID, text, parse_mode="MarkdownV2")
    except Exception as e:
        log.warning("digest failed: %s", e)


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

    text = tx.monthly_digest_message(prev_month, reqs_month, b626_month, top_sorted)
    try:
        await bot.send_message(ADMIN_CHAT_ID, text, parse_mode="MarkdownV2")
    except Exception as e:
        log.warning("monthly digest failed: %s", e)


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
    data_changed = False
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
                await notify(r["user_id"], tx.user_return_in_hour_message(rid, r["dto"]))
                notif["pre"] = 1; changed = True
            elif left <= 0 and ts - notif.get("over", 0) > 7200:
                await notify(r["user_id"], tx.user_return_overdue_message(rid, r["dto"]))
                notif["over"] = ts; changed = True

        if r["curator"] and r["status"] == "approved" and start_at:
            left = (start_at - now).total_seconds()
            if 3600 < left <= 86400 and not notif.get("cur_issue_24"):
                await notify(r["curator"], tx.curator_issue_day_message(rid, r["dfrom"]))
                notif["cur_issue_24"] = 1; changed = True
            if 0 < left <= 3600 and not notif.get("cur_issue_1"):
                await notify(r["curator"], tx.curator_issue_hour_message(rid, r["dfrom"]))
                notif["cur_issue_1"] = 1; changed = True

        if r["curator"] and r["status"] == "issued" and deadline:
            left = (deadline - now).total_seconds()
            if 3600 < left <= 86400 and not notif.get("cur_return_24"):
                await notify(r["curator"], tx.curator_return_day_message(rid, r["dto"]))
                notif["cur_return_24"] = 1; changed = True
            if 0 < left <= 3600 and not notif.get("cur_return_1"):
                await notify(r["curator"], tx.curator_return_hour_message(rid, r["dto"]))
                notif["cur_return_1"] = 1; changed = True

        STALE = 6 * 3600
        if r["status"] == "new" and r["created_ts"] and ts - r["created_ts"] > STALE and ts - notif.get("nocur", 0) > STALE:
            await notify(ADMIN_CHAT_ID, tx.stale_request_without_curator_message(rid, int((ts - r["created_ts"]) // 3600)))
            notif["nocur"] = ts; changed = True
        if r["status"] == "curator" and r["created_ts"] and ts - r["created_ts"] > STALE and ts - notif.get("noappr", 0) > STALE:
            await notify(ADMIN_CHAT_ID, tx.stale_request_unapproved_message(rid, _disp_user(r["curator"])))
            notif["noappr"] = ts; changed = True

        auto_cancel = None
        if r["status"] in ("new", "curator") and r["created_ts"] and ts - r["created_ts"] > 3 * 86400:
            auto_cancel = tx.auto_cancel_reason("review_timeout")
        elif r["status"] == "approved" and start_at and now > start_at:
            auto_cancel = tx.auto_cancel_reason("issue_timeout")
        if auto_cancel:
            with db() as c:
                c.execute("UPDATE requests SET status='canceled' WHERE id=?", (rid,))
            _push_hist("requests", rid, "canceled", "автоотмена: " + auto_cancel)
            await notify(r["user_id"], tx.request_auto_canceled_message(rid, auto_cancel))
            with db() as c:
                row = c.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
            await send_or_update_card("requests", row)
            data_changed = True
            continue
        if changed:
            _set_notif("requests", rid, notif)
            data_changed = True

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
            notif["start_wish"] = 1
            changed = True
        if end and now > end and not notif.get("handover_user"):
            await notify(b["user_id"], tx.studio_finished_user_message(b["id"]))
            notif["handover_user"] = 1; changed = True
        if end and now > end and b["curator"] and not notif.get("handover_curator"):
            await notify(b["curator"], tx.studio_finished_curator_message(b["id"], b["day"], b["slot"]))
            notif["handover_curator"] = 1; changed = True
        if changed:
            _set_notif("b626", b["id"], notif)
            data_changed = True

    with db() as c:
        rows = c.execute("SELECT * FROM b626 WHERE status='new'").fetchall()
    for b in rows:
        notif = _get_notif("b626", b)
        if b["created_ts"] and ts - b["created_ts"] > 6 * 3600 and ts - notif.get("noappr", 0) > 6 * 3600:
            await notify(ADMIN_CHAT_ID, tx.stale_studio_booking_message(b["id"], b["day"], b["slot"]))
            notif["noappr"] = ts
            _set_notif("b626", b["id"], notif)
            data_changed = True

    today = now.strftime("%Y-%m-%d")
    if now.hour >= 22 and _meta_get("digest_date") != today:
        _meta_set("digest_date", today); await daily_digest()
    last_bk = _meta_get("backup_date")
    stale_bk = True
    if last_bk:
        try: stale_bk = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(last_bk, "%Y-%m-%d")).days >= 7
        except ValueError: stale_bk = True
    if stale_bk:
        _meta_set("backup_date", today); weekly_backup()
    if now.day == 1 and now.hour >= 12 and _meta_get("monthly_digest") != today:
        _meta_set("monthly_digest", today); await monthly_digest()

    with db() as c:
        for row in c.execute("SELECT id, block_until FROM users WHERE verified='blocked' AND block_until<>''").fetchall():
            if _block_expired(row["block_until"]):
                c.execute("UPDATE users SET verified='ok', block_reason='', block_until='' WHERE id=?", (row["id"],)); data_changed = True
        for row in c.execute("SELECT cat, until FROM cat_blocks WHERE until<>''").fetchall():
            if _cat_until_passed(row["until"]):
                c.execute("DELETE FROM cat_blocks WHERE cat=?", (row["cat"],)); data_changed = True
    if data_changed:
        await sse_broadcast()


def _seconds_to_next_check(now=None) -> float:
    """Секунды до ближайшей границы :00/:05/:10... по московскому времени."""
    current = now or datetime.now(MSK)
    passed = (current.minute % 5) * 60 + current.second + current.microsecond / 1000000.0
    return max(0.05, 300.0 - passed)


async def scheduler_loop() -> None:
    while True:
        try:
            await run_checks()
        except Exception as e:
            log.warning("scheduler: %s", e)
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
    if file.suffix in (".html", ".js", ".css"):
        resp.headers["Cache-Control"] = "no-cache"  # чтобы правки долетали без очистки кэша
    return resp


# ================= Бот =================

@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(tx.start_message(), reply_markup=app_button())


@dp.message(Command("chatid"))
async def cmd_chatid(message: Message) -> None:
    """Прислать id чата - чтобы вписать ADMIN_CHAT_ID в .env."""
    await message.answer(tx.chat_id_message(message.chat.id), parse_mode="HTML")


# Скрытые служебные команды для старших админов (не в меню бота - только знающий напишет руками).
@dp.message(Command("digest"))
async def cmd_digest(message: Message) -> None:
    if not is_senior(message.from_user.id):
        return
    await daily_digest()
    await message.answer(tx.digest_done_message())


@dp.message(Command("backup"))
async def cmd_backup(message: Message) -> None:
    if not is_senior(message.from_user.id):
        return
    weekly_backup()
    await message.answer(tx.backup_done_message())


@dp.message(Command("checks"))
async def cmd_checks(message: Message) -> None:
    if not is_senior(message.from_user.id):
        return
    await run_checks()
    await message.answer(tx.checks_done_message())


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
        await message.answer(tx.add_admin_usage_message())
        return
    with db() as c:
        c.execute("INSERT OR IGNORE INTO extra_admins(user_id, added_by, added_ts) VALUES(?,?,?)",
                  (target, message.from_user.id, datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S")))
    EXTRA_ADMIN_IDS.add(target)
    await message.answer(tx.admin_added_message(target))


@dp.message(Command("deladmin"))
async def cmd_deladmin(message: Message) -> None:
    if not is_senior(message.from_user.id):
        return
    target = _parse_id_arg(message)
    if target is None:
        await message.answer(tx.delete_admin_usage_message())
        return
    with db() as c:
        c.execute("DELETE FROM extra_admins WHERE user_id=?", (target,))
    EXTRA_ADMIN_IDS.discard(target)
    await message.answer(tx.admin_deleted_message(target))


@dp.message(Command("admins"))
async def cmd_admins(message: Message) -> None:
    if not is_senior(message.from_user.id):
        return
    await message.answer(tx.admins_list_message(SENIOR_ADMIN_IDS, ADMIN_IDS, EXTRA_ADMIN_IDS))


@dp.message(F.chat.type == "private")
async def any_private(message: Message) -> None:
    # переслали пост из канала - подсказываем его id для ADMIN_CHAT_ID
    fo = getattr(message, "forward_origin", None)
    fchat = getattr(fo, "chat", None) if fo else None
    if fchat is not None:
        await message.answer(tx.forwarded_chat_id_message(fchat.id), parse_mode="HTML")
        return
    await message.answer(tx.private_fallback_message(),
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
    app.router.add_post("/api/register", api_register)
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

    if dev_mode:
        log.warning("DEV-режим: бот не запущен (нет BOT_TOKEN), все запросы = пользователь %s. "
                    "Только для локальных тестов!", DEV_USER_ID)
        try:
            await asyncio.Event().wait()
        finally:
            sched.cancel()
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
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())

