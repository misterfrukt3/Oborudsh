const {chromium}=require('playwright');const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const page=await browser.newPage({viewport:{width:390,height:844},reducedMotion:'reduce'});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',r=>r.request().url().startsWith('http://127.0.0.1:8745')?r.continue():r.abort());
 await page.goto('http://127.0.0.1:8745');
 await page.evaluate(()=>{role='admin';resetTo('adminReq',{id:requests.find(r=>r.status==='new').id});});
 assert.equal(await page.getByRole('button',{name:'Стать куратором',exact:true}).count(),0);
 await page.getByRole('button',{name:'Согласовать заявку',exact:true}).click();
 await page.getByRole('button',{name:'Стать куратором',exact:true}).click();
 assert.equal(await page.evaluate(()=>requests.find(r=>r.id===stack.at(-1).params.id).status),'approved');
 await page.getByRole('button',{name:'Попросить изменить время',exact:true}).click();
 await page.locator('#change-time-reason').fill('Перенесите получение на 15:00');
 await page.getByRole('button',{name:'Отправить просьбу',exact:true}).click();
 assert.match(await page.locator('#screen').innerText(),/Ожидаем изменения времени/);
 await page.evaluate(()=>{const id=stack.at(-1).params.id;requests.find(r=>r.id===id).me=true;role='user';resetTo('reqDetail',{id});});
  await page.getByRole('button',{name:'Изменить время',exact:true}).click();
 await page.locator('#edit-date-from').fill('2030-06-02');
 await page.locator('#edit-date-to').fill('2030-06-02');
 await page.getByRole('textbox',{name:'Получение: часы'}).fill('15');
 await page.getByRole('textbox',{name:'Получение: минуты'}).fill('00');
 await page.getByRole('textbox',{name:'Возврат: часы'}).fill('18');
 await page.getByRole('textbox',{name:'Возврат: минуты'}).fill('00');
 await page.getByRole('button',{name:'Сохранить и отправить на согласование'}).click();
 assert.equal(await page.evaluate(()=>requests.find(r=>r.id===stack.at(-1).params.id).status),'new');
 await page.evaluate(()=>{role='senior';resetTo('seniorHub');});
 await page.locator('.list-item').filter({hasText:'Все заявки'}).click();
 assert.equal(await page.locator('.tappable').count()>0,true);
 await page.getByRole('button',{name:'Завершённые',exact:true}).click();
 assert.match(await page.locator('#screen').innerText(),/Закрыта/);
 await page.getByRole('button',{name:'626',exact:true}).click();
 await page.getByRole('button',{name:'Активные',exact:true}).click();
 await page.locator('.tappable').first().click();
 await page.getByRole('button',{name:'Изменить бронь 626',exact:true}).click();
 assert.equal(await page.locator('#edit626-goal').count(),1);
 for(const width of [320,390,430]){
  await page.setViewportSize({width,height:844});
  for(const name of ['allRequests','equipmentState','bookingTime']){
   await page.evaluate(name=>resetTo(name),name);
   assert.equal(await page.evaluate(()=>document.querySelector('#screen').scrollWidth<=document.querySelector('#screen').clientWidth),true,`${name}: overflow ${width}`);
  }
 }
 await page.evaluate(()=>{role='senior';equipmentScope='issued';resetTo('equipmentState');});
 const issuedId=await page.evaluate(()=>requests.find(r=>['issued','ret'].includes(r.status)).id);
 assert.match(await page.locator('#screen').innerText(),new RegExp(`ID ${issuedId}`));
 await page.getByRole('button',{name:'В очереди на выдачу',exact:true}).click();
 await page.evaluate(()=>{role='user';resetTo('allRequests');});
 assert.match(await page.locator('#screen').innerText(),/только старшим/);
 await page.evaluate(()=>{role='senior';openStats();});
 assert.match(await page.locator('#screen').innerText(),/Согласовал:/);
 assert.deepEqual(errors,[]);await browser.close();console.log('Admin requests browser workflow, time changes, equipment state and layouts passed.');
})().catch(e=>{console.error(e);process.exit(1)});
