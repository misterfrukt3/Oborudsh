import asyncio
import sqlite3
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path

import main


class CoreRulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_db = main.DB_PATH
        main.DB_PATH = Path(self.tmp.name) / "test.db"
        main.init_db()
        main._migrate()
        main.load_catalog()
        main.sync_equipment_units()
        with main.db() as c:
            c.execute("INSERT INTO users(id, name, role, agreed, verified) VALUES(1, 'Test User Name', 'стажёр', 1, 'ok')")

    def tearDown(self):
        main.SSE_CLIENTS.clear()
        main.DB_PATH = self.old_db
        self.tmp.cleanup()

    def test_equipment_window_rejects_invalid_rules(self):
        self.assertIsNotNone(main.validate_request_window("2000-01-01", "2000-01-01", "09:00", "10:00"))
        self.assertIsNotNone(main.validate_request_window("2030-06-02", "2030-06-03", "09:00", "10:00"))  # Sunday

    def test_items_must_exist_and_have_valid_quantity(self):
        _, error = main.validate_items(1, [["not in catalog", 1]])
        self.assertIsNotNone(error)
        short = next(iter(main.CATALOG_META))
        _, error = main.validate_items(1, [[short, 0]])
        self.assertIsNotNone(error)

    def test_studio_range_accepts_frontend_dash_and_detects_slots(self):
        self.assertEqual(main.slot_expand("09:00–10:00"), ["09:00", "09:30"])
    def test_db_context_closes_connection(self):
        with main.db() as connection:
            connection.execute("SELECT 1").fetchone()
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_revision_changes_only_after_mutation(self):
        before = main.db_revision()
        self.assertEqual(before, main.db_revision())
        with main.db() as c:
            c.execute("UPDATE users SET username='changed' WHERE id=1")
        self.assertNotEqual(before, main.db_revision())

    def test_score_events_are_decimal_and_idempotent(self):
        with main.db() as c:
            c.execute("INSERT INTO users(id,name,agreed,verified) VALUES(2,'Admin Two Name',1,'ok')")
            c.execute("INSERT INTO users(id,name,agreed,verified) VALUES(3,'Admin Three Name',1,'ok')")
            c.execute("INSERT INTO actions(admin_id,kind,ref,action,ts) VALUES(2,'requests',77,'issue','2030-01-01 10:00:00')")
            c.execute("INSERT INTO actions(admin_id,kind,ref,action,ts) VALUES(2,'requests',77,'return_closed','2030-01-01 11:00:00')")
            c.execute("INSERT INTO actions(admin_id,kind,ref,action,ts) VALUES(3,'requests',77,'return_closed','2030-01-01 11:00:00')")
        self.assertEqual(main.enqueue_request_scores(77), 2)
        self.assertEqual(main.enqueue_request_scores(77), 0)
        with main.db() as c:
            rows = c.execute("SELECT event_id,points FROM score_events ORDER BY event_id").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum((Decimal(row["points"]) for row in rows), Decimal("0")), Decimal("0.02"))

    def test_disabled_google_keeps_local_queue(self):
        old = main.GOOGLE_SHEETS_ENABLED
        main.GOOGLE_SHEETS_ENABLED = False
        try:
            self.assertTrue(main.enqueue_score("daily_admin:2030-01-01", 1, "daily_admin", "2030-01-01", Decimal("0.1"), "test"))
            status = main.score_status()
            self.assertFalse(status["googleEnabled"])
            self.assertEqual(status["pending"], 1)
        finally:
            main.GOOGLE_SHEETS_ENABLED = old

    def test_daily_admin_awarded_once_and_626_key_is_unique(self):
        today = main.datetime.now(main.MSK).strftime("%Y-%m-%d")
        with main.db() as c:
            c.execute("INSERT INTO actions(admin_id,kind,ref,action,ts) VALUES(1,'requests',1,'issue',?)",
                      (today + " 12:00:00",))

        class FakeBot:
            def __init__(self):
                self.rich = []

            async def send_rich_message(self, chat_id, rich_message):
                self.rich.append((chat_id, rich_message))

            async def send_message(self, chat_id, text):
                raise AssertionError("plain fallback should not be used")

        old_bot, old_chat = main.bot, main.ADMIN_CHAT_ID
        fake = FakeBot()
        main.bot, main.ADMIN_CHAT_ID = fake, 123
        try:
            asyncio.run(main.daily_digest(award_score=True))
            asyncio.run(main.daily_digest(award_score=True))
        finally:
            main.bot, main.ADMIN_CHAT_ID = old_bot, old_chat
        with main.db() as c:
            daily = c.execute("SELECT COUNT(*) n FROM score_events WHERE event_id=?",
                              ("daily_admin:" + today,)).fetchone()["n"]
        self.assertEqual(daily, 1)
        self.assertTrue(fake.rich)
        self.assertTrue(main.enqueue_score("626:9:1", 1, "626", 9, Decimal("0.05"), "626"))
        self.assertFalse(main.enqueue_score("626:9:1", 1, "626", 9, Decimal("0.05"), "626"))

    def test_boot_payload_handles_500_requests_quickly(self):
        rows = [(1, "[]", "01.01.2030", "02.01.2030", "event", "", "new", "[]",
                 "2030-01-01", "2030-01-02", "09:00", "10:00") for _ in range(500)]
        with main.db() as c:
            c.executemany("""INSERT INTO requests(
                user_id,items,dfrom,dto,event,comment,status,history,dfrom_iso,dto_iso,tfrom,tto
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        started = time.perf_counter()
        payload = main.boot_payload(1)
        self.assertEqual(len(payload["requests"]), 500)
        self.assertLess(time.perf_counter() - started, 5.0)

    def test_markdown_exports_and_rich_chunks(self):
        for kind in ("requests", "626", "admins"):
            filename, document = main.build_export_text(kind)
            self.assertTrue(filename.endswith(".md"))
            self.assertIn("# ", document)
            self.assertNotIn("|---", document)
        chunks = main._rich_chunks(["A" * 20000, "B" * 20000])
        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(len(chunk) <= 30000 for chunk in chunks))
        slot, error = main.validate_626_window("2030-06-03", "09:00–10:00")
        self.assertIsNone(error)
        self.assertEqual(slot, "09:00–10:00")


    def test_equipment_schema_and_passports_exist_after_migration(self):
        with main.db() as c:
            tables = {row["name"] for row in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            columns = {row["name"] for row in c.execute("PRAGMA table_info(requests)").fetchall()}
            units = c.execute("SELECT COUNT(*) n FROM equipment_units").fetchone()["n"]
        self.assertIn("equipment_units", tables)
        self.assertIn("issued_by", columns)
        self.assertIn("returned_by", columns)
        self.assertGreater(units, 0)

    def test_repair_unit_is_not_assigned_and_preferred_is_validated(self):
        short = next(
            name for name, meta in main.CATALOG_META.items() if int(meta["total"]) >= 2
        )
        allowed = main.ready_numbers(short)
        first, second = allowed[:2]
        with main.db() as c:
            c.execute(
                "UPDATE equipment_units SET state='repair' WHERE short=? AND num=?",
                (short, first),
            )
        assigned, error = main.assign_numbers([[short, 1]], "2030-01-01", "2030-01-02")
        self.assertIsNone(error)
        self.assertEqual(assigned[short], [second])
        assigned, error = main.assign_numbers(
            [[short, 1]], "2030-01-01", "2030-01-02",
            preferred={short: [first]},
        )
        self.assertIsNone(assigned)
        self.assertIsNotNone(error)

    def test_unit_passport_contains_request_history(self):
        short = next(iter(main.CATALOG_META))
        with main.db() as c:
            c.execute("INSERT INTO users(id,name,agreed,verified) VALUES(2,'Admin Two Name',1,'ok')")
            c.execute(
                """INSERT INTO requests(
                   user_id,items,dfrom,dto,event,status,history,dfrom_iso,dto_iso,
                   tfrom,tto,nums,issued_by,returned_by,taken_at,returned_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (1, f'[["{short}",1]]', "01.01.2030", "02.01.2030", "Test", "closed",
                 "[]", "2030-01-01", "2030-01-02", "09:00", "10:00",
                 '{"%s":[1]}' % short.replace('"', '\\"'), 2, 2, "01.01, 09:00", "02.01, 10:00"),
            )
        passport = main.unit_passport(short, 1)
        self.assertEqual(passport["short"], short)
        self.assertEqual(passport["history"][0]["status"], "closed")
        self.assertNotEqual(passport["history"][0]["issuedBy"], "—")

    def test_sse_broadcast_coalesces_revision_signal(self):
        async def scenario():
            queue = asyncio.Queue(maxsize=1)
            main.SSE_CLIENTS.add(queue)
            await main.sse_broadcast()
            await main.sse_broadcast()
            return queue.qsize(), await queue.get()
        size, revision = asyncio.run(scenario())
        self.assertEqual(size, 1)
        self.assertEqual(revision, main.db_revision())

    def test_scheduler_aligns_to_five_minute_boundary(self):
        point = main.datetime(2030, 1, 1, 12, 3, 20, tzinfo=main.MSK)
        self.assertAlmostEqual(main._seconds_to_next_check(point), 100.0)
        boundary = main.datetime(2030, 1, 1, 12, 5, 0, tzinfo=main.MSK)
        self.assertAlmostEqual(main._seconds_to_next_check(boundary), 300.0)

    def test_feature_flags_and_editable_texts(self):
        payload = main.boot_payload(1)
        self.assertEqual(payload["features"]["productionRole"], main.ENABLE_PRODUCTION_ROLE)
        old_admins = set(main.ADMIN_IDS)
        try:
            main.ADMIN_IDS.add(1)
            self.assertIn("equipmentUnits", main.boot_payload(1))
        finally:
            main.ADMIN_IDS.clear()
            main.ADMIN_IDS.update(old_admins)
        message = main.tx.equipment_issued_message(
            7, [["Камера", 1]], "02.01.2030", "", {"Камера": {"cat": "Камеры"}}
        )
        self.assertIn("Оборудование выдано", message)
        self.assertNotIn("??", message)
        card = main.tx.request_card_message(
            1, "new", "Иван [тест]", "@user_name", "01.01", "02.01",
            "Съёмка!", [["R8", 1]], "Комментарий.", "", "",
        )
        self.assertIn(r"\[тест\]", card)
        self.assertIn(r"Съёмка\!", card)

    def test_sources_have_no_broken_question_mark_runs(self):
        for filename in ("main.py", "texts.py"):
            source = (Path(__file__).parent / filename).read_text(encoding="utf-8")
            self.assertNotIn("??", source, filename)


    def test_catalog_short_names_and_allowed_numbers_are_valid(self):
        raw = (main.WEBAPP_DIR / "catalog.js").read_text(encoding="utf-8")
        data = main.json.loads(raw[raw.index("["):raw.rindex("]") + 1])
        items = [item for category in data for item in category["items"]]
        shorts = [item["short"] for item in items]
        self.assertEqual(len(shorts), len(set(shorts)))
        self.assertTrue(all(item.get("numbers") for item in items))
        pooled = next(
            item for item in items if len(item["numbers"]) > item["total"]
        )
        self.assertEqual(
            main.ready_capacity(pooled["short"]),
            pooled["total"],
        )
        with main.db() as connection:
            unit_numbers = {
                row["num"]
                for row in connection.execute(
                    "SELECT num FROM equipment_units WHERE short=?",
                    (pooled["short"],),
                ).fetchall()
            }
        self.assertEqual(unit_numbers, set(pooled["numbers"]))

    def test_people_sheet_username_merges_all_access(self):
        values = [
            ["ФИО", "ТГ", "Отделы Media BMSTU", "Роль Media BMSTU", "Организации"],
            ["Иванов Иван Иванович", "@Ivan", "SMM", "Стажёр", "КвизON"],
            ["Иванов Иван Иванович", "https://t.me/ivan", "Фото", "Активист", "Art Factory BMSTU"],
        ]
        directory = main._build_member_username_directory(values)
        member = directory["ivan"]
        self.assertEqual(member["role"], "активист")
        self.assertEqual(member["deps"], ["СММ", "Фото"])
        self.assertEqual(
            member["orgs"],
            ["Media BMSTU", "КвизON", "Art Factory BMSTU"],
        )
        main._apply_sheet_member(1, member)
        user = main.get_user(1)
        self.assertEqual(user["verified"], "ok")
        self.assertEqual(user["agreed"], 1)
        self.assertEqual(user["name"], "Иванов Иван Иванович")
        self.assertEqual(main.json.loads(user["orgs"]), member["orgs"])
        self.assertTrue(
            main.enqueue_score(
                "people-test:1", 1, "test", 1, Decimal("0.1"), "people"
            )
        )
        with main.db() as connection:
            score = connection.execute(
                "SELECT fio,points FROM score_events WHERE event_id='people-test:1'"
            ).fetchone()
        self.assertEqual(score["fio"], "Иванов Иван Иванович")
        self.assertEqual(score["points"], "0.1")

    def test_agree_endpoint_auto_registers_by_telegram_username(self):
        member = {
            "name": "Иванов Иван Иванович",
            "telegram": "@dev",
            "orgs": ["Media BMSTU", "КвизON"],
            "deps": ["Фото"],
            "role": "активист",
        }

        class FakeRequest:
            async def json(self):
                return {}

        async def fake_lookup(username, force=False):
            self.assertEqual(username, "dev")
            return {"status": "found", "member": member}

        old_dev = main.DEV_USER_ID
        old_lookup = main.lookup_member_by_username
        main.DEV_USER_ID = 1
        main.lookup_member_by_username = fake_lookup
        try:
            response = asyncio.run(main.api_agree(FakeRequest()))
        finally:
            main.DEV_USER_ID = old_dev
            main.lookup_member_by_username = old_lookup
        payload = main.json.loads(response.text)
        self.assertTrue(payload["autoRegistered"])
        self.assertTrue(payload["registered"])
        self.assertEqual(payload["verified"], "ok")
        self.assertEqual(payload["profile"]["orgs"], member["orgs"])
        self.assertEqual(payload["profile"]["deps"], member["deps"])
        self.assertEqual(payload["profile"]["status"], "активист")

    def test_legacy_mailing_reads_old_db_without_touching_new_db(self):
        legacy = Path(self.tmp.name) / "old.sqlite3"
        source = sqlite3.connect(legacy)
        source.execute(
            "CREATE TABLE users(user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT)"
        )
        source.execute(
            "CREATE TABLE checkouts(id INTEGER PRIMARY KEY, user_id INTEGER)"
        )
        source.execute(
            "INSERT INTO users VALUES(55,'legacy_user','Legacy User Name')"
        )
        source.execute("INSERT INTO checkouts VALUES(1,55)")
        source.commit()
        source.close()

        class FakeBot:
            def __init__(self):
                self.sent = []

            async def send_message(self, user_id, text):
                self.sent.append((user_id, text))

        old_legacy, old_bot = main.LEGACY_DB_PATH, main.bot
        fake = FakeBot()
        main.LEGACY_DB_PATH, main.bot = legacy, fake
        try:
            preview = main.read_legacy_recipients()
            result = asyncio.run(main.send_legacy_invites())
        finally:
            main.LEGACY_DB_PATH, main.bot = old_legacy, old_bot
        self.assertEqual(
            preview,
            [{"user_id": 55, "username": "legacy_user", "name": "Legacy User Name"}],
        )
        self.assertEqual(result, {"source": 1, "sent": 1, "failed": 0})
        self.assertEqual(fake.sent[0][0], 55)
        with main.db() as connection:
            imported = connection.execute(
                "SELECT COUNT(*) n FROM users WHERE id=55"
            ).fetchone()["n"]
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        self.assertEqual(imported, 0)
        self.assertNotIn("legacy_invites", tables)


    def test_manual_does_not_describe_production_role(self):
        source = (main.WEBAPP_DIR / "index.html").read_text(encoding="utf-8")
        manual = source[source.index("SCREENS.manual"):source.index("const SO_ORGS")]
        self.assertNotIn("production", manual)


if __name__ == "__main__":
    unittest.main()
