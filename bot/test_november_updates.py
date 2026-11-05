"""Ноябрьские правки: временная БД, Telegram и Google не вызываются."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import main
import test_core
import test_workflows
from test_admin_requests import JuneClock


class NovemberUpdatesTest(unittest.TestCase):
    def setUp(self):
        test_core.CoreRulesTest.setUp(self)
        for ctx in (patch.object(main, 'datetime', JuneClock),
                    patch.object(main, 'is_admin', side_effect=lambda uid: uid in (2, 3, 4)),
                    patch.object(main, 'is_senior', side_effect=lambda uid: uid == 3),
                    patch.object(main, 'bot', None),
                    patch.object(main, 'notify', new=AsyncMock()),
                    patch.object(main, 'send_or_update_card', new=AsyncMock())):
            ctx.start()
            self.addCleanup(ctx.stop)
        with main.db() as c:
            c.executemany("INSERT INTO users(id,name,username,agreed,verified) VALUES(?,?,?,1,'ok')",
                          [(2, 'Администратор Два', 'admin2'), (3, 'Старший Три', 'senior3'),
                           (4, 'Администратор Четыре', 'admin4'), (5, 'Другой Пользователь', 'user5')])
            c.execute("UPDATE users SET name='Secret Owner XYZ',username='secret_owner',deps=?,orgs=? WHERE id=1",
                      (json.dumps(['Фото', 'Видео']), json.dumps(['Media BMSTU', 'Студсовет'])))

    tearDown = test_core.CoreRulesTest.tearDown

    def call(self, handler, body, uid=1):
        return asyncio.run(handler.__wrapped__(None, body, uid))

    def request(self, **kwargs):
        kwargs.setdefault('day', '2030-06-04')
        ref, short = test_workflows.WorkflowTest.request(self, **kwargs)
        with main.db() as c:
            c.execute("UPDATE requests SET event='Съёмка' WHERE id=?", (ref,))
        return ref, short

    def state(self, table, ref):
        with main.db() as c:
            return dict(c.execute(f'SELECT * FROM {table} WHERE id=?', (ref,)).fetchone())

    def appeal(self, anonymous=False):
        response = self.call(main.api_appeal, {'text': 'Где забрать оборудование?', 'anon': anonymous})
        self.assertEqual(response.status, 200, response.text)
        return json.loads(response.text)['appeals'][0]['id']

    def test_approver_survives_curator_changes_and_is_reset_on_kit_edit(self):
        ref, short = self.request()
        self.assertEqual(self.call(main.api_req_action, {'id': ref, 'action': 'approved'}, 2).status, 200)
        self.assertEqual(self.call(main.api_req_action, {'id': ref, 'action': 'curator'}, 4).status, 200)
        row = self.state('requests', ref)
        self.assertEqual((row['approved_by'], row['curator']), (2, 4))
        self.assertEqual(main.boot_payload(1)['requests'][0]['approvedBy'], '@admin2')
        second = next(s for s, m in main.CATALOG_META.items() if not m['level'] and s != short)
        response = self.call(main.api_req_update, {'id': ref, 'items': [[short, 1], [second, 1]]})
        self.assertEqual(response.status, 200, response.text)
        row = self.state('requests', ref)
        self.assertEqual((row['status'], row['curator'], row['approved_by']), ('new', 4, None))
        self.assertIsNone(main.boot_payload(1)['requests'][0]['approvedBy'])
        self.assertEqual(self.call(main.api_req_action, {'id': ref, 'action': 'approved'}, 3).status, 200)
        self.assertEqual(self.state('requests', ref)['approved_by'], 3)
        self.assertIn('@senior3', self.state('requests', ref)['history'])

    def test_senior_must_assign_curator_before_issue(self):
        ref, _ = self.request(status='approved')
        response = self.call(main.api_req_action, {'id': ref, 'action': 'issue'}, 3)
        self.assertNotEqual(response.status, 200)
        self.assertEqual(self.state('requests', ref)['status'], 'approved')
        self.assertEqual(self.call(main.api_req_action, {'id': ref, 'action': 'curator'}, 3).status, 200)
        self.assertEqual(self.call(main.api_req_action, {'id': ref, 'action': 'issue'}, 3).status, 200)

    def test_studio_approver_and_time_reset(self):
        ref = test_workflows.WorkflowTest.studio(self, day='2030-06-04', status='new', curator=None)
        self.assertEqual(self.call(main.api_626_action, {'id': ref, 'action': 'approved'}, 3).status, 200)
        self.assertEqual(main.boot_payload(1)['bookings626'][0]['approvedBy'], '@senior3')
        body = dict(kind='626', id=ref, d1='2030-06-04', t1='12:00', t2='13:00', goal='Интервью')
        self.assertEqual(self.call(main.api_booking_time, body, 3).status, 200)
        self.assertIsNone(self.state('b626', ref)['approved_by'])

    def test_migration_backfills_last_approval_once_without_guessing(self):
        ref, _ = self.request(status='approved')
        main._log_action(2, 'requests', ref, 'approved')
        main._log_action(4, 'requests', ref, 'approved')
        with main.db() as c:
            c.execute('ALTER TABLE requests DROP COLUMN approved_by')
            c.execute('ALTER TABLE requests DROP COLUMN approved_at')
        main.workflow_schema()
        self.assertEqual(self.state('requests', ref)['approved_by'], 4)
        main.reset_booking_review('req', ref)
        main._migrate()
        self.assertIsNone(self.state('requests', ref)['approved_by'])

    def test_admins_can_read_reply_before_approval_and_after_another_curator(self):
        ref, _ = self.request()
        for uid in (1, 2, 4):
            response = self.call(main.api_chat, dict(kind='req', id=ref, text='Сообщение', asRole='admin'), uid)
            self.assertEqual(response.status, 200, response.text)
        self.assertEqual(len(main.boot_payload(4)['requests'][0]['chat']), 3)
        self.assertEqual(main.boot_payload(4)['requests'][0]['unread'], 2)
        self.assertEqual(self.call(main.api_chat, dict(kind='req', id=ref, text='Чужой'), 5).status, 403)
        self.assertEqual(self.call(main.api_read, dict(kind='req', id=ref), 5).status, 403)
        self.call(main.api_req_action, dict(id=ref, action='approved'), 2)
        self.call(main.api_req_action, dict(id=ref, action='curator'), 2)
        self.assertEqual(len(main.boot_payload(4)['requests'][0]['chat']), 3)
        self.assertEqual(self.call(main.api_read, dict(kind='req', id=ref), 4).status, 200)
        self.assertEqual(main.boot_payload(4)['requests'][0]['unread'], 0)

    def test_unassigned_owner_chat_notifies_admin_channel(self):
        ref, _ = self.request()
        with patch.object(main, 'ADMIN_CHAT_ID', -10099):
            self.call(main.api_chat, dict(kind='req', id=ref, text='Можно раньше?'))
        self.assertEqual(main.notify.call_args.args[0], -10099)
        self.assertIn('Можно раньше?', main.notify.call_args.args[1])

    def test_studio_chat_before_approval_visible_to_regular_admin(self):
        ref = test_workflows.WorkflowTest.studio(self, status='new', curator=None)
        self.assertEqual(self.call(main.api_chat, dict(kind='626', id=ref, text='Вопрос')).status, 200)
        self.assertEqual(len(main.boot_payload(2)['bookings626'][0]['chat']), 1)
        self.assertEqual(self.call(main.api_chat, dict(kind='626', id=ref, text='Ответ'), 2).status, 200)

    def test_appeal_reply_read_close_and_reopen(self):
        ref = self.appeal()
        self.assertEqual(self.call(main.api_appeal_action, dict(id=ref, action='reply', text='В рентале'), 2).status, 200)
        a = main.boot_payload(1)['appeals'][0]
        self.assertEqual((a['chat'][0]['text'], a['unread']), ('В рентале', 1))
        self.assertEqual(self.call(main.api_read, dict(kind='appeal', id=ref)).status, 200)
        self.assertEqual(main.boot_payload(1)['appeals'][0]['unread'], 0)
        self.assertEqual(self.call(main.api_appeal_action, dict(id=ref, action='close')).status, 403)
        self.assertEqual(self.call(main.api_appeal_action, dict(id=ref, action='close'), 4).status, 200)
        self.assertEqual(self.state('appeals', ref)['closed_by'], 4)
        self.assertNotEqual(self.call(main.api_appeal_action, dict(id=ref, action='reply', text='Ещё вопрос')).status, 200)
        self.assertEqual(self.call(main.api_appeal_action, dict(id=ref, action='reopen'), 2).status, 200)
        self.assertEqual(self.call(main.api_appeal_action, dict(id=ref, action='reply', text='Спасибо')).status, 200)

    def test_anonymous_appeal_hides_identity_but_accepts_replies(self):
        ref = self.appeal(True)
        self.call(main.api_appeal_action, dict(id=ref, action='reply', text='Уточнение'))
        a = main.boot_payload(2)['appeals'][0]
        encoded = json.dumps(a)
        self.assertEqual(a['author'], 'Аноним')
        for private in ('Secret Owner XYZ', 'secret_owner', 'user_id', 'sender'):
            self.assertNotIn(private, encoded)
        self.call(main.api_appeal_action, dict(id=ref, action='reply', text='Ответ'), 2)
        self.assertEqual(main.notify.call_args.args[0], 1)

    def test_other_user_has_no_appeal_access(self):
        ref = self.appeal()
        self.assertEqual(main.boot_payload(5)['appeals'], [])
        for action in ('reply', 'close', 'reopen'):
            self.assertEqual(self.call(main.api_appeal_action, dict(id=ref, action=action, text='Чужой'), 5).status, 403)
        self.assertEqual(self.call(main.api_read, dict(kind='appeal', id=ref), 5).status, 403)

    def test_start_page_and_history_preferences_are_personal_and_persistent(self):
        self.assertEqual(self.call(main.api_preferences, dict(startPage='adminHub'), 2).status, 200)
        self.assertEqual(self.call(main.api_preferences, dict(showPast=False), 2).status, 200)
        main._migrate()
        self.assertEqual(main.boot_payload(2)['preferences'], dict(startPage='adminHub', showPast=False))
        self.assertEqual(main.boot_payload(1)['preferences'], dict(startPage='home', showPast=True))
        for page, uid in [('adminHub', 1), ('seniorHub', 2), ('bad', 3)]:
            self.assertEqual(self.call(main.api_preferences, dict(startPage=page), uid).status, 403)
        self.assertEqual(self.call(main.api_preferences, dict(startPage='seniorHub'), 3).status, 200)

    def test_revoked_admin_can_still_change_history_preference(self):
        with main.db() as c:
            c.execute("INSERT INTO user_preferences(user_id,start_page) VALUES(1,'seniorHub')")
        self.assertEqual(self.call(main.api_preferences, dict(showPast=False)).status, 200)
        self.assertEqual(main.boot_payload(1)['preferences'], dict(startPage='home', showPast=False))
        self.assertEqual(self.call(main.api_preferences, dict(startPage=[]), 3).status, 403)

    def test_migration_does_not_restore_approval_for_pending_kit(self):
        ref, _ = self.request(status='issued')
        main._log_action(2, 'requests', ref, 'approved')
        with main.db() as c:
            c.execute('UPDATE requests SET review_pending=1 WHERE id=?', (ref,))
            c.execute('ALTER TABLE requests DROP COLUMN approved_by')
            c.execute('ALTER TABLE requests DROP COLUMN approved_at')
        main.workflow_schema()
        self.assertIsNone(self.state('requests', ref)['approved_by'])

    def test_filter_metadata_includes_all_departments_and_organizations(self):
        self.request()
        r = main.boot_payload(2)['requests'][0]
        self.assertEqual(r['deps'], ['Фото', 'Видео'])
        self.assertEqual(r['orgs'], ['Media BMSTU', 'Студсовет'])

    def test_new_cameras_have_one_unit_and_are_available_to_everyone(self):
        for name in ('Nikon D7000', 'Canon 5D Mark III'):
            self.assertEqual(main.CATALOG_META[name]['numbers'], [1])
            self.assertEqual(main.CATALOG_META[name]['level'], '')
            self.assertIsNone(main.validate_items(1, [[name, 1]])[1])

    def test_explicit_senior_grant(self):
        self.assertIn(538610814, main.SENIOR_ADMIN_IDS)


if __name__ == '__main__':
    unittest.main()
