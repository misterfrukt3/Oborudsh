const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:"msedge"});
 const page=await browser.newPage({viewport:{width:320,height:740}});
 const errors=[]; page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>route.request().url().startsWith('http://127.0.0.1:8745')?route.continue():route.abort());
 await page.goto('http://127.0.0.1:8745');
 console.log(await page.evaluate(()=>({screen:stack,quoteNames:CATALOG.flatMap(c=>c.items).filter(i=>/["'<>]/.test(i.short)).map(i=>i.short)})));
 await page.evaluate(()=>{role='user';resetTo('home');startWizard(true);wiz.d1='2030-06-02';wiz.d2='2030-06-02';wiz.t1='10:00';wiz.t2='12:00';wiz.event='Test';saveDraft();});
 await page.reload();
 assert.equal(await page.evaluate(()=>readDraft().event),'Test');
 await page.evaluate(()=>{startWizard();});
 assert.match(await page.locator('#overlay').innerText(),/Продолжить/);
 await page.evaluate(()=>{restoreDraft();});
 const result=await page.evaluate(async()=>{
   const names=CATALOG.flatMap(c=>c.items).filter(i=>/["'<>]/.test(i.short)).map(i=>i.short);
   const tricky=`A ' " &quot; <b> B`;
   const div=document.createElement('div');div.innerHTML=`<button onclick="window.roundTrip='${escJs(tricky)}'">${escHtml(tricky)}</button>`;div.firstChild.click();
   if(window.roundTrip!==tricky||div.textContent!==tricky)throw Error('escaping failed');
   for(const short of names){
     requests.unshift({id:989,items:[[short,1]],event:'Check',comment:'',d1Iso:'2030-06-02',d2Iso:'2030-06-02',t1:'10:00',t2:'12:00'});
     repeatReq(989);if(!Object.hasOwn(wiz.cart,short))throw Error('repeat name');
     startEditReq(989);if(!Object.hasOwn(wiz.cart,short))throw Error('edit name');
     requests.shift();
   }
   startWizard(true);const item=CATALOG.flatMap(c=>c.items).find(i=>!i.level&&i.total>1);
   SRV={};wiz.busy={[item.short]:item.total};wiz.capacity={[item.short]:item.total};
   const originalApi=api;api=async()=>({busy:wiz.busy,capacity:wiz.capacity});
   favSets=[{id:1,items:[[item.short,2]]}];await applyFavSet(1);
   if(wiz.cart[item.short])throw Error('fully busy favorite');
   wiz.busy[item.short]=item.total-1;await applyFavSet(1);
   if(wiz.cart[item.short]!==1)throw Error('partially busy favorite');
   api=originalApi;SRV=null;role='user';resetTo('home');
   return names;
 });
 console.log('Names and favorites passed',result);
 await page.evaluate(()=>{document.querySelectorAll('.toast').forEach(t=>t.remove());document.querySelector('#overlay').innerHTML='';});
 await page.waitForTimeout(450);
 await page.screenshot({path:'tests/user-320.png',fullPage:true});
 await page.evaluate(()=>setRole('admin'));
 await page.waitForTimeout(450);
 await page.screenshot({path:'tests/admin-320.png',fullPage:true});
 await page.evaluate(()=>{
   role='senior';resetTo('adminReq',{id:requests.find(r=>r.status==='new').id});
 });
 await page.waitForTimeout(450);
 assert.equal(await page.getByRole('button',{name:'Отклонить с причиной',exact:true}).count(),1);
 await page.screenshot({path:'tests/senior-request-320.png',fullPage:true});
 await page.evaluate(()=>{
   SRV={};window.savedApi=api;api=async()=>{throw Error('Доставка временно недоступна');};
   startReturn(123);retPhotos=['data:image/jpeg;base64,YQ=='];render();document.querySelector('#ret-comm').value='Состояние';doReturn(123);
 });
 await page.waitForFunction(()=>!_busy);
 assert.equal(await page.evaluate(()=>retPhotos.length),1);
 assert.equal(await page.locator('#ret-comm').inputValue(),'Состояние');
 assert.match(await page.locator('[role=alert]').innerText(),/Доставка временно недоступна/);
 await page.evaluate(()=>{handover626(123);hoPhotos=['data:image/jpeg;base64,YQ=='];render();doHandover626(123);});
 await page.waitForFunction(()=>!_busy);
 assert.equal(await page.evaluate(()=>hoPhotos.length),1);
 assert.match(await page.locator('[role=alert]').innerText(),/Доставка временно недоступна/);
 await page.evaluate(()=>{api=window.savedApi;SRV=null;});
 console.log('Photo retry forms and senior rejection passed');
 assert.deepEqual(errors,[]);
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});

