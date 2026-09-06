import asyncio
import base64
import json
import unittest
from unittest.mock import AsyncMock, patch
import main
import test_core


class WorkflowTest(unittest.TestCase):
    setUp = test_core.CoreRulesTest.setUp
    tearDown = test_core.CoreRulesTest.tearDown

    def request(self, status='new', start='10:00', end='11:00', day='2030-06-02', qty=1, curator=None):
        short = next(iter(main.CATALOG_META))
        with main.db() as c:
            ref=c.execute('''INSERT INTO requests(user_id,items,status,dfrom_iso,dto_iso,tfrom,tto,nums,curator,created_ts)
                VALUES(1,?,?,?,?,?,?,?,?,?)''', (json.dumps([[short,qty]]),status,day,day,start,end,json.dumps({short:[1]}),curator,1)).lastrowid
        return ref, short

    def studio(self, day='2000-01-01', status='approved', curator=2):
        with main.db() as c:
            return c.execute("INSERT INTO b626(user_id,day,slot,status,curator) VALUES(1,?,'10:00–11:00',?,?)",(day,status,curator)).lastrowid

    def call(self, handler, body, uid=1):
        with patch.object(main,'boot_payload',return_value={'ok':True}),patch.object(main,'send_or_update_card',new=AsyncMock()),patch.object(main,'notify',new=AsyncMock()):
            return asyncio.run(handler.__wrapped__(None,body,uid))

    def test_peak_does_not_sum_sequential_bookings(self):
        _,short=self.request(start='10:00',end='11:00',qty=2)
        self.request(start='11:00',end='12:00',qty=3)
        self.assertEqual(main.busy_map('2030-06-02','2030-06-02','09:00','13:00')[short],3)
        self.request(start='10:30',end='11:30',qty=1)
        self.assertEqual(main.busy_map('2030-06-02','2030-06-02','09:00','13:00')[short],4)

    def test_unreturned_number_blocks_even_after_due_date(self):
        ref,short=self.request(status='issued',day='2000-01-01')
        self.assertIn(1,main.used_numbers(short,'2030-06-02','2030-06-02','12:00','13:00'))
        self.assertEqual(main.held_units(short)[0]['requestId'],ref)
        with main.db() as c:c.execute("UPDATE requests SET status='ret' WHERE id=?",(ref,))
        self.assertIn(1,main.used_numbers(short,'2030-06-02','2030-06-02'))
        with main.db() as c:c.execute("UPDATE requests SET status='closed' WHERE id=?",(ref,))
        self.assertNotIn(1,main.used_numbers(short,'2030-06-02','2030-06-02'))

    def test_adjacent_number_booking_is_available(self):
        _,short=self.request(status='approved')
        self.assertNotIn(1,main.used_numbers(short,'2030-06-02','2030-06-02','11:00','12:00'))
        self.assertIn(1,main.used_numbers(short,'2030-06-02','2030-06-02','10:59','12:00'))

    def test_photo_failure_keeps_status_and_retry_deduplicates(self):
        class FakeBot:
            def __init__(self):self.sent=[];self.fail=True
            async def send_photo(self,recipient,*args,**kwargs):
                if recipient==3 and self.fail:raise RuntimeError('Telegram delivery unavailable')
                self.sent.append(recipient)
        for studio in (False,True):
            with self.subTest(studio=studio):
                ref=self.studio() if studio else self.request(status='issued',curator=2)[0]
                table='b626' if studio else 'requests'
                handler=main.api_626_action if studio else main.api_req_action
                body={'id':ref,'action':'handover' if studio else 'userret','photos':[base64.b64encode(b'photo').decode()]}
                fake=FakeBot()
                with patch.object(main,'bot',fake),patch.object(main,'ADMIN_CHAT_ID',3):
                    response=self.call(handler,body)
                    self.assertEqual(response.status,502)
                    with main.db() as c:self.assertEqual(c.execute(f'SELECT status FROM {table} WHERE id=?',(ref,)).fetchone()['status'],'approved' if studio else 'issued')
                    fake.fail=False
                    self.assertEqual(self.call(handler,body).status,200)
                    self.assertEqual(fake.sent.count(2),1)
                    self.assertEqual(fake.sent.count(3),1)
                    with main.db() as c:self.assertEqual(c.execute(f'SELECT status FROM {table} WHERE id=?',(ref,)).fetchone()['status'],'ret')

    def test_owner_cannot_cancel_started_studio(self):
        ref=self.studio()
        with patch.object(main,'is_senior',return_value=False):
            self.assertNotEqual(self.call(main.api_626_action,{'id':ref,'action':'cancel'}).status,200)
        future=self.studio(day='2030-06-02')
        with patch.object(main,'is_senior',return_value=False):
            self.assertEqual(self.call(main.api_626_action,{'id':future,'action':'cancel'}).status,200)

    def test_senior_cancels_started_studio_only_with_reason(self):
        ref=self.studio()
        with patch.object(main,'is_senior',return_value=True):
            self.assertNotEqual(self.call(main.api_626_action,{'id':ref,'action':'cancel'},3).status,200)
            self.assertEqual(self.call(main.api_626_action,{'id':ref,'action':'cancel','comment':'Съёмка отменена'},3).status,200)

    def test_studio_curator_can_be_replaced_after_submission(self):
        ref=self.studio(status='ret')
        with patch.object(main,'is_senior',return_value=False),patch.object(main,'is_admin',return_value=True):
            self.assertEqual(self.call(main.api_626_action,{'id':ref,'action':'uncurator'},2).status,200)
            self.assertEqual(self.call(main.api_626_action,{'id':ref,'action':'curator'},3).status,200)
        with main.db() as c:self.assertEqual(c.execute('SELECT curator FROM b626 WHERE id=?',(ref,)).fetchone()['curator'],3)

    def test_senior_rejects_unclaimed_request_with_reason(self):
        ref,_=self.request()
        with patch.object(main,'is_senior',return_value=True),patch.object(main,'is_admin',return_value=True):
            self.assertNotEqual(self.call(main.api_req_action,{'id':ref,'action':'rejected'},3).status,200)
            self.assertEqual(self.call(main.api_req_action,{'id':ref,'action':'rejected','comment':'Некому выдать'},3).status,200)

    def test_offers_are_durable_and_all_declines_escalate_once(self):
        ref,_=self.request()
        fake=type('FakeBot',(),{'send_message':AsyncMock()})()
        with patch.object(main,'bot',fake),patch.object(main,'ADMIN_IDS',{2}),patch.object(main,'EXTRA_ADMIN_IDS',set()),patch.object(main,'SENIOR_ADMIN_IDS',{3}),patch.object(main,'ADMIN_CHAT_ID',99):
            with main.db() as c:r=c.execute('SELECT * FROM requests WHERE id=?',(ref,)).fetchone()
            asyncio.run(main.offer_unclaimed_request(r));asyncio.run(main.offer_unclaimed_request(r))
            self.assertEqual(fake.send_message.await_count,2)
            with main.db() as c:c.execute("UPDATE admin_offers SET answer='no' WHERE ref=? AND admin_id=2",(ref,))
            asyncio.run(main.escalate_offers(ref));self.assertEqual(fake.send_message.await_count,2)
            with main.db() as c:c.execute("UPDATE admin_offers SET answer='no' WHERE ref=? AND admin_id=3",(ref,))
            asyncio.run(main.escalate_offers(ref));asyncio.run(main.escalate_offers(ref))
            self.assertEqual(fake.send_message.await_count,3)
            self.assertIn('tg://user?id=3',fake.send_message.call_args.args[1])

    def test_only_first_accepting_admin_becomes_curator(self):
        from types import SimpleNamespace
        ref,_=self.request()
        with main.db() as c:
            c.executemany("INSERT INTO admin_offers(ref,admin_id,sent) VALUES(?,?,1)",[(ref,2),(ref,3)])
        callbacks=[SimpleNamespace(from_user=SimpleNamespace(id=uid),data=f"offer:yes:{ref}",answer=AsyncMock()) for uid in (2,3)]
        async def run():
            await asyncio.gather(*(main.answer_admin_offer(cb) for cb in callbacks))
        with patch.object(main,'ACTION_LOCK',asyncio.Lock()),patch.object(main,'is_admin',return_value=True),patch.object(main,'notify',new=AsyncMock()),patch.object(main,'send_or_update_card',new=AsyncMock()),patch.object(main,'sse_broadcast',new=AsyncMock()):
            asyncio.run(run())
        with main.db() as c:
            self.assertEqual(c.execute('SELECT curator FROM requests WHERE id=?',(ref,)).fetchone()['curator'],2)
        self.assertIn('уже обработана',callbacks[1].answer.call_args.args[0])

    def test_invitation_threshold_is_36_hours(self):
        import time
        ref,_=self.request()
        with patch.object(main,'offer_unclaimed_request',new=AsyncMock()) as offer,patch.object(main,'notify',new=AsyncMock()),patch.object(main,'weekly_backup'),patch.object(main,'daily_digest',new=AsyncMock()),patch.object(main,'monthly_digest',new=AsyncMock()):
            with main.db() as c:c.execute('UPDATE requests SET created_ts=? WHERE id=?',(time.time()-35*3600,ref))
            asyncio.run(main.run_checks());self.assertEqual(offer.await_count,0)
            with main.db() as c:c.execute('UPDATE requests SET created_ts=? WHERE id=?',(time.time()-36*3600-1,ref))
            asyncio.run(main.run_checks());self.assertEqual(offer.await_count,1)

    def test_issue_endpoint_rejects_a_held_number(self):
        _,short=self.request(status='ret',day='2000-01-01')
        ref,_=self.request(status='approved',curator=2)
        with patch.object(main,'is_admin',return_value=True),patch.object(main,'is_senior',return_value=True):
            response=self.call(main.api_req_action,{'id':ref,'action':'issue','nums':{short:[1]}},2)
        self.assertNotEqual(response.status,200)
        with main.db() as c:self.assertEqual(c.execute('SELECT status FROM requests WHERE id=?',(ref,)).fetchone()['status'],'approved')

    def test_exact_names_survive_favorites_and_hide_restore(self):
        names=[s for s in main.CATALOG_META if any(ch in s for ch in '\"<>')]
        self.assertEqual(len(names),4)
        for short in names:
            with self.subTest(short=short),patch.object(main,'is_senior',return_value=True):
                self.assertEqual(self.call(main.api_favset_add,{'name':'Набор','items':[[short,1]]}).status,200)
                self.assertEqual(self.call(main.api_equip_remove,{'short':short}).status,200)
                with main.db() as c:self.assertIsNotNone(c.execute('SELECT short FROM removed_items WHERE short=?',(short,)).fetchone())
                self.assertEqual(self.call(main.api_equip_restore,{'short':short}).status,200)
                with main.db() as c:self.assertEqual(json.loads(c.execute('SELECT items FROM fav_sets ORDER BY id DESC LIMIT 1').fetchone()['items'])[0][0],short)

if __name__=='__main__':unittest.main()
