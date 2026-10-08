const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const page=await browser.newPage({viewport:{width:390,height:844},reducedMotion:'reduce'});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',r=>r.request().url().startsWith('http://127.0.0.1:8745')?r.continue():r.abort());
 await page.goto('http://127.0.0.1:8745');
 const id=await page.evaluate(()=>{const r=requests[0];r.status='approved';r.me=true;role='user';resetTo('reqDetail',{id:r.id});return r.id;});
 await page.getByRole('button',{name:'Отменить с причиной',exact:true}).click();
 await page.getByRole('button',{name:'Подтвердить отмену',exact:true}).click();
 assert.equal(await page.locator('#cancel-reason').count(),1);
 assert.equal(await page.evaluate(id=>requests.find(r=>r.id===id).status,id),'approved');
 await page.locator('#cancel-reason').fill('Съёмка перенесена');
 await page.getByRole('button',{name:'Подтвердить отмену',exact:true}).click();
 assert.equal(await page.evaluate(id=>requests.find(r=>r.id===id).status,id),'canceled');
 assert.match(await page.evaluate(id=>requests.find(r=>r.id===id).history.at(-1)[1],id),/Съёмка перенесена/);
 for(const status of ['issued','ret','closed']){
   await page.evaluate(({id,status})=>{requests.find(r=>r.id===id).status=status;resetTo('reqDetail',{id});},{id,status});
   assert.equal(await page.getByRole('button',{name:'Отменить с причиной',exact:true}).count(),0);
 }
 for(const status of ['new','approved']){
   await page.evaluate(({id,status})=>{const r=requests.find(r=>r.id===id);r.status=status;r.curator=null;role='admin';resetTo('adminReq',{id});},{id,status});
   await page.getByRole('button',{name:'Отменить с причиной',exact:true}).click();
   await page.locator('#rejreq-reason').fill('Некому выдать оборудование');
   await page.getByRole('button',{name:'Отклонить',exact:true}).click();
   assert.equal(await page.evaluate(id=>requests.find(r=>r.id===id).status,id),'rejected');
 }
 const bid=await page.evaluate(()=>{const b=bookings626[0];b.when='2030-06-02';b.slot='10:00–11:00';b.status='approved';b.me=true;role='user';resetTo('studioDetail',{id:b.id});return b.id;});
 await page.getByRole('button',{name:'Отменить с причиной',exact:true}).click();
 await page.locator('#cancel-reason').fill('Аудитория больше не нужна');
 await page.getByRole('button',{name:'Подтвердить отмену',exact:true}).click();
 assert.equal(await page.evaluate(id=>bookings626.find(b=>b.id===id).status,bid),'canceled');
 await page.evaluate(()=>{SRV={isAdmin:false,isSenior:false,mediaTrip:{allowed:false}};resetTo('home');});
 assert.equal(await page.getByText('Медиа выезд',{exact:true}).count(),0);
 await page.evaluate(()=>resetTo('mediaTrip'));
 assert.match(await page.locator('#screen').innerText(),/добавленным участникам/);
 await page.evaluate(()=>{SRV={isAdmin:false,isSenior:false,mediaTrip:{...structuredClone(mtDemo),allowed:true,canManage:false,canConfigure:false,team:1,teams:[{number:1,curator:1,members:[{id:1,name:'Участник'}]}]}};resetTo('home');});
 await page.getByText('Медиа выезд',{exact:true}).click();
 assert.match(await page.locator('#screen').innerText(),/Команда 1/);
 assert.equal(await page.getByText('Панель рентала',{exact:true}).count(),0);
 assert.equal(await page.locator('#mt-code').count(),0);
 await page.evaluate(()=>{SRV=null;role='user';requests[0].status='approved';requests[0].me=true;resetTo('reqDetail',{id:requests[0].id});});
 for(const width of [320,390,430]){
   await page.setViewportSize({width,height:844});
   await page.getByRole('button',{name:'Отменить с причиной',exact:true}).click();
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
   await page.getByRole('button',{name:'Назад',exact:true}).click();
 }
 assert.deepEqual(errors,[]);
 await page.screenshot({path:require('node:path').join(__dirname,'october-updates.png')});
 await browser.close();
 console.log('Cancellation reasons, admin controls, membership visibility and mobile layouts passed.');
})().catch(e=>{console.error(e);process.exit(1)});
