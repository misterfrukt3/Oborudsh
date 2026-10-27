"""Правила расписания и сводок: только временная БД, без Telegram/Google."""
import asyncio
import base64
import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import main
import test_core
import test_workflows


class Clock(datetime):
    current = datetime(2030, 6, 1, 8, 0, tzinfo=main.MSK)

    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)


class BookingPolicyTest(unittest.TestCase):
    def setUp(self):
        test_core.CoreRulesTest.setUp(self)
        Clock.current = datetime(2030, 6, 1, 8, tzinfo=main.MSK)  # суббота
        for ctx in (patch.object(main, 'datetime', Clock),
                    patch.object(main, 'is_admin', side_effect=lambda uid: uid in (2,3,4)),
                    patch.object(main, 'is_senior', side_effect=lambda uid: uid == 3),
                    patch.object(main.time, 'time', side_effect=lambda: Clock.current.timestamp())):
            ctx.start()
            self.addCleanup(ctx.stop)
        with main.db() as c:
            c.executemany("INSERT INTO users(id,name,agreed,verified) VALUES(?,?,1,'ok')", [(2,'Куратор Два'),(3,'Старший Три'),(4,'Другой Админ')])
        self.short = next(s for s,m in main.CATALOG_META.items() if not m['level'] and m['total'] >= 3)

    tearDown = test_core.CoreRulesTest.tearDown
    call = test_workflows.WorkflowTest.call
    studio = test_workflows.WorkflowTest.studio

    def request(self, status='new', curator=None, day='2030-06-04', qty=1, start='10:00', end='11:00'):
        ref,_ = test_workflows.WorkflowTest.request(self,status=status,curator=curator,day=day,start=start,end=end)
        with main.db() as c:
            c.execute("UPDATE requests SET items=?,nums=?,event='Съёмка',comment='',created_ts=? WHERE id=?",
                      (json.dumps([[self.short,qty]]),json.dumps({self.short:list(range(1,qty+1))}),Clock.current.timestamp(),ref))
        return ref

    def state(self, ref):
        with main.db() as c: return dict(c.execute('SELECT * FROM requests WHERE id=?',(ref,)).fetchone())

    def body(self, day='2030-06-04', end_day=None, start='10:00', end='11:00'):
        return dict(d1=day,d2=end_day or day,t1=start,t2=end,items=[[self.short,1]],event='Съёмка')

    def test_equipment_advance_is_exactly_seven_days_and_admins_are_exempt(self):
        self.assertEqual(self.call(main.api_req_create,self.body(day='2030-06-08',start='08:00',end='09:00')).status,200)
        self.assertEqual(self.call(main.api_req_create,self.body(day='2030-06-08',start='08:01',end='09:01')).status,400)
        self.assertEqual(self.call(main.api_req_create,self.body(day='2030-06-18'),2).status,200)
        self.assertEqual(self.call(main.api_req_create,self.body(day='2030-06-19'),3).status,200)

    def test_equipment_sunday_endpoints_only_seniors_and_rental_can_span_sunday(self):
        for uid in (1,2,4):
            self.assertEqual(self.call(main.api_req_create,self.body(day='2030-06-02'),uid).status,400)
            self.assertEqual(self.call(main.api_req_create,self.body(day='2030-06-01',end_day='2030-06-02'),uid).status,400)
        self.assertEqual(self.call(main.api_req_create,self.body(day='2030-06-02'),3).status,200)
        self.assertEqual(self.call(main.api_req_create,self.body(day='2030-06-01',end_day='2030-06-03')).status,200)

    def test_studio_sunday_and_monday_14_boundary_for_all_admin_kinds(self):
        for day,slot,uid,expected in [('2030-06-02','10:00–11:00',1,400),
                                      ('2030-06-03','13:59–14:30',1,400),
                                      ('2030-06-03','14:00–15:00',1,200),
                                      ('2030-06-02','10:00–11:00',2,200),
                                      ('2030-06-03','10:00–11:00',3,200)]:
            with self.subTest(day=day,slot=slot,uid=uid):
                response=self.call(main.api_626_create,dict(day=day,slot=slot,goal='Интервью'),uid)
                self.assertEqual(response.status,expected,response.text)
                if expected==400: self.assertNotIn('кроме',response.text.lower())

    def test_time_edit_cannot_bypass_calendar_policy(self):
        ref=self.request()
        for body in (self.body(day='2030-06-02'), self.body(day='2030-06-11')):
            body['id']=ref
            self.assertEqual(self.call(main.api_req_update,body).status,400)
            self.assertEqual(self.state(ref)['dfrom_iso'],'2030-06-04')
            body.update(kind='req')
            self.assertEqual(self.call(main.api_booking_time,body).status,400)
        bid=self.studio(day='2030-06-04',status='new')
        with main.db() as c:
            c.execute("UPDATE b626 SET goal='Интервью' WHERE id=?",(bid,))
            c.execute("INSERT INTO time_changes VALUES('626',?,'Позже',3,'now')",(bid,))
        for day,start in [('2030-06-02','14:00'),('2030-06-03','13:59')]:
            response=self.call(main.api_booking_time,dict(kind='626',id=bid,d1=day,t1=start,t2='15:00'))
            self.assertEqual(response.status,400)
        self.assertEqual(self.call(main.api_booking_time,dict(kind='626',id=bid,d1='2030-06-02',t1='12:00',t2='13:00'),3).status,200)

    def test_actual_sunday_issue_submission_and_acceptance_only_seniors(self):
        Clock.current=datetime(2030,6,2,12,tzinfo=main.MSK)
        ref=self.request(status='approved',curator=2)
        self.assertEqual(self.call(main.api_req_action,dict(id=ref,action='issue'),2).status,403)
        self.assertEqual(self.call(main.api_req_action,dict(id=ref,action='issue'),3).status,200)
        self.assertEqual(self.call(main.api_req_action,dict(id=ref,action='userret',photos=[base64.b64encode(b'photo').decode()])).status,403)
        with main.db() as c:c.execute("UPDATE requests SET status='ret' WHERE id=?",(ref,))
        self.assertEqual(self.call(main.api_req_action,dict(id=ref,action='return'),2).status,403)
        self.assertEqual(self.call(main.api_req_action,dict(id=ref,action='return'),3).status,200)
        # Старший может сдать собственную заявку в воскресенье.
        second=self.request(status='issued',curator=2)
        with main.db() as c:c.execute('UPDATE requests SET user_id=3 WHERE id=?',(second,))
        with patch.object(main,'bot',SimpleNamespace(send_photo=AsyncMock())),patch.object(main,'ADMIN_CHAT_ID',0):
            self.assertEqual(self.call(main.api_req_action,dict(id=second,action='userret',photos=[base64.b64encode(b'photo').decode()]),3).status,200)

    def test_owner_edits_all_preissue_stages_and_keeps_curator(self):
        for status in ('new','curator','approved'):
            with self.subTest(status=status):
                ref=self.request(status=status,curator=2)
                response=self.call(main.api_req_update,dict(id=ref,items=[[self.short,2]]))
                self.assertEqual(response.status,200,response.text)
                row=self.state(ref)
                self.assertEqual((row['status'],row['curator']),('new',2))
                self.assertEqual(self.call(main.api_req_action,dict(id=ref,action='issue'),2).status,403)
                self.assertEqual(self.call(main.api_req_action,dict(id=ref,action='approved'),4).status,200)
                with main.db() as c:c.execute("UPDATE requests SET status='canceled' WHERE id=?",(ref,))

    def test_composition_edit_does_not_satisfy_pending_time_request(self):
        ref=self.request(status='approved',curator=2)
        with main.db() as c:c.execute("INSERT INTO time_changes VALUES('req',?,'Позже',2,'now')",(ref,))
        self.assertEqual(self.call(main.api_req_update,dict(id=ref,items=[[self.short,2]])).status,200)
        self.assertIsNotNone(main.time_change('req',ref))
        self.assertEqual(self.call(main.api_req_action,dict(id=ref,action='approved'),2).status,400)

    def test_curator_is_notified_even_when_another_admin_edits(self):
        ref=self.request(status='approved',curator=2)
        with patch.object(main,'notify',new=AsyncMock()) as notify,patch.object(main,'boot_payload',return_value={'ok':True}),patch.object(main,'send_or_update_card',new=AsyncMock()):
            response=asyncio.run(main.api_req_update.__wrapped__(None,dict(id=ref,items=[[self.short,2]]),4))
        self.assertEqual(response.status,200)
        self.assertTrue(any(c.args[0]==2 and 'изменилась' in c.args[1] for c in notify.await_args_list))
        self.assertEqual(self.state(ref)['curator'],2)

    def test_regular_admin_can_cancel_risky_requests_with_another_curator(self):
        for studio in (False,True):
            ref=self.studio(day='2030-06-01') if studio else self.request(day='2030-06-01',status='approved',curator=2)
            handler=main.api_626_action if studio else main.api_req_action
            action='cancel' if studio else 'rejected'
            self.assertEqual(self.call(handler,dict(id=ref,action=action,comment='В субботу команда не работает'),4).status,200)

    def test_admin_edits_issued_and_submitted_kits_without_releasing_units(self):
        for status in ('issued','ret'):
            with self.subTest(status=status):
                ref=self.request(status=status,curator=2)
                body=dict(id=ref,items=[[self.short,2]])
                self.assertEqual(self.call(main.api_req_update,body).status,403)
                self.assertEqual(self.call(main.api_req_update,body,4).status,200)
                row=self.state(ref)
                self.assertEqual((row['status'],row['curator'],row['review_pending']),(status,2,1))
                self.assertEqual(json.loads(row['nums'])[self.short],[1,2])
                self.assertEqual({h['num'] for h in main.held_units(self.short)},{1,2})
                if status=='ret':self.assertEqual(self.call(main.api_req_action,dict(id=ref,action='return'),2).status,400)
                self.assertEqual(self.call(main.api_req_action,dict(id=ref,action='approved'),4).status,200)
                self.assertEqual((self.state(ref)['status'],self.state(ref)['review_pending']),(status,0))
                with main.db() as c:c.execute("UPDATE requests SET status='ret' WHERE id=?",(ref,))
                self.assertEqual(self.call(main.api_req_action,dict(id=ref,action='return'),2).status,200)
                self.assertEqual(self.call(main.api_req_update,body,3).status,403)

    def test_issued_edit_rejects_date_changes_and_conflicts_atomically(self):
        ref=self.request(status='issued',curator=2)
        before=self.state(ref)
        self.assertEqual(self.call(main.api_req_update,dict(id=ref,items=[[self.short,2]],t1='12:00'),4).status,400)
        other=self.request(status='issued',qty=main.CATALOG_META[self.short]['total']-1)
        with main.db() as c:c.execute('UPDATE requests SET nums=? WHERE id=?',(json.dumps({self.short:list(range(2,main.CATALOG_META[self.short]['total']+1))}),other))
        self.assertEqual(self.call(main.api_req_update,dict(id=ref,items=[[self.short,2]]),4).status,400)
        self.assertEqual(self.state(ref),before)

    def test_issue_cannot_silently_change_previously_approved_kit(self):
        ref=self.request(status='approved',curator=2)
        self.assertEqual(self.call(main.api_req_action,dict(id=ref,action='issue',items=[[self.short,2]]),2).status,400)
        self.assertEqual(self.state(ref)['status'],'approved')

    def test_saturday_and_short_notice_warnings_are_admin_only_and_use_creation_time(self):
        ref=self.request(day='2030-06-01')
        row=self.state(ref)
        self.assertEqual(len(main.shape_req(row,2)['adminWarnings']),2)
        self.assertEqual(main.shape_req(row,1)['adminWarnings'],[])
        self.assertIn('суббот',main.late_note(row))
        ref=self.request(day='2030-06-03',start='08:00',end='09:00')
        self.assertEqual(main.shape_req(self.state(ref),2)['adminWarnings'],[])
        with main.db() as c:c.execute('UPDATE requests SET created_ts=created_ts+1 WHERE id=?',(ref,))
        self.assertEqual(len(main.shape_req(self.state(ref),2)['adminWarnings']),1)
        bid=self.studio(day='2030-06-01',status='new')
        with main.db() as c:
            c.execute('UPDATE b626 SET created_ts=? WHERE id=?',(Clock.current.timestamp(),bid))
            room=c.execute('SELECT * FROM b626 WHERE id=?',(bid,)).fetchone()
        self.assertEqual(len(main.shape_626(room,2)['adminWarnings']),2)
        self.assertEqual(main.shape_626(room,1)['adminWarnings'],[])

    def test_scheduler_never_auto_cancels_or_sends_unclaimed_messages(self):
        Clock.current=datetime(2030,6,4,6,tzinfo=main.MSK)
        refs=[self.request(status=status,day='2030-05-01') for status in ('new','curator','approved')]
        self.studio(day='2030-05-01',status='new')
        with main.db() as c:
            c.executemany('UPDATE requests SET created_ts=1 WHERE id=?',[(r,) for r in refs])
            c.execute("INSERT INTO admin_offers(ref,admin_id,sent,sent_at,answer) VALUES(?,2,1,1,'')",(refs[-1],))
        fake=SimpleNamespace(send_message=AsyncMock())
        with patch.object(main,'bot',fake),patch.object(main,'ADMIN_CHAT_ID',99),patch.object(main,'notify',new=AsyncMock()) as notify,patch.object(main,'weekly_backup'):
            asyncio.run(main.run_checks());asyncio.run(main.run_checks())
        notify.assert_not_awaited();fake.send_message.assert_not_awaited()
        self.assertEqual([self.state(r)['status'] for r in refs],['new','curator','approved'])

    def test_legacy_offer_buttons_cannot_assign_or_send_messages(self):
        ref=self.request(status='approved')
        fake=SimpleNamespace(send_message=AsyncMock())
        with patch.object(main,'bot',fake):
            for choice in ('yes','no'):
                cb=SimpleNamespace(from_user=SimpleNamespace(id=2),data=f'offer:{choice}:{ref}',answer=AsyncMock())
                asyncio.run(main.answer_admin_offer(cb))
                self.assertIn('отключены',cb.answer.call_args.args[0])
        fake.send_message.assert_not_awaited()
        self.assertIsNone(self.state(ref)['curator'])

    def test_two_moscow_digest_slots_are_once_daily_and_retry_delivery_errors(self):
        fake=SimpleNamespace()
        with patch.object(main,'bot',fake),patch.object(main,'ADMIN_CHAT_ID',99),patch.object(main,'daily_digest',new=AsyncMock()) as digest,patch.object(main,'weekly_backup'):
            for h,m in [(7,59),(8,0),(8,5),(21,59),(22,0),(22,5)]:
                Clock.current=datetime(2030,6,4,h,m,tzinfo=main.MSK)
                asyncio.run(main.run_checks())
            self.assertEqual([c.kwargs['period'] for c in digest.await_args_list],['morning','evening'])
            Clock.current=datetime(2030,6,5,8,tzinfo=main.MSK)
            digest.side_effect=RuntimeError('offline')
            with self.assertRaises(RuntimeError):asyncio.run(main.run_checks())
            self.assertEqual(main._meta_get('digest_morning_date'),'2030-06-04')
            digest.side_effect=None
            asyncio.run(main.run_checks())
            self.assertEqual(main._meta_get('digest_morning_date'),'2030-06-05')

    def test_digest_lists_times_both_directions_curator_and_missed_issuance(self):
        Clock.current=datetime(2030,6,4,8,tzinfo=main.MSK)
        ref=self.request(status='new',day='2030-06-04',start='10:17',end='11:43')
        missed=self.request(status='approved',curator=2,day='2030-06-03')
        tomorrow=self.request(status='approved',curator=4,day='2030-06-05')
        fake=SimpleNamespace()
        with patch.object(main,'bot',fake),patch.object(main,'ADMIN_CHAT_ID',99),patch.object(main,'send_rich_markdown',new=AsyncMock()) as send:
            asyncio.run(main.daily_digest(period='morning'))
            morning='\n'.join(send.call_args.args[1])
            self.assertIn(f'Выдача · 2030-06-04 10:17 · ID {ref}',morning)
            self.assertIn(f'Возврат · 2030-06-04 11:43 · ID {ref}',morning)
            self.assertIn('БЕЗ КУРАТОРА',morning)
            self.assertNotIn('Не выдано',morning)
            Clock.current=datetime(2030,6,4,22,tzinfo=main.MSK)
            asyncio.run(main.daily_digest())
            evening='\n'.join(send.call_args.args[1])
            self.assertIn(f'Не выдано · 2030-06-03 10:00 · ID {missed}',evening)
            self.assertIn('Куратор Два',evening)
            self.assertIn(f'Выдача · 2030-06-05 10:00 · ID {tomorrow}',evening)
            self.assertIn('Другой Админ',evening)
            self.assertNotIn('без куратора уже',evening)

    def test_migration_preserves_existing_issued_requests_and_is_repeatable(self):
        ref=self.request(status='issued',curator=2)
        with main.db() as c:c.execute('ALTER TABLE requests DROP COLUMN review_pending')
        main.init_db();main._migrate();main._migrate()
        row=self.state(ref)
        self.assertEqual((row['status'],row['curator'],row['review_pending']),('issued',2,0))


if __name__=='__main__':unittest.main()
