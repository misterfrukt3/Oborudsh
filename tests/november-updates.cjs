const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const page=await browser.newPage({viewport:{width:390,height:844},reducedMotion:'reduce'});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',r=>r.request().url().startsWith('http://127.0.0.1:8745')?r.continue():r.abort());
 await page.clock.install({time:new Date('2030-06-01T05:00:00Z')});
 await page.goto('http://127.0.0.1:8745');
 await page.addStyleTag({content:'.proto-bar{display:none}'});
 await page.evaluate(()=>{
  role='admin';
  const base=requests.find(r=>r.status==='new');
  requests=[
   {...base,id:901,author:'Анна Фото',event:'Интервью',deps:['Фото','Видео'],dep:'Фото',orgs:['Media BMSTU','Студсовет'],items:[['Nikon D7000',1]],d1Iso:'2030-06-04',d2Iso:'2030-06-06',t1:'10:00',t2:'11:00',status:'new',curator:null,me:true},
   {...base,id:902,author:'Борис Звук',event:'Концерт',deps:['Звук'],dep:'Звук',orgs:['Оркестр'],items:[['Canon 5D Mark III',1]],d1Iso:'2030-06-07',d2Iso:'2030-06-08',t1:'10:00',t2:'11:00',status:'approved',curator:null,me:false},
   {...base,id:903,author:'Анна Фото',event:'Архив',deps:['Фото'],dep:'Фото',orgs:['Студсовет'],items:[['Nikon D7000',1]],status:'closed',me:true},
  ];resetTo('allRequests');
 });
 // The full list and every metadata filter are usable by ordinary admins.
 assert.equal(await page.locator('.tappable').count(),2);
 await page.locator('summary').click();
 await page.locator('#filter-all-dep').selectOption('Видео');
 assert.equal(await page.locator('.tappable').count(),1);
 assert.match(await page.locator('.tappable').innerText(),/901/);
 await page.locator('#filter-all-dep').selectOption('');
 await page.locator('#filter-all-person').selectOption('Борис Звук');
 assert.match(await page.locator('.tappable').innerText(),/902/);
 await page.locator('#filter-all-person').selectOption('');
 await page.locator('#filter-all-org').selectOption('Студсовет');
 assert.equal(await page.locator('.tappable').count(),1);
 await page.locator('#filter-all-org').selectOption('');
 await page.locator('#filter-all-day').fill('2030-06-05');
 assert.match(await page.locator('.tappable').innerText(),/901/);
 await page.locator('#filter-all-day').fill('');
 await page.locator('#filter-all-item').selectOption('Canon 5D Mark III');
 assert.match(await page.locator('.tappable').innerText(),/902/);
 await page.locator('#filter-all-item').selectOption('');
 await page.locator('#filter-all-sort').selectOption('newest');
 assert.match(await page.locator('.tappable').first().innerText(),/902/);
 await page.locator('#filter-all-search').fill('nikon');
 assert.match(await page.locator('.tappable').innerText(),/901/);
 await page.getByRole('button',{name:'Сбросить фильтры'}).click();
 // Approval, assignment and issue are three separate steps for seniors too.
 await page.evaluate(()=>{role='senior';resetTo('adminReq',{id:901});});
 assert.equal(await page.locator('#achat-inp').count(),1);
 await page.getByRole('button',{name:'Согласовать заявку',exact:true}).click();
 assert.equal(await page.getByRole('button',{name:'Стать куратором',exact:true}).count(),1);
 assert.equal(await page.getByRole('button',{name:/Выдать оборудование/}).count(),0);
 assert.match(await page.locator('#screen').innerText(),/Согласовал: @you/);
 await page.getByRole('button',{name:'Стать куратором',exact:true}).click();
 assert.equal(await page.getByRole('button',{name:/Выдать оборудование/}).count(),1);
 await page.evaluate(()=>{role='user';resetTo('reqDetail',{id:901});});
 assert.equal(await page.locator('#chat-inp').count(),1);
 await page.getByRole('button',{name:'Изменить состав и детали',exact:true}).click();
 assert.equal(await page.evaluate(()=>wiz.editId),901);
 // Backspace goes back once a field is empty; typing advances again.
 const hour=page.getByRole('textbox',{name:'Получение: часы'}),minute=page.getByRole('textbox',{name:'Получение: минуты'});
 await minute.focus();await minute.evaluate(e=>e.setSelectionRange(e.value.length,e.value.length));await minute.press('Backspace');
 assert.equal(await minute.evaluate(e=>document.activeElement===e),true);
 await minute.press('Backspace');
 assert.equal(await hour.evaluate(e=>document.activeElement===e),true);
 await hour.press('ControlOrMeta+A');await hour.pressSequentially('12');
 assert.equal(await minute.evaluate(e=>document.activeElement===e),true);
 await minute.press('Backspace');assert.equal(await hour.evaluate(e=>document.activeElement===e),true);
 await hour.evaluate(e=>e.setSelectionRange(e.value.length,e.value.length));
 await hour.press('Delete');assert.equal(await minute.evaluate(e=>document.activeElement===e),true);
 // Both camera descriptions appear in the cart. Nikon already includes its lens.
 await page.evaluate(()=>{wiz.step=2;wiz.cart={'Nikon D7000':1};render();openCart();});
 assert.match(await page.locator('.camera-description').innerText(),/24–70 f\/2.8/);
 assert.match(await page.locator('.camera-description').innerText(),/зарядка.*дополнительный аккумулятор/);
 assert.equal(await page.evaluate(()=>kitWarnings().length),0);
 await page.evaluate(()=>{wiz.cart={'Canon 5D Mark III':1};openCart();});
 assert.match(await page.locator('.camera-description').innerText(),/Объектив нужно добавить отдельно/);
 await page.evaluate(()=>{$('overlay').innerHTML='';role='admin';equipmentScope='queue';resetTo('equipmentState');});
 await page.locator('#equipment-search').fill('Canon');
 assert.match(await page.locator('.equipment-holder').innerText(),/902/);
 assert.equal(await page.getByRole('button',{name:'Камеры',exact:true}).count(),1);
 // Every tab restores its previous position after a detail view or another role.
 await page.evaluate(()=>{
  equipmentSearch='';role='admin';
  const base=requests[0];requests=Array.from({length:24},(_,i)=>({...base,id:1000+i,status:'approved',curator:null}));
  resetTo('allRequests');$('screen').scrollTop=650;
 });
 const allTop=await page.locator('#screen').evaluate(e=>e.scrollTop);
 await page.evaluate(()=>navTo('adminReq',{id:1005}));
 await page.evaluate(()=>goBack());
 assert.equal(await page.locator('#screen').evaluate(e=>e.scrollTop),allTop);
 await page.evaluate(()=>{setRole('user');resetTo('home');setRole('admin');navTo('allRequests');});
 assert.equal(await page.locator('#screen').evaluate(e=>e.scrollTop),allTop);
 // A single persistent toggle hides completed equipment and studio history.
 await page.evaluate(()=>{requests.push({...requests[0],id:777,event:'Past unique booking',status:'closed',me:true});role='user';resetTo('home');});
 assert.match(await page.locator('#screen').innerText(),/История броней/i);
 await page.getByRole('button',{name:'Скрыть завершённые',exact:true}).click();
 assert.equal(await page.locator('[onclick*="id:777"]').count(),0);
 await page.getByRole('button',{name:'Показать завершённые',exact:true}).click();
 assert.equal(await page.locator('[onclick*="id:777"]').count(),1);
 // Escaped appeals, anonymous sender, admin answers and closing/reopening.
 await page.evaluate(()=>{startAppeal();appealText='<img src=x onerror=alert(1)> Вопрос';appealAnon=true;openQuestion();});
 assert.equal(await page.locator('#q-text').inputValue(),'<img src=x onerror=alert(1)> Вопрос');
 await page.getByRole('button',{name:'Отправить',exact:true}).click();
 await page.evaluate(()=>{role='admin';appeals[0].me=false;resetTo('appeals');});
 await page.locator('.tappable').click();
 assert.match(await page.locator('#screen').innerText(),/Аноним/);
 await page.locator('#appeal-reply').fill('Получите у куратора');
 await page.getByRole('button',{name:'Отправить',exact:true}).click();
 assert.match(await page.locator('.chat').innerText(),/Получите у куратора/);
 await page.getByRole('button',{name:'Закрыть обращение',exact:true}).click();
 assert.equal(await page.locator('#appeal-reply').count(),0);
 await page.getByRole('button',{name:'Открыть снова',exact:true}).click();
 assert.equal(await page.locator('#appeal-reply').count(),1);
 // Settings and all new views fit common phone widths in both themes.
 await page.evaluate(()=>resetTo('preferences'));
 await page.getByRole('button',{name:'Панель админа',exact:true}).click();
 assert.equal(await page.evaluate(()=>preferences.startPage),'adminHub');
 await page.evaluate(()=>openStartPage({isAdmin:true,isSenior:false}));
 assert.equal(await page.evaluate(()=>cur().name),'adminHub');
 for(const dark of [true,false])for(const width of [320,390,430]){
  await page.evaluate(dark=>$('phone').classList.toggle('dark',dark),dark);
  await page.setViewportSize({width,height:844});
  for(const name of ['allRequests','equipmentState','preferences','appeals','appealDetail']){
   await page.evaluate(name=>resetTo(name,name==='appealDetail'?{id:appeals[0].id}:{}),name);
   if(name==='allRequests')await page.locator('summary').click();
   assert.equal(await page.locator('#screen').evaluate(e=>e.scrollWidth<=e.clientWidth),true,`${name}: overflow ${width}`);
  }
 }
 await page.evaluate(()=>{$('phone').classList.add('dark');render();$('screen').scrollTop=0;document.querySelectorAll('.toast').forEach(t=>t.remove());});
 await page.screenshot({path:'.mac-local/november-appeal.png'});
 await page.evaluate(()=>{resetTo('allRequests');requestFilter('all').expanded=true;render();$('screen').scrollTop=0;});
 await page.screenshot({path:'.mac-local/november-filters.png'});
 // A real Telegram-style boot honors preferences; direct request links take priority.
 const payload=await page.evaluate(()=>({ok:true,registered:true,verified:'ok',isAdmin:true,isSenior:false,
  preferences:{startPage:'equipmentState',showPast:false},requests,bookings626,profile,appeals:[],revision:'1'}));
 const launch=await browser.newPage({viewport:{width:390,height:844}});
 launch.on('pageerror',e=>errors.push(e.message));
 await launch.route('**/*',r=>r.request().url().startsWith('http://127.0.0.1:8745')?r.continue():r.abort());
 await launch.route('**/api/**',r=>r.fulfill({json:payload}));
 await launch.goto('http://127.0.0.1:8745/?tgWebAppPlatform=tdesktop');
 await launch.waitForFunction(()=>cur().name==='equipmentState');
 assert.equal(await launch.evaluate(()=>role),'admin');
 await launch.goto('http://127.0.0.1:8745/?tgWebAppPlatform=tdesktop&tgWebAppStartParam=request_1005_admin');
 await launch.waitForFunction(()=>cur().name==='adminReq');
 assert.equal(await launch.evaluate(()=>cur().params.id),1005);
 payload.isAdmin=false;
 await launch.goto('http://127.0.0.1:8745/?tgWebAppPlatform=tdesktop');
 await launch.waitForFunction(()=>cur().name==='home');
 assert.equal(await launch.evaluate(()=>role),'user');
 assert.deepEqual(errors,[]);
 await browser.close();console.log('November UI: filters, scroll, time deletion, kit editing, cameras, appeals and settings passed.');
})().catch(e=>{console.error(e);process.exit(1)});
