const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PW_CHANNEL?{channel:process.env.PW_CHANNEL}:{})});
 const page=await browser.newPage({viewport:{width:390,height:844},reducedMotion:'reduce',timezoneId:'America/Los_Angeles'});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.clock.install({time:new Date('2030-06-01T05:00:00Z')}); // 08:00 Moscow
 await page.route('**/*',r=>r.request().url().startsWith('http://127.0.0.1:8745')?r.continue():r.abort());
 await page.goto('http://127.0.0.1:8745');
 await page.evaluate(()=>{role='user';resetTo('home');});
 assert.equal(await page.getByText('Медиа выезд',{exact:true}).count(),0);
 await page.evaluate(()=>{startWizard(true);wiz.month={y:2030,m:5};render();});
 assert.equal(await page.locator(`.day[onclick="wizPick('2030-06-02')"]`).isDisabled(),true);
 assert.equal(await page.locator(`.day[onclick="wizPick('2030-06-09')"]`).isDisabled(),true);
 assert.equal(await page.locator(`.day[onclick="wizPick('2030-06-08')"]`).isDisabled(),false);
 await page.evaluate(()=>wizPick('2030-06-04'));
 assert.equal(await page.locator(`.day[onclick="wizPick('2030-06-11')"]`).isDisabled(),false,'return may be after seven days');
 const dateResults=await page.evaluate(()=>{
  wiz.d1='2030-06-08';wiz.d2='2030-06-08';wiz.t1='08:00';wiz.t2='09:00';const edge=dateBlock();
  wiz.t1='08:01';const over=dateBlock();
  role='admin';wiz.d1='2030-06-18';wiz.d2=wiz.d1;const admin=dateBlock();
  wiz.d1='2030-06-02';wiz.d2=wiz.d1;const sunday=dateBlock();
  role='senior';const senior=dateBlock();role='user';wiz.d1='2030-06-01';wiz.d2=wiz.d1;wiz.t1='10:00';wiz.t2='11:00';const today=dateBlock();return {edge,over,admin,sunday,senior,today};
 });
 assert.equal(dateResults.edge,null);assert.match(dateResults.over,/7 дней/);assert.equal(dateResults.admin,null);
 assert.match(dateResults.sunday,/воскресень/);assert.equal(dateResults.senior,null);assert.equal(dateResults.today,null,'today uses Moscow time');
 await page.evaluate(()=>{role='user';start626();wiz626.month={y:2030,m:5};render();});
 assert.equal(await page.locator(`.day[onclick="s626Pick('2030-06-02')"]`).isDisabled(),true);
 await page.evaluate(()=>{wiz626.day='2030-06-03';wiz626.from='13:59';wiz626.to='15:00';wiz626.goal='Интервью';render();});
 assert.match(await page.locator('#screen').innerText(),/с 14:00/);
 assert.equal(await page.getByRole('button',{name:'Отправить на согласование',exact:true}).isDisabled(),true);
 await page.evaluate(()=>{wiz626.from='14:00';render();});
 assert.equal(await page.getByRole('button',{name:'Отправить на согласование',exact:true}).isDisabled(),false);
 await page.evaluate(()=>{role='admin';wiz626.day='2030-06-02';wiz626.from='10:00';render();});
 assert.equal(await page.getByRole('button',{name:'Отправить на согласование',exact:true}).isDisabled(),false);
 assert.doesNotMatch(await page.locator('#screen').innerText(),/кроме админ/);
 const id=await page.evaluate(()=>{
  const r=requests[0],it=CATALOG.flatMap(c=>c.items).find(i=>!i.level&&i.total>=3);
  Object.assign(r,{status:'approved',me:true,curator:'@you',items:[[it.short,1]],d1Iso:'2030-06-01',d2Iso:'2030-06-01',t1:'10:00',t2:'11:00',from:'01.06, 10:00',to:'01.06, 11:00',createdTs:Date.now()/1000,nums:{[it.short]:[1]}});
  role='admin';resetTo('adminReq',{id:r.id});return r.id;
 });
 assert.equal(await page.locator('.admin-risk').count(),2);
 await page.screenshot({path:'tests/booking-policy-admin.png',fullPage:true});
 await page.evaluate(id=>{role='user';resetTo('reqDetail',{id});},id);
 assert.equal(await page.locator('.admin-risk').count(),0);
 await page.getByRole('button',{name:'✏️ Редактировать',exact:true}).click();
 await page.evaluate(()=>{wiz.cart[Object.keys(wiz.cart)[0]]=2;wiz.step=4;render();});
 await page.getByRole('button',{name:'Сохранить изменения',exact:true}).click();
 assert.equal(await page.evaluate(id=>requests.find(r=>r.id===id).status,id),'new');
 assert.equal(await page.evaluate(id=>requests.find(r=>r.id===id).curator,id),'@you');
 await page.evaluate(id=>{role='admin';const r=requests.find(r=>r.id===id);r.status='issued';resetTo('adminReq',{id});},id);
 await page.getByRole('button',{name:'Изменить состав',exact:true}).click();
 assert.equal(await page.evaluate(()=>wiz.step),2);
 await page.evaluate(()=>{wiz.cart[Object.keys(wiz.cart)[0]]=1;wiz.step=4;render();});
 await page.getByRole('button',{name:'Сохранить изменения',exact:true}).click();
 assert.deepEqual(await page.evaluate(id=>{const r=requests.find(r=>r.id===id);return [r.status,r.reviewPending,r.curator];},id),['issued',true,'@you']);
 await page.getByRole('button',{name:'Согласовать изменённый состав',exact:true}).click();
 assert.deepEqual(await page.evaluate(id=>{const r=requests.find(r=>r.id===id);return [r.status,r.reviewPending];},id),['issued',false]);
 for(const width of [320,390,430]){
  await page.setViewportSize({width,height:844});
  await page.evaluate(id=>{requests.find(r=>r.id===id).status='approved';resetTo('adminReq',{id});},id);
  assert.equal(await page.evaluate(()=>document.querySelector('#screen').scrollWidth<=document.querySelector('#screen').clientWidth),true,`admin overflow ${width}`);
  await page.evaluate(()=>{const b=bookings626[0];b.when='2030-06-01';b.createdTs=Date.now()/1000;resetTo('studioDetail',{id:b.id});});
  assert.equal(await page.evaluate(()=>document.querySelector('#screen').scrollWidth<=document.querySelector('#screen').clientWidth),true,`626 overflow ${width}`);
 }
 await page.clock.setFixedTime(new Date('2030-06-02T09:00:00Z'));
 const sunday=await page.evaluate(id=>{
  const r=requests.find(r=>r.id===id);r.status='issued';role='user';resetTo('reqDetail',{id});
  return {message:equipmentSundayError(),buttons:document.querySelectorAll('button[onclick^="startReturn"]').length};
 },id);
 assert.match(sunday.message,/воскресень/);assert.equal(sunday.buttons,0);
 await page.evaluate(id=>{role='admin';const r=requests.find(r=>r.id===id);r.status='approved';r.curator=null;resetTo('adminReq',{id});},id);
 assert.equal(await page.getByRole('button',{name:'Стать куратором',exact:true}).isEnabled(),true);
 await page.getByRole('button',{name:'Стать куратором',exact:true}).click();
 assert.equal(await page.getByRole('button',{name:'Снять с себя кураторство',exact:true}).isEnabled(),true);
 assert.equal(await page.getByRole('button',{name:/Выдача и сдача оборудования по воскресеньям/}).isDisabled(),true);
 await page.evaluate(()=>{role='senior';});assert.equal(await page.evaluate(()=>equipmentSundayError()),null);
 // Computer Telegram: native header is absent; the app provides a visible back button.
 await page.goto('http://127.0.0.1:8745/?tgWebAppPlatform=tdesktop');
 await page.waitForFunction(()=>stack.at(-1)?.name==='bootError');
 await page.evaluate(()=>{SRV=null;role='user';resetTo('home');navTo('studio');});
 assert.equal(await page.locator('#desktop-back').isVisible(),true);
 await page.locator('#desktop-back button').click();
 assert.equal(await page.evaluate(()=>stack.at(-1).name),'home');
 assert.equal(await page.locator('#desktop-back').isVisible(),false);
 assert.deepEqual(errors,[]);
 await browser.close();console.log('Booking dates, roles, warnings, kit reapproval, mobile layouts and desktop back passed.');
})().catch(e=>{console.error(e);process.exit(1)});
