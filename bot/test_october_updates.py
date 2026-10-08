import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import main
import test_core
import test_workflows
import test_media_trip


class OctoberUpdatesTest(unittest.TestCase):
    setUp = test_core.CoreRulesTest.setUp
    tearDown = test_core.CoreRulesTest.tearDown
    request = test_workflows.WorkflowTest.request
    studio = test_workflows.WorkflowTest.studio
    call = test_workflows.WorkflowTest.call

    def test_owner_cancels_before_issue_with_reason_saved_and_curator_notified(self):
        with patch.object(main, 'is_senior', return_value=False):
            for status in ('new', 'curator', 'approved'):
                ref, _ = self.request(status=status, curator=2)
                self.assertEqual(self.call(main.api_req_action, dict(id=ref, action='cancel')).status, 400)
                with patch.object(main, 'boot_payload', return_value={}), patch.object(main, 'send_or_update_card', new=AsyncMock()), patch.object(main, 'notify', new=AsyncMock()) as notify:
                    self.assertEqual(asyncio.run(main.api_req_action.__wrapped__(None, dict(id=ref, action='cancel', comment='Съёмка отменена'), 1)).status, 200)
                notify.assert_awaited_with(2, f'Заявка ID {ref} отменена пользователем. Причина: Съёмка отменена')
                with main.db() as c:
                    row = c.execute('SELECT status,history FROM requests WHERE id=?', (ref,)).fetchone()
                self.assertEqual(row['status'], 'canceled')
                self.assertIn('Съёмка отменена', json.loads(row['history'])[-1][1])
            for status in ('issued', 'ret', 'closed'):
                ref, _ = self.request(status=status)
                self.assertEqual(self.call(main.api_req_action, dict(id=ref, action='cancel', comment='Причина')).status, 403)
            ref, _ = self.request(status='approved')
            self.assertEqual(self.call(main.api_req_action, dict(id=ref, action='cancel', comment='Причина'), 9).status, 403)

    def test_regular_admin_rejects_free_or_own_request_only_with_reason(self):
        with patch.object(main, 'is_senior', return_value=False), patch.object(main, 'is_admin', return_value=True):
            for status, curator in [('new', None), ('approved', None), ('approved', 2), ('curator', 2)]:
                ref, _ = self.request(status=status, curator=curator)
                self.assertEqual(self.call(main.api_req_action, dict(id=ref, action='rejected'), 2).status, 400)
                self.assertEqual(self.call(main.api_req_action, dict(id=ref, action='rejected', comment='Нет возможности выдать'), 2).status, 200)
            ref, _ = self.request(status='approved', curator=3)
            self.assertEqual(self.call(main.api_req_action, dict(id=ref, action='rejected', comment='Причина'), 2).status, 403)

    def test_regular_studio_curator_can_cancel_before_start_only(self):
        with patch.object(main, 'is_senior', return_value=False), patch.object(main, 'is_admin', return_value=True):
            ref = self.studio(day='2030-06-02', curator=2)
            self.assertEqual(self.call(main.api_626_action, dict(id=ref, action='cancel', comment='Причина'), 3).status, 403)
            self.assertEqual(self.call(main.api_626_action, dict(id=ref, action='cancel'), 2).status, 400)
            self.assertEqual(self.call(main.api_626_action, dict(id=ref, action='cancel', comment='Причина'), 2).status, 200)
            ref = self.studio(curator=2)
            self.assertEqual(self.call(main.api_626_action, dict(id=ref, action='cancel', comment='Причина'), 2).status, 403)

    def test_escalation_retries_only_failed_recipient_and_ignores_old_channel_receipt(self):
        ref, _ = self.request(status='approved')
        with main.db() as c:
            c.execute("INSERT INTO admin_offers(ref,admin_id,answer) VALUES(?,2,'no')", (ref,))
            c.execute('INSERT INTO offer_escalations VALUES(?)', (ref,))
        failed = 5027289530
        async def send(uid, *args, **kwargs):
            if uid == failed:
                raise RuntimeError('Recipient unavailable')
        fake = SimpleNamespace(send_message=AsyncMock(side_effect=send))
        with patch.object(main, 'bot', fake), patch.object(main, 'ADMIN_CHAT_ID', 0):
            asyncio.run(main.escalate_offers(ref))
            self.assertEqual([c.args[0] for c in fake.send_message.await_args_list], [1896340090, failed, failed])
            self.assertFalse(main.offer_status_summary()[0]['escalated'])
            fake.send_message.side_effect = None
            fake.send_message.reset_mock()
            asyncio.run(main.escalate_offers(ref))
            asyncio.run(main.escalate_offers(ref))
            self.assertEqual([c.args[0] for c in fake.send_message.await_args_list], [failed])
            self.assertTrue(main.offer_status_summary()[0]['escalated'])
        main.reset_booking_review('req', ref)
        with main.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM offer_escalation_receipts WHERE ref=?', (ref,)).fetchone()[0], 0)

    def member(self, name='Test User Name', username='tester', role='активист'):
        return dict(name=name, telegram=username, role=role, deps=['Видео'], orgs=['Media BMSTU'])

    def test_member_sync_preview_apply_preserves_history_verification_and_admins(self):
        ref, _ = self.request(status='approved')
        with main.db() as c:
            c.execute("UPDATE users SET username='tester',verified='pending' WHERE id=1")
            c.execute("INSERT INTO users(id,name,username,agreed,verified) VALUES(2,'Blocked User Name','blocked',1,'blocked')")
        directory = {main._norm_name('Test User Name'): [self.member()], main._norm_name('Blocked User Name'): [self.member('Blocked User Name', 'blocked')]}
        with patch.object(main, 'MEMBERS_SHEET_ID', 'test'), patch.object(main, '_members_snapshot', return_value=directory), patch.dict(main._MEMBERS_CACHE, error=''):
            preview = main.sync_registered_members()
            self.assertEqual(len(preview['changed']), 1)
            self.assertEqual(main.get_user(1)['role'], 'стажёр')
            main.sync_registered_members(apply=True)
            self.assertEqual(main.get_user(1)['role'], 'активист')
            self.assertEqual(main.get_user(1)['verified'], 'pending')
            self.assertEqual(main.get_user(2)['verified'], 'blocked')
            self.assertEqual(main.sync_registered_members()['changed'], [])
        with main.db() as c:
            self.assertEqual(c.execute('SELECT status FROM requests WHERE id=?', (ref,)).fetchone()[0], 'approved')

    def test_member_sync_downgrade_missing_ambiguous_and_stale(self):
        with main.db() as c:
            c.execute("UPDATE users SET username='tester',role='активист' WHERE id=1")
        member = self.member(role='стажёр')
        with patch.object(main, 'MEMBERS_SHEET_ID', 'test'), patch.dict(main._MEMBERS_CACHE, error=''):
            with patch.object(main, '_members_snapshot', return_value={'x': [member]}):
                main.sync_registered_members(True)
                self.assertEqual(main.get_user(1)['role'], 'стажёр')
            with patch.object(main, '_members_snapshot', return_value={}):
                self.assertEqual(main.sync_registered_members(True)['missing'], [1])
            with patch.object(main, '_members_snapshot', return_value={'x': [member, self.member('Another User Name')]}):
                self.assertEqual(main.sync_registered_members(True)['ambiguous'], [1])
            with patch.object(main, '_members_snapshot', return_value={'x': [self.member()]}), patch.dict(main._MEMBERS_CACHE, error='network unavailable'):
                with self.assertRaises(ValueError):
                    main.sync_registered_members(True)
                self.assertEqual(main.get_user(1)['role'], 'стажёр')

    def test_membersync_is_private_and_senior_only(self):
        for senior, chat in [(False, 'private'), (True, 'group')]:
            message = SimpleNamespace(from_user=SimpleNamespace(id=1), chat=SimpleNamespace(type=chat), answer=AsyncMock(), text='/membersync apply')
            with patch.object(main, 'is_senior', return_value=senior), patch.object(main, 'sync_registered_members') as sync:
                asyncio.run(main.cmd_membersync(message))
                sync.assert_not_called()
                message.answer.assert_not_awaited()


class TripUpdatesTest(unittest.TestCase):
    setUp = test_core.CoreRulesTest.setUp
    tearDown = test_core.CoreRulesTest.tearDown
    admin = test_media_trip.MediaTripTest.admin
    call = test_media_trip.MediaTripTest.call
    setup_trip = test_media_trip.MediaTripTest.setup_trip
    create = test_media_trip.MediaTripTest.create

    def test_access_added_removed_and_blocked_members(self):
        self.setup_trip()
        self.assertFalse(main.MEDIA_TRIP.payload(2)['allowed'])
        self.assertEqual(self.call(dict(action='members', number=1, members=[2]), 1).status, 200)
        self.assertTrue(main.MEDIA_TRIP.payload(2)['allowed'])
        self.assertFalse(main.MEDIA_TRIP.payload(2)['canManage'])
        self.assertEqual(self.call(dict(action='join', code='anything'), 2).status, 403)
        self.call(dict(action='members', number=1, remove=2), 1)
        self.assertFalse(main.MEDIA_TRIP.payload(2)['allowed'])
        with main.db() as c:
            c.execute("UPDATE users SET verified='blocked' WHERE id=1")
        self.assertFalse(main.MEDIA_TRIP.payload(1)['allowed'])

    def test_legacy_settings_migrate_once_preserving_teams_channel_and_staff(self):
        self.setup_trip()
        legacy = dict(testing=True, staff=[self.admin, 42], channel=-10099, place='Рентал')
        with main.db() as c:
            c.execute('UPDATE trip_settings SET data=?', (json.dumps(legacy),))
        main.MEDIA_TRIP.schema()
        main.MEDIA_TRIP.schema()
        settings = main.MEDIA_TRIP.settings()
        self.assertFalse(settings['testing'])
        self.assertEqual(settings['staff'], [self.admin, 42])
        self.assertEqual(settings['channel'], -10099)
        self.assertTrue(main.MEDIA_TRIP.payload(1)['allowed'])
        self.assertFalse(main.MEDIA_TRIP.payload(1122855409)['allowed'])

    def test_channel_fallback_retry_recovery_and_valid_url_button(self):
        block, _ = self.setup_trip()
        self.call(dict(action='settings', staff=[self.admin], channel=0, place='Рентал'))
        with patch.object(main, 'ADMIN_CHAT_ID', -100555):
            self.assertEqual(self.create(block).status, 200)
        with main.db() as c:
            # Reproduce a request submitted before a destination channel was configured.
            c.execute("DELETE FROM trip_outbox WHERE key LIKE 'new:%'")
        fake = SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError('temporary offline')))
        with patch.object(main, 'ADMIN_CHAT_ID', -100555), patch.object(main, 'bot', fake):
            asyncio.run(main.MEDIA_TRIP.tick())
            with main.db() as c:
                row = c.execute("SELECT * FROM trip_outbox WHERE key LIKE 'new:%'").fetchone()
            self.assertEqual(row['recipient'], -100555)
            self.assertEqual(row['attempts'], 1)
            fake.send_message.side_effect = None
            fake.send_message.reset_mock()
            asyncio.run(main.MEDIA_TRIP.tick(row['retry'] + 1))
            asyncio.run(main.MEDIA_TRIP.tick(row['retry'] + 1))
            messages = [a for a in fake.send_message.await_args_list if 'заявка №' in a.args[1]]
            self.assertEqual(len(messages), 1)
            button = messages[0].kwargs['reply_markup'].inline_keyboard[0][0]
            self.assertIsNone(button.web_app)
            self.assertTrue(button.url.startswith('https://t.me/'))

    def test_no_silent_request_when_neither_channel_is_configured(self):
        block, _ = self.setup_trip()
        self.call(dict(action='settings', staff=[self.admin], channel=0))
        with patch.object(main, 'ADMIN_CHAT_ID', 0):
            self.assertEqual(self.create(block).status, 400)


if __name__ == '__main__':
    unittest.main()
