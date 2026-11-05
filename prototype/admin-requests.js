/* Management of the normal equipment / 626 workflow. */
let allRequestKind='req',allRequestScope='active',equipmentScope='issued',equipmentSearch='',equipmentCategory='Все',appealScope='open';
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
    ${kind==='req'&&['new','curator','approved','issued','ret'].includes(o.status)?`<button class="btn-sm" onclick="startEditReq(${o.id})">${editable?'Изменить состав и детали':'Изменить состав'}</button>`:''}
    ${senior&&kind==='req'&&o.curator&&['new','curator','approved','issued','ret'].includes(o.status)?`<button class="btn-sm" onclick="adminAct(${o.id},'uncurator')">Снять куратора</button>`:''}
    ${!senior&&kind==='req'&&o.status==='new'&&myCur(o)?`<button class="btn-sm" onclick="adminAct(${o.id},'uncurator')">Снять с себя кураторство</button>`:''}
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
  const error=e.kind==='req'?equipmentDateError(e.d1,e.d2,e.t1):studioDateError(e.d1,e.t1);if(error){toast(error);return;}
  if(e.kind==='626'&&isSeniorNow()){body.goal=e.goal;body.needs=e.needs.split('\n').map(n=>n.trim()).filter(Boolean);}
  if(SRV){srvDo('booking/time',body,()=>{goBack();toast('Сохранено — нужно повторное согласование');});return;}
  const o=(e.kind==='req'?requests:bookings626).find(o=>o.id===e.id);
  if(e.kind==='req'){Object.assign(o,{d1Iso:e.d1,d2Iso:e.d2,t1:e.t1,t2:e.t2,from:fmtIso(e.d1)+', '+e.t1,to:fmtIso(e.d2)+', '+e.t2});}
  else{Object.assign(o,{when:e.d1,slot:e.t1+'–'+e.t2});if(body.goal)o.goal=body.goal;if(body.needs)o.needs=body.needs;}
  Object.assign(o,{status:'new',curator:null,curMe:false,timeChange:null,approvedBy:null,approvedAt:''});o.history.push(['new','Данные изменены — нужно повторное согласование']);goBack();
}
SCREENS.allRequests=()=>{
  if(!isAdminNow())return {body:'<div class="card sub">Раздел доступен только администраторам.</div>'};
  const studio=allRequestKind==='626',data=studio?bookings626:requests;
  const list=filterRequests(data.filter(o=>allRequestScope==='active'?!isPastBooking(o):isPastBooking(o)),'all',studio);
  return {body:`<h1 class="big">Все заявки</h1><div class="seg" role="tablist"><button class="${!studio?'on':''}" onclick="allRequestKind='req';render()">Оборудование</button><button class="${studio?'on':''}" onclick="allRequestKind='626';render()">626</button></div>
    <div class="seg" role="tablist"><button class="${allRequestScope==='active'?'on':''}" onclick="allRequestScope='active';render()">Активные</button><button class="${allRequestScope==='history'?'on':''}" onclick="allRequestScope='history';render()">Завершённые</button></div>
    ${requestFilterHtml('all',data,studio)}
    <div class="request-grid">${list.map(o=>`<div class="card tappable" onclick="navTo('${studio?'studioDetail':'adminReq'}',{id:${o.id}})"><div class="booking-card-title"><b>${studio?'626 №':'ID '}${o.id} · ${escHtml(studio?o.goal:o.event)}</b>${statusPill(o.status,studio?ST626:ST)}</div><p class="sub">${escHtml(o.author)}</p><div class="hud">${studio?fmtIso(o.when)+' · '+o.slot:o.from+' → '+o.to}</div>${nextStep(o,studio)}</div>`).join('')||'<div class="card sub">В этом разделе заявок нет.</div>'}</div>`};
};
SCREENS.equipmentState=()=>{
  if(!(SRV?SRV.isAdmin:role!=='user'))return {body:'<div class="card sub">Раздел доступен администраторам.</div>'};
  const list=requests.filter(r=>equipmentScope==='issued'?['issued','ret'].includes(r.status):r.status==='approved');
  const items=new Map();list.forEach(r=>r.items.forEach(([s,q])=>{if(!items.has(s))items.set(s,[]);items.get(s).push([r,q]);}));
  const categories=[...new Set([...items.keys()].map(s=>catOf(s)||'Другое'))].sort((a,b)=>a.localeCompare(b,'ru'));
  const query=equipmentSearch.trim().toLowerCase();
  const visible=[...items].filter(([name,rows])=>(equipmentCategory==='Все'||(catOf(name)||'Другое')===equipmentCategory)&&(!query||[name,itemOf(name)?.full,catOf(name),...rows.flatMap(([r])=>[r.id,r.author,r.curator])].join(' ').toLowerCase().includes(query)));
  return {body:`<h1 class="big">Что сейчас с оборудованием</h1><div class="seg"><button class="${equipmentScope==='issued'?'on':''}" onclick="equipmentScope='issued';render()">Выдано</button><button class="${equipmentScope==='queue'?'on':''}" onclick="equipmentScope='queue';render()">В очереди на выдачу</button></div>
    <p class="sub">${equipmentScope==='issued'?'Оборудование удерживается до приёма возврата, включая заявки с отправленными фото.':'Согласованные заявки: состав, даты и кураторы.'}</p>
    <div class="search"><input id="equipment-search" type="text" maxlength="100" placeholder="Название, категория, человек, ID заявки" value="${escAttr(equipmentSearch)}" oninput="equipmentSearch=this.value;renderKeepFocus()"></div>
    <div class="chips">${['Все',...categories].map(c=>`<button class="chip-btn ${equipmentCategory===c?'on':''}" onclick="equipmentCategory='${escJs(c)}';render()">${escHtml(c)}</button>`).join('')}</div>
    <div class="sec-label">${visible.length} позиций · ${new Set(visible.flatMap(([,rows])=>rows.map(([r])=>r.id))).size} заявок</div>
    <div class="request-grid">${visible.sort((a,b)=>a[0].localeCompare(b[0],'ru')).map(([name,rows])=>`<div class="card"><div class="booking-card-title"><b>${escHtml(name)}</b><b>× ${rows.reduce((n,[r,q])=>n+q,0)}</b></div>${rows.map(([r,q])=>`<button class="equipment-holder" onclick="navTo('adminReq',{id:${r.id}})"><span><b>ID ${r.id} · ${escHtml(r.author)}</b><span class="hud">${equipmentScope==='issued'?'Вернуть до: '+r.to:'Получение: '+r.from}</span><span class="sub">Куратор: ${escHtml(r.curator||'ещё не назначен')}${r.status==='ret'?' · ждёт приёма возврата':''}</span><span class="hud">${(r.nums?.[name]||[]).length?'Экземпляры: '+r.nums[name].join(', '):''}</span></span><b>× ${q}</b></button>`).join('')}</div>`).join('')||'<div class="card sub">Ничего не найдено. Измените поиск или категорию.</div>'}</div>`};
};

const requestFilters={};
function isPastBooking(o){return ['closed','canceled','rejected'].includes(o.status);}
function requestFilter(key){return requestFilters[key]||(requestFilters[key]={search:'',dep:'',person:'',org:'',day:'',item:'',sort:'day',expanded:false});}
function bookingDeps(o){return o.deps?.length?o.deps:o.dep?[o.dep]:[];}
function bookingItems(o,studio){return studio?(o.needs||[]):(o.items||[]).map(i=>i[0]);}
function filterRequests(data,key,studio=false){
  const f=requestFilter(key),q=f.search.trim().toLowerCase();
  const value=o=>({day:(studio?o.when:o.d1Iso)||'',person:o.author||'',dep:bookingDeps(o).join(', '),org:(o.orgs||[]).join(', '),item:bookingItems(o,studio).slice().sort().join(', '),newest:o.id})[f.sort];
  return data.filter(o=>(!f.dep||bookingDeps(o).includes(f.dep))&&(!f.person||o.author===f.person)&&(!f.org||(o.orgs||[]).includes(f.org))&&
    (!f.day||(studio?o.when===f.day:(o.d1Iso<=f.day&&o.d2Iso>=f.day)))&&(!f.item||bookingItems(o,studio).includes(f.item))&&
    (!q||[o.id,o.author,o.event,o.goal,o.curator,...bookingDeps(o),...(o.orgs||[]),...bookingItems(o,studio)].join(' ').toLowerCase().includes(q)))
    .sort((a,b)=>f.sort==='newest'?b.id-a.id:String(value(a)).localeCompare(String(value(b)),'ru')||String(studio?a.slot:a.t1).localeCompare(String(studio?b.slot:b.t1))||b.id-a.id);
}
function requestFilterHtml(key,data,studio=false){
  const f=requestFilter(key),uniq=values=>[...new Set(values.filter(Boolean))].sort((a,b)=>a.localeCompare(b,'ru'));
  const select=(field,label,values)=>`<label><span>${label}</span><select id="filter-${key}-${field}" onchange="requestFilter('${key}').${field}=this.value;render()"><option value="">Все</option>${uniq(values).map(v=>`<option value="${escAttr(v)}" ${f[field]===v?'selected':''}>${escHtml(v)}</option>`).join('')}</select></label>`;
  return `<div class="search"><input id="filter-${key}-search" type="text" maxlength="100" placeholder="ID, название, человек или оборудование" value="${escAttr(f.search)}" oninput="requestFilter('${key}').search=this.value;renderKeepFocus()"></div>
    <details class="request-filters" ${f.expanded?'open':''} ontoggle="requestFilter('${key}').expanded=this.open"><summary>Фильтры и сортировка</summary><div class="filter-grid">
      ${select('dep','Отдел',data.flatMap(bookingDeps))}${select('person','Человек',data.map(o=>o.author))}${select('org','Организация',data.flatMap(o=>o.orgs||[]))}
      ${select('item',studio?'Дополнительное оборудование':'Состав',data.flatMap(o=>bookingItems(o,studio)))}
      <label><span>День брони</span><input id="filter-${key}-day" type="date" value="${escAttr(f.day)}" onchange="requestFilter('${key}').day=this.value;render()"></label>
      <label><span>Сортировка</span><select id="filter-${key}-sort" onchange="requestFilter('${key}').sort=this.value;render()">${[['day','По дням'],['person','По людям'],['dep','По отделам'],['org','По организациям'],['item','По составу'],['newest','Сначала новые']].map(([v,l])=>`<option value="${v}" ${f.sort===v?'selected':''}>${l}</option>`).join('')}</select></label>
      <button class="btn-sm" onclick="delete requestFilters['${key}'];render()">Сбросить фильтры</button></div></details>`;
}
function approvalInfo(o){
  if(o.approvedBy)return `<div class="approval-info">Согласовал: <b>${escHtml(o.approvedBy)}</b>${o.approvedAt?`<span class="hud">${escHtml(o.approvedAt)}</span>`:''}</div>`;
  return ['approved','issued','ret','closed'].includes(o.status)&&!o.reviewPending?'<div class="sub">Согласовавший не записан в старой заявке.</div>':'';
}
function savePreferences(update){
  if(SRV){srvDo('preferences',update,()=>{render();toast('Настройка сохранена');});return;}
  Object.assign(preferences,update);try{localStorage.setItem('obor_demo_preferences',JSON.stringify(preferences));}catch(e){}render();
}
function historyToggle(){return `<button class="btn-sm history-toggle" aria-pressed="${preferences.showPast}" onclick="savePreferences({showPast:!preferences.showPast})">${preferences.showPast?'Скрыть завершённые':'Показать завершённые'}</button>`;}
function settingsEntry(){return isAdminNow()?`<div class="list-item" onclick="navTo('preferences')"><div class="emoji-badge">${uic('wrench',19)}</div><div class="grow">Стартовая страница<div class="sub">что открывать при запуске</div></div><span class="chev">›</span></div>`:'';}
function openStartPage(d){
  const page=preferences.startPage;
  const allowed=['adminHub','equipmentState','allRequests','adminCalendar','appeals'];
  if(d.isAdmin&&(allowed.includes(page)||(page==='seniorHub'&&d.isSenior))){role=page==='seniorHub'?'senior':'admin';resetTo(page);}
  else{role='user';resetTo('home');}
}
SCREENS.preferences=()=>{
  if(!isAdminNow())return {body:'<div class="card sub">Доступно администраторам.</div>'};
  const pages=[['home','Главная пользователя'],['adminHub','Панель админа'],['equipmentState','Что сейчас с оборудованием'],['allRequests','Все заявки'],['adminCalendar','Недельный календарь'],['appeals','Обращения']];
  if(isSeniorNow())pages.splice(2,0,['seniorHub','Панель старшего']);
  return {body:`<h1 class="big">Стартовая страница</h1><p class="sub">Выберите, что открывать при обычном запуске бота. Ссылка на конкретную заявку откроет её сразу.</p><div class="start-page-options">${pages.map(([id,label])=>`<button class="check-row ${preferences.startPage===id?'on':''}" aria-pressed="${preferences.startPage===id}" onclick="savePreferences({startPage:'${id}'})"><span class="checkbox" aria-hidden="true">✓</span><span class="grow">${label}</span></button>`).join('')}</div>`};
};
function appealsEntry(admin=false){
  const list=admin?appeals:appeals.filter(a=>a.me),unread=list.reduce((n,a)=>n+(a.unread||0),0),open=list.filter(a=>a.status==='open').length;
  return `<div class="list-item" onclick="navTo('appeals')"><div class="emoji-badge">${uic('q',19)}</div><div class="grow">${admin?'Обращения':'Мои обращения'}<div class="sub">${admin?open+' открыто · ответы и закрытие':'ответы команды и история'}</div></div>${unread?`<span class="unread-b">${unread}</span>`:''}<span class="chev">›</span></div>`;
}
SCREENS.appeals=()=>{
  const admin=role!=='user'&&isAdminNow(),list=(admin?appeals:appeals.filter(a=>a.me)).filter(a=>a.status===appealScope);
  return {body:`<h1 class="big">${admin?'Обращения':'Мои обращения'}</h1><div class="seg"><button class="${appealScope==='open'?'on':''}" onclick="appealScope='open';render()">Открытые</button><button class="${appealScope==='closed'?'on':''}" onclick="appealScope='closed';render()">Закрытые</button></div>
    ${list.map(a=>`<div class="card tappable" onclick="navTo('appealDetail',{id:${a.id}})"><b>№${a.id} · ${escHtml(a.author)}</b>${unreadBadge(a)}<p class="appeal-preview">${escHtml(a.text)}</p><div class="hud">${escHtml(a.createdAt)}</div></div>`).join('')||'<div class="card sub">Обращений пока нет.</div>'}`,mainbtn:!admin?mainBtn('Задать вопрос','startAppeal()'):''};
};
SCREENS.appealDetail=({id})=>{
  const a=appeals.find(a=>a.id===id),admin=role!=='user'&&isAdminNow();
  if(!a||(!admin&&!a.me))return {body:'<div class="card sub">Обращение недоступно.</div>'};
  return {body:`<h1 class="big">Обращение №${a.id}</h1><div class="card"><b>${escHtml(a.author)}</b><div class="hud">${escHtml(a.createdAt)} · ${a.status==='open'?'Открыто':'Закрыто'}</div><p class="appeal-text">${escHtml(a.text)}</p>${a.photoCount?'<p class="sub">Фото отправлены команде вместе с обращением.</p>':''}${a.closedBy?`<p class="sub">Закрыл: ${escHtml(a.closedBy)} · ${escHtml(a.closedAt)}</p>`:''}</div><div class="card"><div class="chat">${a.chat.map(m=>chatMsg(m,!a.me)).join('')||'<p class="sub">Сообщений пока нет.</p>'}</div>
    ${a.status==='open'?`<div class="row appeal-reply-row"><input type="text" id="appeal-reply" maxlength="1000" placeholder="${admin?'Ответить автору…':'Сообщение команде…'}"><button class="btn-sm primary" onclick="replyAppeal(${id})">Отправить</button></div>`:''}</div>`,mainbtn:admin?mainBtn(a.status==='open'?'Закрыть обращение':'Открыть снова',`actAppeal(${id},'${a.status==='open'?'close':'reopen'}')`,'secondary'):'',after:()=>markRead('appeal',id)};
};
function replyAppeal(id){
  const text=$('appeal-reply').value.trim();if(!text)return;
  actAppeal(id,'reply',text);
}
function actAppeal(id,action,text=''){
  if(SRV){srvDo('appeal/action',{id,action,text,asRole:role},()=>{if($('appeal-reply'))$('appeal-reply').value='';render();toast(action==='reply'?'Сообщение отправлено':'Обращение '+(action==='close'?'закрыто':'открыто'));});return;}
  const a=appeals.find(a=>a.id===id);
  if(action==='reply'){a.chat.push({who:a.me?'me':'them',text,tm:moscowTime(),label:a.me?'Пользователь':'Админ'});$('appeal-reply').value='';}
  else{a.status=action==='close'?'closed':'open';a.closedBy=action==='close'?'@you':null;a.closedAt=action==='close'?'сейчас':null;}
  render();
}
