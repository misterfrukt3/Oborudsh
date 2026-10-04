import asyncio
import json
import time
import unittest
from unittest.mock import AsyncMock, patch

import main
import test_core
from media_trip import TESTERS
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


class MediaTripTest(unittest.TestCase):
    setUp = test_core.CoreRulesTest.setUp
    tearDown = test_core.CoreRulesTest.tearDown
    admin = 1896340090

    def call(self, body, uid=None):
        with patch.object(main, 'boot_payload', return_value={'ok': True}):
            return asyncio.run(main.MEDIA_TRIP.handle(body, self.admin if uid is None else uid))

    def setup_trip(self):
        self.assertEqual(self.call(dict(action='settings', testing=False, staff=[self.admin], place='Рентал', channel=-10099)).status, 200)
        self.assertEqual(self.call(dict(action='team', number=1, curator=1)).status, 200)
        now = time.time()
        with main.db() as c:
            block = c.execute("INSERT INTO trip_blocks(kind,start,end) VALUES('task',?,?)", (now + 1800, now + 3600)).lastrowid
            item = c.execute("INSERT INTO trip_items(name,total) VALUES('Камера',1)").lastrowid
        return block, item

    def create(self, block, uid=1):
        return self.call(dict(action='create', block=block, needs={'Камера (видео)': 1}, purpose='Снимаем интервью'), uid)

    def ref(self):
        with main.db() as c:
            return c.execute('SELECT MAX(id) FROM trip_requests').fetchone()[0]

    def change(self, ref, status, **args):
        return self.call(dict(action='request', id=ref, status=status, **args))

    def test_testers_gate_is_enforced_on_server(self):
        self.assertFalse(main.MEDIA_TRIP.payload(1)['allowed'])
        self.assertEqual(self.call(dict(action='join', code='none'), 1).status, 403)
        self.assertTrue(main.MEDIA_TRIP.payload(self.admin)['canManage'])
        self.assertEqual(len(TESTERS), 6)

    def test_membership_and_curator_permissions(self):
        self.setup_trip()
        with main.db() as c:
            code = c.execute('SELECT code FROM trip_teams WHERE number=1').fetchone()[0]
        self.assertEqual(self.call(dict(action='join', code=code), 2).status, 200)
        self.assertEqual(self.call(dict(action='members', number=1, members=[3]), 2).status, 403)
        self.assertEqual(self.call(dict(action='members', number=1, members=[3]), 1).status, 200)
        self.assertEqual(self.call(dict(action='block', kind='task', start='2030-01-01T10:00', end='2030-01-01T11:00'), 1).status, 403)
        self.assertEqual(self.call(dict(action='settings', testing=False, staff=[], place='', channel=0)).status, 400)

    def test_delete_empty_team_releases_members_and_invalidates_code(self):
        self.setup_trip()
        self.call(dict(action='members', number=1, members=[2]), 1)
        with main.db() as c:
            code = c.execute('SELECT code FROM trip_teams WHERE number=1').fetchone()[0]
        for uid in (1, 2, 1122855409):
            self.assertEqual(self.call(dict(action='delete_team', number=1), uid).status, 403)
        self.assertEqual(self.call(dict(action='delete_team', number=999)).status, 400)
        self.assertEqual(self.call(dict(action='delete_team', number='bad')).status, 400)
        before = main.db_revision()
        self.assertEqual(self.call(dict(action='delete_team', number=1)).status, 200)
        self.assertNotEqual(before, main.db_revision())
        self.assertEqual(main.MEDIA_TRIP.payload(self.admin)['teams'], [])
        for uid in (1, 2):
            self.assertIsNone(main.MEDIA_TRIP.payload(uid)['team'])
        self.assertEqual(self.call(dict(action='join', code=code), 2).status, 400)
        self.assertEqual(self.call(dict(action='delete_team', number=1)).status, 400)
        self.assertEqual(self.call(dict(action='team', number=1, curator=1)).status, 200)
        with main.db() as c:
            self.assertNotEqual(code, c.execute('SELECT code FROM trip_teams WHERE number=1').fetchone()[0])
        self.assertEqual(self.call(dict(action='join', code=code), 2).status, 400)
        self.assertEqual(self.call(dict(action='team', number=2, curator=2)).status, 200)

    def test_delete_team_blocks_every_active_status_including_overdue_issue(self):
        block, item = self.setup_trip()
        self.create(block)
        ref = self.ref()
        for status in ('new', 'assembling', 'ready', 'issued'):
            if status != 'new':
                self.assertEqual(self.change(ref, status, kit=[[item, 1]]).status, 200)
            if status == 'issued':
                with main.db() as c:
                    c.execute('UPDATE trip_blocks SET start=?,end=? WHERE id=?',
                              (time.time()-7200, time.time()-3600, block))
            with self.subTest(status=status):
                response = self.call(dict(action='delete_team', number=1))
                self.assertEqual(response.status, 400)
                self.assertIn('активные заявки', json.loads(response.text)['error'])
                self.assertEqual(main.MEDIA_TRIP.payload(1)['team'], 1)
                self.assertEqual(main.MEDIA_TRIP.payload(self.admin)['requests'][0]['status'], status)
        self.assertEqual(self.change(ref, 'returned').status, 200)
        self.assertEqual(self.call(dict(action='delete_team', number=1)).status, 200)

    def test_delete_team_preserves_terminal_requests_and_reserves_history_number(self):
        block, item = self.setup_trip()
        for status in ('canceled', 'rejected', 'returned'):
            self.create(block)
            ref = self.ref()
            if status == 'canceled':
                self.assertEqual(self.call(dict(action='request', id=ref, status=status), 1).status, 200)
            elif status == 'rejected':
                self.assertEqual(self.change(ref, status, reason='Нет камеры').status, 200)
            else:
                for target in ('assembling', 'ready', 'issued', 'returned'):
                    self.assertEqual(self.change(ref, target, kit=[[item, 1]]).status, 200)
        before = main.MEDIA_TRIP.payload(self.admin)['requests']
        with main.db() as c:
            code = c.execute('SELECT code FROM trip_teams WHERE number=1').fetchone()[0]
        self.assertEqual(self.call(dict(action='delete_team', number=1)).status, 200)
        self.assertEqual(main.MEDIA_TRIP.payload(self.admin)['requests'], before)
        self.assertEqual(main.MEDIA_TRIP.payload(self.admin)['teams'], [])
        self.assertEqual(main.MEDIA_TRIP.payload(1)['requests'], [])
        self.assertEqual(self.call(dict(action='join', code=code), 2).status, 400)
        self.assertEqual(self.call(dict(action='members', number=1, members=[2])).status, 403)
        self.assertEqual(self.call(dict(action='members', number=1, members=[2]), 1).status, 403)
        self.assertEqual(self.call(dict(action='team', number=1, curator=2)).status, 400)
        self.assertEqual(self.call(dict(action='team', number=2, curator=1)).status, 200)
        self.assertEqual(main.MEDIA_TRIP.payload(1)['requests'], [])

    def test_delete_team_available_to_testers_in_testing_mode(self):
        self.assertEqual(self.call(dict(action='team', number=1, curator=self.admin)).status, 200)
        self.assertEqual(self.call(dict(action='delete_team', number=1), 1).status, 403)
        self.assertEqual(self.call(dict(action='delete_team', number=1), 1122855409).status, 200)

    def test_team_deletion_migration_preserves_existing_teams(self):
        # This fixture uses only the temporary database from CoreRulesTest.setUp.
        with main.db() as c:
            c.execute('DROP TABLE trip_teams')
            c.execute('CREATE TABLE trip_teams(number INTEGER PRIMARY KEY, curator INTEGER NOT NULL, code TEXT UNIQUE NOT NULL)')
            c.execute("INSERT INTO trip_teams VALUES(1,?,'legacy-code')", (self.admin,))
            c.execute('INSERT INTO trip_members VALUES(?,1)', (self.admin,))
        main.MEDIA_TRIP.schema()
        main.MEDIA_TRIP.schema()
        team = main.MEDIA_TRIP.payload(self.admin)['teams'][0]
        self.assertEqual((team['number'], team['curator'], team['code']), (1, self.admin, 'legacy-code'))
        self.assertEqual(team['members'][0]['id'], self.admin)
        self.assertEqual(self.call(dict(action='delete_team', number=1)).status, 200)

    def test_one_active_request_nearest_block_and_full_lifecycle(self):
        block, item = self.setup_trip()
        with main.db() as c:
            later = c.execute("INSERT INTO trip_blocks(kind,start,end) VALUES('night',?,?)", (time.time()+7200,time.time()+28800)).lastrowid
        self.assertEqual(self.create(later).status, 400)
        self.assertEqual(self.create(block).status, 200)
        ref = self.ref()
        self.assertEqual(self.create(block).status, 400)
        self.assertEqual(self.call(dict(action='request',id=ref,status='assembling'),1).status,403)
        self.assertEqual(self.change(ref,'issued').status,400)
        self.assertEqual(self.change(ref,'assembling').status,200)
        self.assertEqual(self.change(ref,'ready',kit=[]).status,400)
        self.assertEqual(self.change(ref,'ready',kit=[[item,1]]).status,200)
        self.assertEqual(self.change(ref,'issued').status,200)
        self.assertEqual(self.call(dict(action='request',id=ref,status='canceled'),1).status,400)
        self.assertEqual(self.change(ref,'returned').status,200)
        self.assertEqual(self.create(block).status,200)

    def test_stock_reserved_and_overdue_equipment_blocks_other_teams(self):
        block, item = self.setup_trip()
        self.create(block);first=self.ref()
        self.change(first,'assembling');self.change(first,'ready',kit=[[item,1]])
        self.call(dict(action='team',number=2,curator=2))
        self.create(block,2);second=self.ref();self.change(second,'assembling')
        self.assertEqual(self.change(second,'ready',kit=[[item,1]]).status,400)
        self.change(first,'issued')
        with main.db() as c:
            c.execute('UPDATE trip_blocks SET start=?,end=? WHERE id=?',(time.time()-7200,time.time()-3600,block))
            upcoming=c.execute("INSERT INTO trip_blocks(kind,start,end) VALUES('task',?,?)",(time.time()+300,time.time()+3600)).lastrowid
        self.create(upcoming,2);third=self.ref();self.change(third,'assembling')
        self.assertEqual(self.change(third,'ready',kit=[[item,1]]).status,400)
        self.change(first,'returned')
        self.assertEqual(self.change(third,'ready',kit=[[item,1]]).status,200)

    def test_schedule_moscow_time_overnight_and_overlap(self):
        self.setup_trip()
        self.assertEqual(self.call(dict(action='block',kind='night',start='2030-02-01T23:00',end='2030-02-02T08:00')).status,200)
        self.assertEqual(self.call(dict(action='block',kind='task',start='2030-02-02T07:00',end='2030-02-02T09:00')).status,400)
        self.assertEqual(self.call(dict(action='block',kind='task',start='2030-02-02T08:00',end='2030-02-02T09:00')).status,200)
        stamp=main.MEDIA_TRIP.stamp('2030-02-01T23:00')
        self.assertEqual(main.MEDIA_TRIP.fmt(stamp),'01.02 23:00')

    def test_reminders_all_members_and_overdue_deduplicated(self):
        block,item=self.setup_trip()
        self.call(dict(action='members',number=1,members=[2]),1)
        self.create(block);ref=self.ref();self.change(ref,'assembling');self.change(ref,'ready',kit=[[item,1]]);self.change(ref,'issued')
        now=time.time()
        fake=type('FakeBot',(),{'send_message':AsyncMock()})()
        with patch.object(main,'bot',fake):
            asyncio.run(main.MEDIA_TRIP.tick(now+1));count=fake.send_message.await_count
            asyncio.run(main.MEDIA_TRIP.tick(now+1));self.assertEqual(count,fake.send_message.await_count)
            asyncio.run(main.MEDIA_TRIP.tick(now+2800))
            messages=[a.args for a in fake.send_message.await_args_list]
            self.assertEqual({a[0] for a in messages if 'пора вернуть' in a[1]}, {1,2})
            asyncio.run(main.MEDIA_TRIP.tick(now+3700));count=fake.send_message.await_count
            asyncio.run(main.MEDIA_TRIP.tick(now+3700));self.assertEqual(count,fake.send_message.await_count)
            self.assertTrue(any(a.args[0]==-10099 and 'ещё не вернула' in a.args[1] for a in fake.send_message.await_args_list))

    def test_failed_notifications_retry_and_stale_ready_is_suppressed(self):
        block,item=self.setup_trip();self.create(block);ref=self.ref()
        self.change(ref,'assembling');self.change(ref,'ready',kit=[[item,1]])
        fake=type('FakeBot',(),{'send_message':AsyncMock(side_effect=RuntimeError('offline'))})()
        with patch.object(main,'bot',fake):
            asyncio.run(main.MEDIA_TRIP.tick())
            with main.db() as c:self.assertGreater(c.execute('SELECT COUNT(*) FROM trip_outbox WHERE sent=0').fetchone()[0],0)
            self.call(dict(action='request',id=ref,status='canceled'),1)
            fake.send_message.side_effect=None;fake.send_message.reset_mock()
            asyncio.run(main.MEDIA_TRIP.tick(time.time()+60))
            self.assertFalse(any('Подойдите' in a.args[1] for a in fake.send_message.await_args_list))

    def test_rejection_requires_reason_and_catalog_preserves_special_names(self):
        block,item=self.setup_trip();self.create(block);ref=self.ref()
        self.assertEqual(self.change(ref,'rejected').status,400)
        self.assertEqual(self.change(ref,'rejected',reason='Нет свободных камер').status,200)
        self.call(dict(action='item',name='SmallRig " -> <тест>',total=2))
        self.assertTrue(any(i['name']=='SmallRig " -> <тест>' for i in main.MEDIA_TRIP.payload(1)['items']))

    def test_authenticated_http_gate_and_revision_updates(self):
        async def scenario():
            app=web.Application();app.router.add_post('/api/media-trip',main.api_media_trip)
            async with TestClient(TestServer(app)) as client:
                with patch.object(main,'DEV_USER_ID',0),patch.object(main,'check_init_data',return_value=None):
                    response=await client.post('/api/media-trip',json={'action':'team','number':1,'curator':1})
                    self.assertEqual(response.status,401)
                with patch.object(main,'DEV_USER_ID',0),patch.object(main,'check_init_data',return_value={'id':1}):
                    response=await client.post('/api/media-trip',json={'action':'team','number':1,'curator':1})
                    self.assertEqual(response.status,403)
                before=main.db_revision()
                with patch.object(main,'DEV_USER_ID',0),patch.object(main,'check_init_data',return_value={'id':self.admin}):
                    response=await client.post('/api/media-trip',json={'action':'team','number':1,'curator':self.admin})
                    self.assertEqual(response.status,200)
                    payload=await response.json()
                    self.assertTrue(payload['mediaTrip']['canManage'])
                    self.assertNotEqual(before,payload['revision'])
                    before = payload['revision']
                    response = await client.post('/api/media-trip', json={'action':'delete_team','number':1})
                    self.assertEqual(response.status, 200)
                    payload = await response.json()
                    self.assertEqual(payload['mediaTrip']['teams'], [])
                    self.assertIsNone(payload['mediaTrip']['team'])
                    self.assertNotEqual(before, payload['revision'])
        asyncio.run(scenario())


if __name__ == '__main__':
    unittest.main()
