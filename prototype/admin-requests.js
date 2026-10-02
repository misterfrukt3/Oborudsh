/* Management of the normal equipment / 626 workflow. */
let allRequestKind='req',allRequestScope='active',allRequestSearch='',equipmentScope='issued';
let timeEdit={kind:'req',id:0,d1:'',d2:'',t1:'',t2:''};
function timeChangeBanner(kind,o){
  if(!o.timeChange||!['new','curator','approved'].includes(o.status))return '';
  return `<div class="kit-warn"><b>Нужно изменить время</b><p class="sub">${escHtml(o.timeChange.reason)}</p>
    ${o.me||isSeniorNow()?`<button class="btn-sm primary" onclick="openBookingTime('${kind}',${o.id})">Изменить время</button>`:'<p class="sub">Ожидаем изменения от заявителя. Затем согласуем заново.</p>'}</div>`;
}
function bookingAdminControls(kind,o){
  if(!(SRV?SRV.isAdmin:role!=='user'))return '';
  const senior=isSeniorNow(),editable=['new','curator','approved'].includes(o.status);
  return `<div class="booking-admin-actions">
    ${editable&&(kind==='req'||senior||myCur(o))?`<button class="btn-sm" onclick="requestBookingTime('${kind}',${o.id})">Попросить изменить время</button>`:''}
    ${senior&&editable?`<button class="btn-sm" onclick="openBookingTime('${kind}',${o.id})">Изменить ${kind==='req'?'даты и время':'бронь 626'}</button>`:''}
    ${senior&&editable&&kind==='req'?`<button class="btn-sm" onclick="startEditReq(${o.id})">Изменить состав и детали</button>`:''}
    ${senior&&kind==='req'&&!o.curator&&o.status==='approved'&&!o.timeChange?`<button class="btn-sm" onclick="adminAct(${o.id},'curator')">Стать куратором</button>`:''}
    ${senior&&kind==='req'&&o.curator&&['curator','approved','issued','ret'].includes(o.status)?`<button class="btn-sm" onclick="adminAct(${o.id},'uncurator')">Снять куратора</button>`:''}
    ${senior&&kind==='626'&&o.status==='new'?`<button class="btn-sm ok" ${o.timeChange?'disabled':''} onclick="dec626(${o.id},'approved')">Согласовать бронь</button><button class="btn-sm danger" onclick="rej626Modal(${o.id})">Отклонить с причиной</button>`:''}
  </div>`;
}
function requestBookingTime(kind,id){
  $('overlay').innerHTML=`<div class="modal-veil"><div class="modal"><h3>Попросить изменить время</h3><p class="sub">Укажите, что нужно поменять. Пользователю придёт просьба с кнопкой открытия заявки.</p>
    <textarea id="change-time-reason" rows="3" maxlength="500" placeholder="Например: перенесите получение на 15:30 — до этого времени рентал закрыт"></textarea>
    <div class="acts"><button class="btn-sm" onclick="$('overlay').innerHTML=''">Отмена</button><button class="btn-sm primary" onclick="sendTimeRequest('${kind}',${id})">Отправить просьбу</button></div></div></div>`;
}
function sendTimeRequest(kind,id){
  const reason=$('change-time-reason').value.trim();if(!reason){toast('Напишите, что нужно поменять');return;}
  if(SRV){srvDo('booking/request-time',{kind,id,reason},()=>{$('overlay').innerHTML='';render();toast('Просьба доставлена пользователю');});return;}
  const o=(kind==='req'?requests:bookings626).find(o=>o.id===id);o.timeChange={reason};$('overlay').innerHTML='';render();toast('Просьба отправлена (демо)');
}
function openBookingTime(kind,id){
  const o=(kind==='req'?requests:bookings626).find(o=>o.id===id);if(!o)return;
  const times=kind==='626'?o.slot.split(/[–—-]/).map(s=>s.trim()):[o.t1,o.t2];
  timeEdit={kind,id,d1:kind==='req'?o.d1Iso:o.when,d2:kind==='req'?o.d2Iso:o.when,t1:times[0],t2:times[1],goal:o.goal,needs:(o.needs||[]).join('\n')};
  navTo('bookingTime');
}
SCREENS.bookingTime=()=>{
  const e=timeEdit,o=(e.kind==='req'?requests:bookings626).find(o=>o.id===e.id);
  if(!o||(!o.me&&!isSeniorNow()))return {body:'<div class="card sub">Недостаточно прав.</div>'};
  return {body:`<h1 class="big">${e.kind==='req'?'Изменить время заявки':'Изменить бронь 626'}</h1>
    <p class="sub">После сохранения понадобится повторное согласование и назначение куратора.</p>
    ${o.timeChange?`<div class="kit-warn">${escHtml(o.timeChange.reason)}</div>`:''}
    <label class="booking-date"><span>${e.kind==='req'?'Дата получения':'Дата брони'}</span><input id="edit-date-from" type="date" value="${escAttr(e.d1)}" onchange="timeEdit.d1=this.value;${e.kind==='626'?'timeEdit.d2=this.value;':''}"></label>
    ${e.kind==='req'?`<label class="booking-date"><span>Дата возврата</span><input id="edit-date-to" type="date" value="${escAttr(e.d2)}" onchange="timeEdit.d2=this.value"></label>`:''}
    ${timePickerHtml({title:'Московское время',fromId:'time-edit-from',fromLabel:e.kind==='req'?'Получение':'Начало',fromValue:e.t1,fromTarget:'timeEdit.t1',toId:'time-edit-to',toLabel:e.kind==='req'?'Возврат':'Конец',toValue:e.t2,toTarget:'timeEdit.t2'})}
    ${e.kind==='626'&&isSeniorNow()?`<div class="sec-label">Цель брони</div><textarea id="edit626-goal" maxlength="100" rows="3" oninput="timeEdit.goal=this.value">${escHtml(e.goal||'')}</textarea><div class="sec-label">Дополнительное оборудование · по одной строке</div><textarea id="edit626-needs" rows="3" maxlength="2000" oninput="timeEdit.needs=this.value">${escHtml(e.needs)}</textarea>`:''}`,
    mainbtn:mainBtn('Сохранить и отправить на согласование','saveBookingTime()')};
};
function saveBookingTime(){
  const e=timeEdit,body={kind:e.kind,id:e.id,d1:e.d1,d2:e.d2,t1:e.t1,t2:e.t2};
  if(e.kind==='626'&&isSeniorNow()){body.goal=e.goal;body.needs=e.needs.split('\n').map(n=>n.trim()).filter(Boolean);}
  if(SRV){srvDo('booking/time',body,()=>{goBack();toast('Сохранено — нужно повторное согласование');});return;}
  const o=(e.kind==='req'?requests:bookings626).find(o=>o.id===e.id);
  if(e.kind==='req'){Object.assign(o,{d1Iso:e.d1,d2Iso:e.d2,t1:e.t1,t2:e.t2,from:fmtIso(e.d1)+', '+e.t1,to:fmtIso(e.d2)+', '+e.t2});}
  else{Object.assign(o,{when:e.d1,slot:e.t1+'–'+e.t2});if(body.goal)o.goal=body.goal;if(body.needs)o.needs=body.needs;}
  Object.assign(o,{status:'new',curator:null,curMe:false,timeChange:null});o.history.push(['new','Данные изменены — нужно повторное согласование']);goBack();
}
SCREENS.allRequests=()=>{
  if(!isSeniorNow())return {body:'<div class="card sub">Раздел доступен только старшим.</div>'};
  const studio=allRequestKind==='626',data=studio?bookings626:requests,q=allRequestSearch.toLowerCase();
  const list=data.filter(o=>(allRequestScope==='active'?!['closed','canceled','rejected'].includes(o.status):['closed','canceled','rejected'].includes(o.status))&&(!q||[o.id,o.author,studio?o.goal:o.event,o.curator||''].join(' ').toLowerCase().includes(q)));
  return {body:`<h1 class="big">Все заявки</h1><div class="seg" role="tablist"><button class="${!studio?'on':''}" onclick="allRequestKind='req';render()">Оборудование</button><button class="${studio?'on':''}" onclick="allRequestKind='626';render()">626</button></div>
    <div class="seg" role="tablist"><button class="${allRequestScope==='active'?'on':''}" onclick="allRequestScope='active';render()">Активные</button><button class="${allRequestScope==='history'?'on':''}" onclick="allRequestScope='history';render()">Завершённые</button></div>
    <div class="search"><input id="all-request-search" type="text" placeholder="ID, мероприятие, имя или куратор" value="${escAttr(allRequestSearch)}" oninput="allRequestSearch=this.value;renderKeepFocus()"></div>
    ${list.map(o=>`<div class="card tappable" onclick="navTo('${studio?'studioDetail':'adminReq'}',{id:${o.id}})"><div class="booking-card-title"><b>${studio?'626 №':'ID '}${o.id} · ${escHtml(studio?o.goal:o.event)}</b>${statusPill(o.status,studio?ST626:ST)}</div><p class="sub">${escHtml(o.author)}</p><div class="hud">${studio?fmtIso(o.when)+' · '+o.slot:o.from+' → '+o.to}</div>${nextStep(o,studio)}</div>`).join('')||'<div class="card sub">В этом разделе заявок нет.</div>'}`};
};
SCREENS.equipmentState=()=>{
  if(!(SRV?SRV.isAdmin:role!=='user'))return {body:'<div class="card sub">Раздел доступен администраторам.</div>'};
  const list=requests.filter(r=>equipmentScope==='issued'?['issued','ret'].includes(r.status):r.status==='approved');
  const items=new Map();list.forEach(r=>r.items.forEach(([s,q])=>{if(!items.has(s))items.set(s,[]);items.get(s).push([r,q]);}));
  return {body:`<h1 class="big">Что сейчас с оборудованием</h1><div class="seg"><button class="${equipmentScope==='issued'?'on':''}" onclick="equipmentScope='issued';render()">Выдано</button><button class="${equipmentScope==='queue'?'on':''}" onclick="equipmentScope='queue';render()">В очереди на выдачу</button></div>
    <p class="sub">${equipmentScope==='issued'?'Оборудование удерживается до приёма возврата, включая заявки с отправленными фото.':'Согласованные заявки: состав, даты и кураторы.'}</p>
    <div class="sec-label">${items.size} позиций · ${list.length} заявок</div>
    ${[...items].sort((a,b)=>a[0].localeCompare(b[0],'ru')).map(([name,rows])=>`<div class="card"><div class="booking-card-title"><b>${escHtml(name)}</b><b>× ${rows.reduce((n,[r,q])=>n+q,0)}</b></div>${rows.map(([r,q])=>`<button class="equipment-holder" onclick="navTo('adminReq',{id:${r.id}})"><span><b>ID ${r.id} · ${escHtml(r.author)}</b><span class="hud">${equipmentScope==='issued'?'Вернуть до: '+r.to:'Получение: '+r.from}</span><span class="sub">Куратор: ${escHtml(r.curator||'ещё не назначен')}${r.status==='ret'?' · ждёт приёма возврата':''}</span><span class="hud">${(r.nums?.[name]||[]).length?'Экземпляры: '+r.nums[name].join(', '):''}</span></span><b>× ${q}</b></button>`).join('')}</div>`).join('')||'<div class="card sub">Оборудования в этом разделе нет.</div>'}`};
};
