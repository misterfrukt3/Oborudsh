import tempfile
import unittest
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
        with main.db() as c:
            c.execute("INSERT INTO users(id, name, role, agreed, verified) VALUES(1, 'Test User Name', 'стажёр', 1, 'ok')")

    def tearDown(self):
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
        slot, error = main.validate_626_window("2030-06-03", "09:00–10:00")
        self.assertIsNone(error)
        self.assertEqual(slot, "09:00–10:00")


if __name__ == "__main__":
    unittest.main()
