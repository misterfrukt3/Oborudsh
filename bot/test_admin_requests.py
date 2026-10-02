import asyncio
import json
import unittest
from unittest.mock import AsyncMock,patch
from urllib.parse import parse_qs,urlsplit

import main
import test_core
import test_workflows


class AdminRequestsTest(unittest.TestCase):
    setUp=test_core.CoreRulesTest.setUp
    tearDown=test_core.CoreRulesTest.tearDown
    request=test_workflows.WorkflowTest.request
    studio=test_workflows.WorkflowTest.studio

    def call(self,handler,body,uid=2):
        with patch.object(main,'is_admin',side_effect=lambda i:i in (2,3)),patch.object(main,'is_senior',side_effect=lambda i:i==3),patch.object(main,'boot_payload',return_value={'ok':True}),patch.object(main,'notify',new=AsyncMock()),patch.object(main,'send_or_update_card',new=AsyncMock()):
            return asyncio.run(handler.__wrapped__(None,body,uid))

    def state(self,table,ref):
        with main.db() as c:return dict(c.execute(f'SELECT * FROM {table} WHERE id=?',(ref,)).fetchone())

    def test_approve_before_curator_and_keep_approval_on_release(self):
        ref,_=self.request()
        self.assertNotEqual(self.call(main.api_req_action,{'id':ref,'action':'curator'}).status,200)
        self.assertEqual(self.call(main.api_req_action,{'id':ref,'action':'approved'}).status,200)
        self.assertEqual((self.state('requests',ref)['status'],self.state('requests',ref)['curator']),('approved',None))
        self.assertNotEqual(self.call(main.api_req_action,{'id':ref,'action':'approved'}).status,200)
        self.assertEqual(self.call(main.api_req_action,{'id':ref,'action':'curator'}).status,200)
        self.assertEqual(self.state('requests',ref)['status'],'approved')
        self.assertEqual(self.call(main.api_req_action,{'id':ref,'action':'uncurator'},3).status,200)
        self.assertEqual((self.state('requests',ref)['status'],self.state('requests',ref)['curator']),('approved',None))

    def test_senior_issues_another_curators_request_and_accepts_return(self):
        ref,short=self.request(status='approved',curator=2)
        self.assertNotEqual(self.call(main.api_req_action,{'id':ref,'action':'issue'},1).status,200)
        self.assertEqual(self.call(main.api_req_action,{'id':ref,'action':'issue'},3).status,200)
        self.assertEqual(self.state('requests',ref)['issued_by'],3)
        with main.db() as c:c.execute("UPDATE requests SET status='ret' WHERE id=?",(ref,))
        self.assertEqual(self.call(main.api_req_action,{'id':ref,'action':'return'},3).status,200)
        self.assertEqual(self.state('requests',ref)['returned_by'],3)

    def test_request_time_is_delivered_and_blocks_approval_until_owner_changes(self):
        ref,_=self.request()
        body={'kind':'req','id':ref,'reason':'Получение нужно перенести на 12:00'}
        self.assertEqual(self.call(main.api_time_change,body,1).status,403)
        self.assertEqual(self.call(main.api_time_change,body).status,200)
        self.assertEqual(main.time_change('req',ref)['reason'],body['reason'])
        self.assertNotEqual(self.call(main.api_req_action,{'id':ref,'action':'approved'}).status,200)
        changed={'kind':'req','id':ref,'d1':'2030-06-02','d2':'2030-06-02','t1':'12:00','t2':'13:00'}
        self.assertEqual(self.call(main.api_booking_time,changed,1).status,200)
        self.assertIsNone(main.time_change('req',ref))
        self.assertEqual(self.state('requests',ref)['status'],'new')
        self.assertEqual(self.call(main.api_req_action,{'id':ref,'action':'approved'}).status,200)

    def test_notification_failure_leaves_no_pending_request(self):
        ref,_=self.request()
        with patch.object(main,'is_admin',return_value=True),patch.object(main,'notify',new=AsyncMock(side_effect=RuntimeError('offline'))):
            response=asyncio.run(main.api_time_change.__wrapped__(None,{'kind':'req','id':ref,'reason':'Перенесите время'},2))
        self.assertEqual(response.status,502)
        self.assertIsNone(main.time_change('req',ref))

    def test_pending_approved_request_cannot_be_issued_and_new_time_resets_curator(self):
        ref,_=self.request(status='approved',curator=2)
        self.assertEqual(self.call(main.api_time_change,{'kind':'req','id':ref,'reason':'Позже'}).status,200)
        self.assertNotEqual(self.call(main.api_req_action,{'id':ref,'action':'issue'},3).status,200)
        body={'kind':'req','id':ref,'d1':'2030-06-02','d2':'2030-06-02','t1':'12:00','t2':'13:00'}
        self.assertEqual(self.call(main.api_booking_time,body,1).status,200)
        row=self.state('requests',ref)
        self.assertEqual((row['status'],row['curator'],row['tfrom']),('new',None,'12:00'))

    def test_senior_edit_conflicts_terminal_and_member_permissions(self):
        ref,_=self.request(status='approved',curator=2)
        other,_=self.request(start='12:00',end='13:00')
        body={'kind':'req','id':ref,'d1':'2030-06-02','d2':'2030-06-02','t1':'12:00','t2':'13:00'}
        self.assertNotEqual(self.call(main.api_booking_time,body,3).status,200)
        self.assertEqual(self.state('requests',ref)['tfrom'],'10:00')
        body.update(t1='13:00',t2='14:00')
        self.assertEqual(self.call(main.api_booking_time,body,1).status,403)
        self.assertEqual(self.call(main.api_booking_time,body,3).status,200)
        with main.db() as c:c.execute("UPDATE requests SET status='closed' WHERE id=?",(ref,))
        body.update(t1='14:00',t2='15:00')
        self.assertNotEqual(self.call(main.api_booking_time,body,3).status,200)

    def test_626_time_request_and_conflict_then_reapproval(self):
        ref=self.studio(day='2030-06-02')
        with main.db() as c:c.execute("UPDATE b626 SET goal='Интервью' WHERE id=?",(ref,))
        self.assertEqual(self.call(main.api_time_change,{'kind':'626','id':ref,'reason':'Нужно позже'},3).status,200)
        body={'kind':'626','id':ref,'d1':'2030-06-02','d2':'2030-06-02','t1':'12:00','t2':'13:00'}
        self.assertEqual(self.call(main.api_booking_time,body,1).status,200)
        row=self.state('b626',ref)
        self.assertEqual((row['status'],row['curator'],row['slot']),('new',None,'12:00–13:00'))
        self.assertEqual(self.call(main.api_626_action,{'id':ref,'action':'approved'},3).status,200)
        self.assertNotEqual(self.call(main.api_626_action,{'id':ref,'action':'approved'},2).status,200)

    def test_626_senior_edits_details_without_changing_time(self):
        ref=self.studio(day='2030-06-02')
        body={'kind':'626','id':ref,'d1':'2030-06-02','t1':'10:00','t2':'11:00','goal':'Новая съёмка','needs':['Хромакей']}
        self.assertEqual(self.call(main.api_booking_time,body,3).status,200)
        self.assertEqual(self.state('b626',ref)['goal'],'Новая съёмка')

    def test_approval_statistics_and_studio_deep_link(self):
        ref,_=self.request();bid=self.studio(day='2030-06-02',status='new',curator=None)
        self.call(main.api_req_action,{'id':ref,'action':'approved'},2)
        self.call(main.api_626_action,{'id':bid,'action':'approved'},3)
        stats=json.loads(self.call(main.api_stats,{},3).text)['stats']['adminStats']
        self.assertEqual(sum(a['approved'] for a in stats),2)
        with patch.object(main,'WEBAPP_URL','https://example.test'):
            button=main.request_button(bid,kind='626')
            query=parse_qs(urlsplit(button.inline_keyboard[0][0].web_app.url).query)
            self.assertEqual(query['kind'],['626'])


if __name__=='__main__':unittest.main()
