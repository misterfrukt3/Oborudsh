/* Visual regression for booking layouts, every visible workflow and Telegram insets.
   Run against the static prototype on :8745; no backend or credentials are used. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

const BASE=process.env.LAYOUT_BASE_URL||'http://127.0.0.1:8745';
const OUT=path.resolve('.mac-local/responsive-qa');
const LONG_GOALS=[
 'Фотосессия участников сборной Турклуба МГТУ им. Н. Э. Баумана',
 'Обучалка по работе в студии для стажеров',
];
const failures=[],pageErrors=[];
let scenarios=0;
fs.mkdirSync(OUT,{recursive:true});

async function installFixtures(page){
 await page.evaluate(goals=>{
  stopRealtime();
  // Realistic lengths reproduce the production screenshot instead of short demo labels.
  profile={name:'Александрова Мария Константиновна',short:'Мария Александрова',tg:'@media_bmstu_long_username',orgs:['Media BMSTU','Студенческий совет факультета информационных технологий'],deps:['Фото','Видео','Работа с организациями'],status:'активист'};
  const base=requests[0];
  const longItem=CATALOG.flatMap(c=>c.items).find(i=>i.short.includes('SmallRig'))||CATALOG[0].items[0];
  requests=[
   {...base,id:901,me:true,author:profile.name,event:goals[0],dep:'Работа с организациями',deps:profile.deps,orgs:profile.orgs,status:'new',curator:null,curMe:false,items:[['Nikon D7000',1],[longItem.short,1]],d1Iso:'2030-06-04',d2Iso:'2030-06-06',t1:'19:00',t2:'21:30',from:'04.06, 19:00',to:'06.06, 21:30',history:[['new','01.06, 08:00']],chat:[],nums:{},reviewPending:false},
   {...base,id:902,me:false,author:'Константинов Александр Александрович',event:goals[1],dep:'Видео',deps:['Видео'],orgs:['Media BMSTU'],status:'approved',curator:null,curMe:false,items:[['Canon 5D Mark III',1]],d1Iso:'2030-06-04',d2Iso:'2030-06-04',t1:'17:00',t2:'21:00',from:'04.06, 17:00',to:'04.06, 21:00',history:[['new','01.06, 08:00'],['approved','01.06, 08:01']],chat:[],nums:{},reviewPending:false},
   {...base,id:903,me:true,author:profile.name,event:'Выданный комплект для съёмки университетского мероприятия',dep:'Фото',deps:['Фото'],orgs:['Media BMSTU'],status:'issued',curator:'@you',curMe:true,items:[['Nikon D7000',1]],d1Iso:'2030-06-04',d2Iso:'2030-06-06',t1:'10:00',t2:'20:00',from:'04.06, 10:00',to:'06.06, 20:00',history:[['new','01.06, 08:00']],chat:[{who:'me',label:'Пользователь',text:'Уточните, пожалуйста, место получения и можно ли дополнительно взять зарядное устройство для камеры?',tm:'08:00'}],nums:{'Nikon D7000':[1]},reviewPending:false},
  ];
  const studio=bookings626[0];
  bookings626=[
   {...studio,id:801,me:false,author:'Разина Мария Константиновна',goal:goals[0],when:'2030-06-04',slot:'19:00–21:30',needs:['Помощь команды Media Tech и оборудование для записи звука'],status:'approved',curator:null,curMe:false,history:[['new','01.06, 08:00'],['approved','01.06, 08:01']],chat:[]},
   {...studio,id:802,me:false,author:'Симонов Александр Александрович',goal:goals[1],when:'2030-06-05',slot:'17:00–21:00',needs:[],status:'approved',curator:null,curMe:false,history:[['new','01.06, 08:00']],chat:[]},
   {...studio,id:803,me:true,author:profile.name,goal:goals[0],when:'2030-06-06',slot:'19:00–21:30',needs:['Хромакей','Свет'],status:'new',curator:null,curMe:false,history:[['new','01.06, 08:00']],chat:[]},
  ];
  appeals=[{id:701,me:true,author:profile.name,text:'Подскажите, как организовать получение большого комплекта оборудования и дополнительного аккумулятора?',status:'open',createdAt:'2030-06-01 08:00',photoCount:0,chat:[{who:'them',label:'Админ',text:'Напишите куратору заявки: он поможет подобрать время и уточнит состав комплекта.',tm:'08:10'}],unread:1}];
  equipmentUnits=[{short:longItem.short,num:1,serial:'SERIAL-12345678901234567890',state:'ready',note:'Комплект с длинным описанием и дополнительными принадлежностями',updatedAt:'2030-06-01',updatedBy:'@administrator_with_long_username'}];
  unitPassport={...equipmentUnits[0],history:[{requestId:901,user:profile.name,from:'04.06, 19:00',to:'06.06, 21:30',status:'closed',issuedBy:'@administrator_with_long_username',returnedBy:'@another_administrator',takenAt:'04.06, 19:00',returnedAt:'06.06, 21:30'}]};
  inventory={active:true,id:12,createdAt:'01.06, 08:00',createdBy:profile.name,isParticipant:true,canManage:true,canFinish:true,canEmergency:true,participants:[{name:profile.name},{name:'Константинов Александр Александрович'}],summary:{total:200,checked:184,ready:175,missing:5,broken:4},categories:[{name:'Дополнительные принадлежности для оборудования',status:'free',checked:0,total:20},{name:'Камеры',status:'working',mine:true,checked:4,total:6}],locations:['Рентал · шкаф с дополнительными принадлежностями','Аудитория 626 · стеллаж для камер']};
  invCategory='Дополнительные принадлежности для оборудования';
  invItems=[{id:601,name:longItem.full,category:invCategory,inventoryNum:'BMSTU-626-12345678901234567890',checked:false,found:true,state:'stored',source:'university',rental:true,storageLocation:inventory.locations[0],issuedTo:'',issuedUntil:'',comment:'Проверить комплектность креплений.',currentData:{Производитель:'SmallRig',Назначение:'Дополнительные принадлежности для съёмочного оборудования'}}];
  invItemId=601;
  statsData={top:[[longItem.full,35],['Nikon D7000',12]],months:[['06.2030',35]],months626:[['06.2030',18]],adminStats:[{name:'@administrator_with_long_username',curated:10,approved:25,issued:12,returned:11,rejected:2}],users:[[profile.name,15]],totals:{requests:300,b626:130},topRejecters:[]};
  preferences={startPage:'adminHub',showPast:true};
  favSets=[{id:11,name:'Комплект для съёмки университетского мероприятия',items:[['Nikon D7000',1],['Canon 5D Mark III',1]]}];
  window.__layoutFixture={requests,bookings626,profile,appeals,equipmentUnits};
 },LONG_GOALS);
}

const CORE=[
 ['home',()=>{role='user';resetTo('home');}],
 ['adminHub',()=>{role='admin';adminTab='queue';resetTo('adminHub');}],
 ['seniorHub',()=>{role='senior';resetTo('seniorHub');}],
 ['studio',()=>{role='user';resetTo('studio');}],
 ['studioDetail',()=>{role='user';resetTo('studioDetail',{id:803});}],
 ['adminReq',()=>{role='senior';resetTo('adminReq',{id:901});}],
 ['reqDetail',()=>{role='user';resetTo('reqDetail',{id:901});}],
 ['wizard-dates',()=>{role='user';startWizard(true);wiz.d1='2030-06-04';wiz.d2='2030-06-06';wiz.t1='19:00';wiz.t2='21:30';wiz.event='Подготовка съёмки университетского мероприятия';wiz.cart={'Nikon D7000':1,'Canon 5D Mark III':1};wiz.step=1;render();}],
 ['wizard-catalog',()=>{wiz.step=2;wiz.catFilter='Камеры';render();}],
 ['wizard-details',()=>{wiz.step=3;render();}],
 ['wizard-confirm',()=>{wiz.step=4;render();}],
 ['studioForm',()=>{role='user';start626();wiz626.day='2030-06-04';wiz626.from='19:00';wiz626.to='21:30';wiz626.goal='Фотосессия участников сборной Турклуба МГТУ им. Н. Э. Баумана';render();}],
 ['allRequests-equipment',()=>{role='admin';allRequestKind='req';allRequestScope='active';requestFilter('all').expanded=true;resetTo('allRequests');}],
 ['allRequests-studio',()=>{allRequestKind='626';resetTo('allRequests');}],
 ['equipmentState',()=>{role='admin';equipmentScope='issued';equipmentSearch='';equipmentCategory='Все';resetTo('equipmentState');}],
 ['bookingTime',()=>{role='senior';openBookingTime('req',901);}],
 ['preferences',()=>{role='admin';resetTo('preferences');}],
 ['appealDetail',()=>{role='user';resetTo('appealDetail',{id:701});}],
 ['inventoryItemForm',()=>{role='senior';resetTo('inventoryItemForm');}],
 ['catBlocks',()=>{role='senior';resetTo('catBlocks');}],
];
const EXTRA=[
 ['rules',()=>{role='user';resetTo('rules',{readonly:true});}],
 ['manual',()=>resetTo('manual')],
 ['regProfile',()=>{role='user';reg=null;resetTo('regProfile',{edit:true});}],
 ['returnFlow',()=>{retPhotos=[];resetTo('returnFlow',{id:903});}],
 ['handover626',()=>{hoPhotos=[];resetTo('handover626',{id:801});}],
 ['adminCalendar',()=>{role='admin';adminWeek=0;resetTo('adminCalendar');}],
 ['equipmentUnits',()=>{role='admin';unitQ='';resetTo('equipmentUnits');}],
 ['unitPassport',()=>resetTo('unitPassport')],
 ['inventoryStart',()=>{role='senior';invParticipants=new Set();resetTo('inventoryStart');}],
 ['inventoryHub',()=>resetTo('inventoryHub')],
 ['inventoryItems',()=>resetTo('inventoryItems')],
 ['inventoryComplete',()=>resetTo('inventoryComplete')],
 ['adminUsers',()=>resetTo('adminUsers')],
 ['blacklist',()=>resetTo('blacklist')],
 ['addEquip',()=>startAddEquip()],
 ['removeEquip',()=>startRemoveEquip()],
 ['stats',()=>resetTo('stats')],
 ['reqChats',()=>resetTo('reqChats')],
 ['problemReturns',()=>resetTo('problemReturns')],
 ['appeals',()=>{role='admin';resetTo('appeals');}],
];
const OVERLAYS=[
 ['cart',()=>{role='user';startWizard(true);wiz.d1='2030-06-04';wiz.d2='2030-06-06';wiz.t1='19:00';wiz.t2='21:30';wiz.cart={'Nikon D7000':1,'Canon 5D Mark III':1};wiz.step=2;render();openCart();}],
 ['question',()=>{resetTo('home');startAppeal();}],
 ['cancel',()=>{resetTo('reqDetail',{id:901});cancelReasonModal('Отменить заявку на съёмку университетского мероприятия',()=>{});}],
 ['change-time',()=>{role='admin';resetTo('adminReq',{id:901});requestBookingTime('req',901);}],
 ['issue',()=>{role='admin';resetTo('adminReq',{id:902});initIssue(requests.find(r=>r.id===902),false);}],
 ['favorite',()=>{role='user';startWizard(true);wiz.cart={'Nikon D7000':1,'Canon 5D Mark III':1};saveFavSet();}],
 ['storage',()=>{role='senior';resetTo('inventoryHub');addStorageModal();}],
 ['confirmation',()=>confirmModal('Завершить инвентаризацию оборудования?', 'Все результаты проверки будут сохранены. Убедитесь, что команда завершила проверку всех экземпляров.',()=>{})],
];

async function measure(page,{mode,width,height,dark,label,overlay=false,booking=false}){
 const context=`${mode}/${width}x${height}/${dark?'dark':'light'}/${label}`;
 const issues=await page.evaluate(({overlay,booking,goals})=>{
  const issues=[],phone=document.getElementById('phone'),screen=document.getElementById('screen');
  const rect=e=>{const r=e.getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
  const visible=e=>e.getBoundingClientRect().width>0&&e.getBoundingClientRect().height>0&&getComputedStyle(e).visibility!=='hidden';
  const overlap=(a,b)=>Math.min(a.right,b.right)-Math.max(a.left,b.left)>1&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1;
  const p=rect(phone),s=rect(screen),scope=overlay?document.getElementById('overlay'):screen;
  const app=window.Telegram?.WebApp;
  const safeTop=app?(Number(app.safeAreaInset?.top)||0)+(Number(app.contentSafeAreaInset?.top)||0):0;
  const safeBottom=app?(Number(app.safeAreaInset?.bottom)||0)+(Number(app.contentSafeAreaInset?.bottom)||0):0;
  const first=screen.querySelector('.screen-inner')?.firstElementChild;
  if(app&&!overlay&&screen.scrollTop<1&&first&&rect(first).top<p.top+safeTop-2)issues.push('content under native Telegram top safe area');
  if(screen.scrollWidth>screen.clientWidth+2)issues.push(`screen overflow ${screen.scrollWidth}/${screen.clientWidth}`);
  if(document.documentElement.scrollWidth>innerWidth+2)issues.push(`document overflow ${document.documentElement.scrollWidth}/${innerWidth}`);
  if(s.height<Math.min(150,innerHeight*.32))issues.push(`unusable content height ${Math.round(s.height)}`);
  for(const e of scope.querySelectorAll('h1.big,.booking-time,.next-step,.pill,button,input,select,textarea')){
   if(!visible(e))continue;
   const r=rect(e);
   const intentionalScroll=(()=>{for(let a=e.parentElement;a&&a!==scope;a=a.parentElement){const c=getComputedStyle(a);if(/auto|scroll/.test(c.overflowX)&&a.scrollWidth>a.clientWidth+2)return true;}return false;})();
   if(!intentionalScroll&&(r.left<p.left-2||r.right>p.right+2))issues.push(`${e.tagName.toLowerCase()}.${e.className||e.id} outside shell: ${Math.round(r.left)}..${Math.round(r.right)} vs ${Math.round(p.left)}..${Math.round(p.right)}`);
   if((e.matches('h1.big,.booking-time,.pill,button'))&&e.clientWidth>0&&e.scrollWidth>e.clientWidth+2)issues.push(`clipped text ${e.tagName.toLowerCase()}.${e.className}: ${e.scrollWidth}/${e.clientWidth} (${e.textContent.trim().slice(0,45)})`);
  }
  for(const row of scope.querySelectorAll('.row,.btnrow,.acts')){
   const controls=[...row.children].filter(e=>e.matches('button,input,select,textarea')&&visible(e));
   for(let i=0;i<controls.length;i++)for(let j=i+1;j<controls.length;j++)if(overlap(rect(controls[i]),rect(controls[j])))issues.push(`overlapping controls in .${row.className}`);
  }
  if(screen.dataset.screen==='catBlocks')for(const card of screen.querySelectorAll('.card')){
   const title=card.querySelector('.grow b'),button=card.querySelector('button');
   if(title&&button&&overlap(rect(title),rect(button)))issues.push('category title overlaps its block/unblock button');
  }
  const actionSlot=document.querySelector('#actions,#action-slot,#screen-actions,.screen-actions');
  if(actionSlot&&visible(actionSlot)){
   if(s.bottom>rect(actionSlot).top+2)issues.push('bottom action slot overlaps scrolling content');
   for(const action of actionSlot.querySelectorAll('button')){
    if(!visible(action))continue;
    const a=rect(action);
    if(a.left<p.left-2||a.right>p.right+2||a.bottom>p.bottom+2||a.top<p.top-2)issues.push('primary action outside the app viewport');
    if(app&&a.bottom>p.bottom-safeBottom+2)issues.push('primary action under native Telegram bottom safe area');
    if(a.height<40)issues.push(`primary action too short: ${Math.round(a.height)}px`);
    if(action.scrollWidth>action.clientWidth+2)issues.push(`primary action text clipped: ${action.textContent.trim().slice(0,50)}`);
   }
  }
  if(overlay){
   const dialog=scope.querySelector('.sheet,.modal');
   if(!dialog)issues.push('missing modal/sheet');
   else{
    const d=rect(dialog);
    if(d.left<p.left-2||d.right>p.right+2||d.top<p.top-2||d.bottom>p.bottom+2)issues.push(`dialog outside shell ${JSON.stringify(d)}`);
    if(app&&(d.top<p.top+safeTop-2||d.bottom>p.bottom-safeBottom+2))issues.push('dialog overlaps native Telegram safe area');
    if(dialog.scrollWidth>dialog.clientWidth+2)issues.push(`dialog horizontal overflow ${dialog.scrollWidth}/${dialog.clientWidth}`);
    for(const button of dialog.querySelectorAll('button')){
     if(!visible(button))continue;
     const b=rect(button),x=b.left+b.width/2,y=b.top+b.height/2;
     if(y<d.top||y>d.bottom||x<d.left||x>d.right)continue;
     const hit=document.elementFromPoint(x,y);
     if(hit&&!button.contains(hit)&&hit!==button)issues.push(`overlay button obscured: ${button.textContent.trim().slice(0,40)}`);
    }
   }
  }
  if(booking){
   for(const goal of goals){
    const title=[...screen.querySelectorAll('b,h1,h2,h3')].find(e=>e.textContent.trim()===goal);
    if(!title){issues.push(`missing production booking title: ${goal.slice(0,30)}`);continue;}
    const card=title.closest('.card'),status=card?.querySelector('.pill'),next=card?.querySelector('.next-step'),button=[...(card?.querySelectorAll('button')||[])].find(e=>e.textContent.includes('Стать куратором'));
    if(!card||!status||!next||!button){issues.push('booking card lacks its status, next step or curator button');continue;}
    const c=rect(card),t=rect(title),st=rect(status),n=rect(next),b=rect(button),cs=getComputedStyle(card),inside=c.width-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);
    if(t.width<inside*.70)issues.push(`booking title squeezed to ${Math.round(t.width)}/${Math.round(inside)}px`);
    if(n.width<inside*.80)issues.push(`next step squeezed to ${Math.round(n.width)}/${Math.round(inside)}px`);
    if(overlap(t,st)||overlap(t,n)||overlap(st,n))issues.push('booking title, status and next step overlap');
    if(n.top<Math.max(t.bottom,st.bottom)-2)issues.push('next step shares the booking title/status row');
    if(b.top<n.bottom-2)issues.push('curator button overlaps booking information');
    if(b.width<inside*.85||b.height<40)issues.push(`curator action is not a usable full-width button (${Math.round(b.width)}x${Math.round(b.height)})`);
   }
  }
  return [...new Set(issues)].slice(0,12);
 },{overlay,booking,goals:LONG_GOALS});
 scenarios++;
 for(const issue of issues)failures.push({context,issue});
 if(issues.length&&failures.filter(f=>f.context===context).length===issues.length&&new Set(failures.map(f=>f.context)).size<=12){await page.screenshot({path:path.join(OUT,`failure-${mode}-${width}-${dark?'dark':'light'}-${label}.png`)});}
 return issues;
}

async function runSurface(browser,mode,widths,fixture){
 const page=await browser.newPage({viewport:{width:390,height:844},reducedMotion:'reduce'});
 page.on('pageerror',e=>pageErrors.push(`${mode}: ${e.message}`));
 await page.route('**/*',r=>r.request().url().startsWith(BASE)?r.continue():r.abort());
 await page.clock.install({time:new Date('2030-06-01T05:00:00Z')});
 if(mode!=='browser'){
  await page.addInitScript(({platform})=>{
   const callbacks={};
   const app={platform,initData:'responsive-layout-fixture',initDataUnsafe:{user:{id:111,first_name:'Мария',last_name:'Александрова'}},colorScheme:'dark',viewportStableHeight:innerHeight,viewportHeight:innerHeight,
    safeAreaInset:{top:24,bottom:20,left:0,right:0},contentSafeAreaInset:{top:56,bottom:0,left:0,right:0},
    ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){},onEvent(name,callback){(callbacks[name]||(callbacks[name]=[])).push(callback);},BackButton:{show(){},hide(){},onClick(){}},
   };
   window.Telegram={WebApp:app};
   window.__layoutViewport=()=>{app.viewportStableHeight=innerHeight;app.viewportHeight=innerHeight;for(const name of ['viewportChanged','safeAreaChanged','contentSafeAreaChanged'])for(const callback of callbacks[name]||[])callback({isStateStable:true});};
  },{platform:mode==='telegram-mobile'?'ios':'tdesktop'});
  await page.route('**/api/**',r=>r.fulfill({json:r.request().url().includes('/api/read')?{ok:true}:fixture}));
 }
 await page.goto(BASE+(mode==='browser'?'':'/?tgWebAppPlatform='+ (mode==='telegram-mobile'?'ios':'tdesktop')));
 await page.waitForFunction(()=>typeof SCREENS!=='undefined'&&cur()?.name!=='boot');
 await page.evaluate(()=>stopRealtime());
 await page.addStyleTag({content:'*,*::before,*::after{animation:none!important;transition:none!important}'});
 await page.evaluate(()=>document.fonts.ready);
 await installFixtures(page);
 for(const {width,height=844} of widths){
  await page.setViewportSize({width,height});
  await page.evaluate(()=>window.__layoutViewport?.());
  for(const dark of [true,false]){
   await page.evaluate(dark=>{$('phone').classList.toggle('dark',dark);$('overlay').innerHTML='';},dark);
   const list=[...CORE,...([390,1440].includes(width)?EXTRA:[])];
   for(const [label,prepare] of list){
    try{
     await page.evaluate(`(()=>{$('overlay').innerHTML='';(${prepare.toString()})();$('screen').scrollTop=0;document.querySelectorAll('.toast').forEach(t=>t.remove());})()`);
     await measure(page,{mode,width,height,dark,label,booking:label==='adminHub'});
     if(dark&&[390,1440].includes(width)&&['adminHub','allRequests-studio','wizard-catalog'].includes(label)){
      if(label==='adminHub')await page.locator('[data-booking-id="801"]').scrollIntoViewIfNeeded();
      await page.screenshot({path:path.join(OUT,`${mode}-${width}-${label}.png`)});
     }
    }catch(e){failures.push({context:`${mode}/${width}/${dark?'dark':'light'}/${label}`,issue:e.message.split('\n')[0]});}
   }
   for(const [label,prepare] of OVERLAYS){
    try{
     await page.evaluate(`(()=>{$('overlay').innerHTML='';(${prepare.toString()})();document.querySelectorAll('.toast').forEach(t=>t.remove());})()`);
     await measure(page,{mode,width,height,dark,label,overlay:true});
     if(dark&&width===390&&label==='cart')await page.screenshot({path:path.join(OUT,`${mode}-${width}-cart.png`)});
    }catch(e){failures.push({context:`${mode}/${width}/${dark?'dark':'light'}/${label}`,issue:e.message.split('\n')[0]});}
   }
   await page.evaluate(()=>$('overlay').innerHTML='');
  }
 }
 if(mode==='browser'){
  await page.evaluate(()=>{$('overlay').innerHTML='';role='user';resetTo('home');});
  const entry=page.locator('.action-big[onclick="startWizard()"]');
  assert.equal(await entry.getAttribute('role'),'button');
  await entry.focus();await entry.press('Enter');
  assert.equal(await page.evaluate(()=>cur().name),'wizard','Booking entry is usable with the desktop keyboard');
  scenarios++;
 }
 if(mode!=='browser'){
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(()=>{window.__layoutViewport();$('phone').classList.add('dark');role='admin';resetTo('adminReq',{id:901});$('screen').scrollTop=0;});
  const before=await page.locator('.screen-inner').evaluate(e=>e.getBoundingClientRect().top);
  await page.evaluate(()=>{Object.assign(Telegram.WebApp.contentSafeAreaInset,{top:88,bottom:12});Object.assign(Telegram.WebApp.safeAreaInset,{left:8,right:8,bottom:28});window.__layoutViewport();});
  const after=await page.locator('.screen-inner').evaluate(e=>e.getBoundingClientRect().top);
  if(after<before+30)failures.push({context:mode+'/dynamic-safe-area',issue:'contentSafeAreaChanged does not move content below the enlarged native header'});
  await measure(page,{mode,width:390,height:844,dark:true,label:'dynamic-safe-area'});
  await page.locator('#achat-inp').focus();
  await page.setViewportSize({width:390,height:500});
  await page.clock.runFor(64);
  const keyboard=await page.evaluate(()=>{
   const field=$('achat-inp').getBoundingClientRect(),screen=$('screen').getBoundingClientRect();
   return {phoneBottom:$('phone').getBoundingClientRect().bottom,viewport:visualViewport.height,screenHeight:$('screen').clientHeight,
    fieldTop:field.top,fieldBottom:field.bottom,screenTop:screen.top,screenBottom:screen.bottom};
  });
  if(keyboard.phoneBottom>keyboard.viewport+2)failures.push({context:mode+'/keyboard',issue:`app stays behind keyboard: bottom ${keyboard.phoneBottom}, visible ${keyboard.viewport}`});
  if(keyboard.screenHeight<150)failures.push({context:mode+'/keyboard',issue:`keyboard leaves only ${keyboard.screenHeight}px of content`});
  if(keyboard.fieldTop<keyboard.screenTop-2||keyboard.fieldBottom>keyboard.screenBottom+2)failures.push({context:mode+'/keyboard',issue:`focused chat field hidden after keyboard resize: ${Math.round(keyboard.fieldTop)}..${Math.round(keyboard.fieldBottom)} vs content ${Math.round(keyboard.screenTop)}..${Math.round(keyboard.screenBottom)}`});
  await measure(page,{mode,width:390,height:500,dark:true,label:'keyboard'});
  await page.screenshot({path:path.join(OUT,`${mode}-keyboard.png`)});
  // A normal viewport event must not undo the user's saved list position.
  await page.locator('#achat-inp').blur();
  await page.setViewportSize({width:390,height:700});
  await page.evaluate(()=>{window.__layoutViewport();role='admin';resetTo('adminHub');$('screen').scrollTop=350;});
  const scrollBefore=await page.locator('#screen').evaluate(e=>e.scrollTop);
  await page.evaluate(()=>window.__layoutViewport());
  await page.clock.runFor(64);
  const scrollAfter=await page.locator('#screen').evaluate(e=>e.scrollTop);
  if(scrollAfter!==scrollBefore)failures.push({context:mode+'/ordinary-scroll',issue:`viewport event changed unfocused list scroll: ${scrollBefore} -> ${scrollAfter}`});
  // The same keyboard adjustment must keep a textarea inside a scrollable sheet.
  await page.evaluate(()=>{role='user';resetTo('home');startAppeal();});
  await page.locator('#q-text').focus();
  await page.setViewportSize({width:390,height:420});
  await page.clock.runFor(64);
  const modalKeyboard=await page.evaluate(()=>{
   const field=$('q-text').getBoundingClientRect(),dialog=document.querySelector('.sheet').getBoundingClientRect();
   return {top:field.top,bottom:field.bottom,dialogTop:dialog.top,dialogBottom:dialog.bottom};
  });
  if(modalKeyboard.top<modalKeyboard.dialogTop-2||modalKeyboard.bottom>modalKeyboard.dialogBottom+2)failures.push({context:mode+'/modal-keyboard',issue:'focused appeal textarea hidden after keyboard resize'});
  await measure(page,{mode,width:390,height:420,dark:true,label:'modal-keyboard',overlay:true});
 }
 await page.close();
}

(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PW_CHANNEL?{channel:process.env.PW_CHANNEL}:{})});
 try{
  const fixturePage=await browser.newPage();
  await fixturePage.route('**/*',r=>r.request().url().startsWith(BASE)?r.continue():r.abort());
  await fixturePage.goto(BASE);
  await installFixtures(fixturePage);
  const fixture=await fixturePage.evaluate(()=>({ok:true,registered:true,verified:'ok',isAdmin:true,isSenior:true,revision:'layout-test',preferences:{startPage:'home',showPast:true},...window.__layoutFixture}));
  await fixturePage.close();
  if(process.env.LAYOUT_FOCUS==='1')await runSurface(browser,'telegram-mobile',[{width:390}],fixture);
  else{
   await runSurface(browser,'browser',[{width:320},{width:360},{width:390},{width:430},{width:768},{width:1024},{width:1440,height:900}],fixture);
   await runSurface(browser,'telegram-mobile',[{width:320},{width:390},{width:430},{width:768},{width:844,height:390}],fixture);
   await runSurface(browser,'telegram-desktop',[{width:430,height:600},{width:768,height:600},{width:1024,height:768},{width:1440,height:900}],fixture);
  }
  fs.writeFileSync(path.join(OUT,'report.json'),JSON.stringify({scenarios,pageErrors,failures},null,2));
  const summary=[...new Map(failures.map(f=>[f.issue,f])).values()];
  for(const failure of summary.slice(0,30))console.error(`${failure.context}: ${failure.issue}`);
  assert.deepEqual(pageErrors,[],'Runtime errors during responsive workflows');
  assert.equal(failures.length,0,`${failures.length} layout failures in ${scenarios} scenarios; see ${path.join(OUT,'report.json')}`);
  console.log(`Responsive layout passed: ${scenarios} screen/modal scenarios, long 626 titles, both themes, browser and Telegram mobile/desktop.`);
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
