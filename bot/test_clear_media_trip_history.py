import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing

from clear_media_trip_history import clear_history


class ClearTripHistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = Path(self.tmp.name) / 'test.db'
        with closing(sqlite3.connect(self.database)) as c, c:
            c.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE trip_requests(id INTEGER PRIMARY KEY, status TEXT);
                INSERT INTO trip_requests VALUES(1,'returned'),(2,'new');
                CREATE TABLE trip_history(ref INTEGER);
                INSERT INTO trip_history VALUES(1),(2);
                CREATE TABLE trip_outbox(key TEXT);
                INSERT INTO trip_outbox VALUES('new:1'),('block:1');
                CREATE TABLE trip_teams(number INTEGER PRIMARY KEY, deleted INTEGER);
                INSERT INTO trip_teams VALUES(1,0),(2,1);
                CREATE TABLE trip_members(uid INTEGER,team INTEGER);
                INSERT INTO trip_members VALUES(1,1),(2,2);
                CREATE TABLE users(id INTEGER,role TEXT);
                INSERT INTO users VALUES(1,'активист');
                CREATE TABLE requests(id INTEGER,status TEXT);
                INSERT INTO requests VALUES(1,'issued');
                CREATE TABLE b626(id INTEGER);
                INSERT INTO b626 VALUES(1);
                CREATE TABLE trip_items(id INTEGER);
                INSERT INTO trip_items VALUES(1);
                CREATE TABLE trip_blocks(id INTEGER);
                INSERT INTO trip_blocks VALUES(1);
                CREATE TABLE trip_settings(data TEXT);
                INSERT INTO trip_settings VALUES('settings');
            ''')

    def dump(self, path=None):
        with closing(sqlite3.connect(path or self.database)) as c, c:
            tables = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            return {name: c.execute(f'SELECT * FROM {name}').fetchall() for (name,) in tables}

    def test_preview_does_not_change_database_or_make_backup(self):
        before = self.dump()
        report = clear_history(self.database, 'clear')
        self.assertFalse(report['applied'])
        self.assertEqual(report['before']['trip_requests'], 2)
        self.assertEqual(self.dump(), before)
        self.assertFalse((self.database.parent / 'backup').exists())

    def test_clear_teams_preserves_other_data_and_backup_contains_original(self):
        before = self.dump()
        report = clear_history(self.database, 'clear', True)
        self.assertTrue(report['applied'])
        self.assertEqual(self.dump(report['backup']), before)
        after = self.dump()
        for table in ('trip_requests', 'trip_history', 'trip_outbox', 'trip_teams', 'trip_members'):
            self.assertEqual(after[table], [])
        for table in ('users', 'requests', 'b626', 'trip_settings', 'trip_blocks', 'trip_items'):
            self.assertEqual(after[table], before[table])
        with closing(sqlite3.connect(self.database)) as c, c:
            c.execute('INSERT INTO trip_teams VALUES(2,0)')

    def test_keep_live_teams_and_release_deleted_team_numbers(self):
        report = clear_history(self.database, 'keep', True)
        self.assertEqual(report['after']['trip_requests'], 0)
        after = self.dump()
        self.assertEqual(after['trip_teams'], [(1, 0)])
        self.assertEqual(after['trip_members'], [(1, 1)])

    def test_issued_trip_equipment_prevents_clear(self):
        with closing(sqlite3.connect(self.database)) as c, c:
            c.execute("UPDATE trip_requests SET status='issued' WHERE id=2")
        before = self.dump()
        with self.assertRaisesRegex(ValueError, 'выданное оборудование'):
            clear_history(self.database, 'clear', True)
        self.assertEqual(self.dump(), before)

    def test_typo_does_not_create_database(self):
        missing = self.database.parent / 'missing.db'
        with self.assertRaises(FileNotFoundError):
            clear_history(missing, 'clear', True)
        self.assertFalse(missing.exists())

    def test_delete_failure_rolls_back_every_table(self):
        with closing(sqlite3.connect(self.database)) as c, c:
            c.execute("CREATE TRIGGER stop_clear BEFORE DELETE ON trip_requests BEGIN SELECT RAISE(ABORT,'test failure'); END")
        before = self.dump()
        with self.assertRaises(sqlite3.IntegrityError):
            clear_history(self.database, 'clear', True)
        self.assertEqual(self.dump(), before)


if __name__ == '__main__':
    unittest.main()
