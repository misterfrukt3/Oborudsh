/* Off-site rental. All permissions and transitions are checked by the server. */
const MT_STATUS={new:'Подана',assembling:'Собирается',ready:'Готова к выдаче',issued:'Выдана',returned:'Возвращена',rejected:'Отказ',canceled:'Отменена'};
const MT_NEEDS=['Камера (видео)','Камера (фото)','Звук','Свет (маленький)','Свет (большой)','Штатив','Стабилизатор','Другое'];
let mtDraft={needs:{},wanted:{},purpose:''}, mtTab='active';
let mtDemo={allowed:true,canManage:true,canConfigure:true,team:null,teams:[],deletedTeams:[],blocks:[],items:[],requests:[],needs:MT_NEEDS,
  settings:{testing:true,staff:[],place:'',channel:0},currentBlock:null,unsent:0};
function mtData(){return SRV?SRV.mediaTrip:mtDemo;}
function mtTime(ts){return new Intl.DateTimeFormat('ru-RU',{timeZone:'Europe/Moscow',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(ts*1000));}
function mtInputTime(ts){return new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(ts*1000)).replace(' ','T');}
function mtKind(b){return b.kind==='night'?'Ночной блок (отбой)':'Выполнение задания';}
function mtBlock(id){return mtData().blocks.find(b=>b.id===id);}
function mtCurrent(){return mtData().blocks.filter(b=>b.end>Date.now()/1000).sort((a,b)=>a.start-b.start)[0];}
function mtField(label,id,value='',type='text',extra=''){
  return `<label class="mt-field"><span>${label}</span><input id="${id}" type="${type}" value="${escAttr(String(value))}" ${extra}></label>`;
}
function mtButton(label,fn,cls='primary'){return `<button class="btn-sm ${cls}" onclick="${fn}">${label}</button>`;}
function mtGate(){const d=mtData();return d?.allowed?null:{body:'<div class="card sub">Режим пока доступен только участникам тестирования.</div>'};}
function mtNotify(text){toast(text);}
async function mtDo(body,after){
  if(_busy)return;
  _busy=true;
  try{
    if(SRV){const d=await api('media-trip',body);applyBoot(d);}
    else mtDemoDo(body);
    _busy=false;
    if(after)after();else render();
    mtNotify('Сохранено');
  }catch(e){_busy=false;toast(e.message);}
}
function mtOpenRequest(){mtDraft={needs:{},wanted:{},purpose:''};navTo('mediaTripCreate');}
function mtSummary(r){
  const b=mtBlock(r.block),expired=r.status==='issued'&&b&&b.end<Date.now()/1000;
  return `<button class="card mt-request ${expired?'mt-overdue':''}" onclick="navTo('mediaTripRequest',{id:${r.id}})">
    <div class="mt-card-head"><b>Команда ${r.team} · №${r.id}</b><span class="mt-status">${expired?'Не вернули':MT_STATUS[r.status]}</span></div>
    <div class="hud">${b?mtKind(b)+' · '+mtTime(b.start)+' — '+mtTime(b.end):'Блок не найден'}</div>
    <p class="sub">${escHtml(r.purpose)}</p></button>`;
}
SCREENS.mediaTrip=()=>{
  const gate=mtGate();if(gate)return gate;
  const d=mtData(),block=mtCurrent(),team=d.teams.find(t=>t.number===d.team),active=d.requests.filter(r=>r.team===d.team&&['new','assembling','ready','issued'].includes(r.status));
  const onBlock=active.some(r=>r.block===block?.id);
  return {body:`<h1 class="big">Медиа выезд</h1><p class="sub">Оборудование для вашей команды на время блока.</p>
    ${d.settings.testing?'<div class="mt-note">Тестирование · доступ ограничен</div>':''}
    ${d.canManage?`<div class="mt-actions">${mtButton('Панель рентала',"navTo('mediaTripRental')")}</div>`:''}
    ${d.canManage||d.canConfigure?`<div class="mt-actions">${mtButton('Настройки выезда',"navTo('mediaTripSettings')",'')}</div>`:''}
    ${team?`<div class="card"><b>Команда ${team.number}</b><p class="sub">Куратор: ${escHtml(team.members.find(m=>m.id===team.curator)?.name||String(team.curator))}</p><p class="sub">Участников: ${team.members.length}</p>${team.code?mtButton('Добавить участников',`navTo('mediaTripMembers',{number:${team.number}})`,''):''}</div>`:
      `<div class="card"><b>Присоединиться к команде</b><p class="sub">Получите код у куратора.</p>${mtField('Код команды','mt-code','','text','autocomplete="off"')}${mtButton('Вступить',"mtDo({action:'join',code:$('mt-code').value})")}</div>`}
    <div class="sec-label">${block&&block.start<Date.now()/1000?'Текущий блок':'Ближайший блок'}</div>
    ${block?`<div class="card"><b>${mtKind(block)}</b><div class="hud">${mtTime(block.start)} — ${mtTime(block.end)}</div><p class="sub">Всё оборудование нужно вернуть к концу блока.</p>
      ${team&&!onBlock?mtButton('Подать заявку','mtOpenRequest()'):onBlock?'<p class="sub">У команды уже есть активная заявка на этот блок.</p>':''}</div>`:'<div class="card sub">Расписание ещё не задано.</div>'}
    ${d.settings.place?`<div class="card"><b>Место выдачи</b><p class="sub">${escHtml(d.settings.place)}</p></div>`:''}
    <div class="sec-label">Заявки команды</div>${d.requests.filter(r=>r.team===d.team).map(mtSummary).join('')||'<div class="card sub">Заявок пока нет.</div>'}
    <details class="mt-details"><summary>Расписание выезда</summary>${d.blocks.map(b=>`<div class="card"><b>${mtKind(b)}</b><div class="hud">${mtTime(b.start)} — ${mtTime(b.end)}</div></div>`).join('')||'<p class="sub">Расписание ещё не задано.</p>'}</details>`};
};
SCREENS.mediaTripCreate=()=>{
  const gate=mtGate();if(gate)return gate;
  const d=mtData(),b=mtCurrent();
  if(!b)return {body:'<div class="card sub">Нет доступного блока.</div>'};
  return {body:`<h1 class="big">Что нужно команде?</h1><div class="hud">${mtKind(b)} · ${mtTime(b.start)} — ${mtTime(b.end)}</div>
    <p class="sub">Выберите, что хотите снимать. Команда рентала подберёт оборудование.</p>
    <div class="mt-needs">${d.needs.map((n,i)=>`<div class="mt-need"><button id="mt-need-choice-${i}" class="mt-need-choice ${mtDraft.needs[n]?'on':''}" aria-pressed="${!!mtDraft.needs[n]}" onclick="mtNeedToggle(${i})">${escHtml(n)}</button><input id="mt-need-qty-${i}" aria-label="${escAttr(n)}: количество" type="number" min="0" max="99" value="${mtDraft.needs[n]||0}" oninput="mtNeedChange(${i},this.value)"></div>`).join('')}</div>
    <div class="sec-label">Для чего нужна оборудка?</div><textarea id="mt-purpose" maxlength="2000" rows="4" placeholder="Например: снимаем интервью на улице, нужны камера, звук и небольшой свет" oninput="mtDraft.purpose=this.value">${escHtml(mtDraft.purpose)}</textarea>
    <details class="mt-details"><summary>Выбрать оборудование из списка</summary><p class="sub">Необязательно. Это пожелания — итоговый состав подберёт рентал.</p>${mtItemInputs('wanted',mtDraft.wanted)}${!d.items.length?'<p class="sub">Каталог выезда ещё не заполнен.</p>':''}</details>`,
    mainbtn:mainBtn('Отправить заявку',`mtSubmit(${b.id})`)};
};
function mtNeedChange(i,value){const n=mtData().needs[i];mtDraft.needs[n]=Number(value);const b=$('mt-need-choice-'+i);b.classList.toggle('on',Number(value)>0);b.setAttribute('aria-pressed',String(Number(value)>0));}
function mtNeedToggle(i){const q=$('mt-need-qty-'+i);q.value=Number(q.value)>0?0:1;mtNeedChange(i,q.value);}
function mtItemInputs(prefix,values){return mtData().items.filter(i=>i.active).map(i=>`<label class="mt-need"><span>${escHtml(i.name)}<small>Всего: ${i.total}</small></span><input id="mt-${prefix}-${i.id}" aria-label="${escAttr(i.name)}: количество" type="number" min="0" max="${i.total}" value="${values[i.id]||0}" ${prefix==='wanted'?`oninput="mtDraft.wanted[${i.id}]=Number(this.value)"`:''}></label>`).join('');}
function mtReadKit(prefix){return mtData().items.filter(i=>i.active).map(i=>[i.id,Number($('mt-'+prefix+'-'+i.id)?.value||0)]).filter(x=>x[1]>0);}
function mtSubmit(block){const needs=Object.fromEntries(Object.entries(mtDraft.needs).filter(x=>x[1]>0));mtDo({action:'create',block,needs,wanted:mtReadKit('wanted'),purpose:$('mt-purpose').value},()=>{mtDraft={needs:{},wanted:{},purpose:''};goBack();});}
SCREENS.mediaTripRental=()=>{
  const gate=mtGate();if(gate)return gate;
  const d=mtData();if(!d.canManage)return {body:'<div class="card sub">Панель доступна команде рентала.</div>'};
  const reqs=d.requests.filter(r=>mtTab==='history'?!['new','assembling','ready','issued'].includes(r.status):mtTab==='overdue'?r.status==='issued'&&mtBlock(r.block)?.end<Date.now()/1000:['new','assembling','ready','issued'].includes(r.status));
  return {body:`<h1 class="big">Рентал выезда</h1><div class="mt-actions">${mtButton('Команды',"navTo('mediaTripTeams')",'')}${mtButton('Расписание',"navTo('mediaTripBlocks')",'')}${mtButton('Каталог выезда',"navTo('mediaTripCatalog')",'')}${mtButton('Настройки',"navTo('mediaTripSettings')",'')}</div>
    ${!d.settings.channel?'<div class="mt-note">Укажите канал выезда в настройках для уведомлений ренталу.</div>':''}
    ${d.unsent?`<p class="sub">Ожидают доставки уведомлений: ${d.unsent}. Бот повторяет отправку при ошибке.</p>`:''}
    <div class="seg">${[['active','В работе'],['overdue','Не вернули'],['history','История']].map(([v,l])=>`<button class="${mtTab===v?'on':''}" onclick="mtTab='${v}';render()">${l}</button>`).join('')}</div>
    ${reqs.map(mtSummary).join('')||'<div class="card sub">В этой очереди пусто.</div>'}`};
};
SCREENS.mediaTripRequest=({id})=>{
  const gate=mtGate();if(gate)return gate;
  const d=mtData(),r=d.requests.find(r=>r.id===id);if(!r)return {body:'<div class="card sub">Заявка не найдена.</div>'};
  const b=mtBlock(r.block),own=d.team===r.team;
  let actions='';
  if(d.canManage){
    if(r.status==='new')actions+=mtButton('Принять и начать сборку',`mtAct(${id},'assembling')`);
    if(r.status==='assembling')actions+=mtButton('Сохранить состав',`mtAct(${id},'kit')`,'')+mtButton('Готова к выдаче',`mtAct(${id},'ready')`);
    if(r.status==='ready')actions+=mtButton('Отметить: выдана',`mtConfirmAct(${id},'issued','Выдать оборудование?','Подтвердите, что команда получила весь указанный состав.')`);
    if(r.status==='issued')actions+=mtButton('Отметить: всё вернули',`mtConfirmAct(${id},'returned','Принять возврат?','Подтвердите, что команда вернула всё оборудование.')`);
    if(['new','assembling','ready'].includes(r.status))actions+=mtButton('Отказать с причиной',`mtReject(${id})`,'danger');
  }
  if(own&&['new','assembling','ready'].includes(r.status))actions+=mtButton('Отменить заявку',`mtConfirmAct(${id},'canceled','Отменить заявку?','Оборудование будет освобождено для других команд.')`,'danger');
  const kitText=values=>values.map(([i,q])=>`<div class="mt-kit-line">${escHtml(d.items.find(x=>x.id===i)?.name||'Позиция №'+i)}<b>× ${q}</b></div>`).join('')||'<p class="sub">Состав пока не выбран.</p>';
  return {body:`<h1 class="big">Команда ${r.team} · заявка №${id}</h1><span class="mt-status">${MT_STATUS[r.status]}</span>
    <div class="card"><b>${b?mtKind(b):'Блок'}</b><div class="hud">${b?mtTime(b.start)+' — '+mtTime(b.end):''}</div></div>
    <div class="sec-label">Потребности команды</div><div class="card">${Object.entries(r.needs).map(([n,q])=>`<div class="mt-kit-line">${escHtml(n)}<b>× ${q}</b></div>`).join('')}<p class="mt-purpose">${escHtml(r.purpose)}</p></div>
    ${r.wanted.length?`<details class="mt-details"><summary>Пожелания из каталога</summary>${kitText(r.wanted)}</details>`:''}
    <div class="sec-label">${r.status==='assembling'&&d.canManage?'Собираем для команды':'Состав выдачи'}</div>
    <div class="card">${r.status==='assembling'&&d.canManage?mtItemInputs('kit',Object.fromEntries(r.kit)):kitText(r.kit)}</div>
    ${r.status==='ready'?`<div class="mt-note">Подойдите за оборудованием: ${escHtml(d.settings.place)}.</div>`:''}
    ${r.reason?`<div class="card sub">Причина: ${escHtml(r.reason)}</div>`:''}
    <div class="mt-actions">${actions}</div><details class="mt-details"><summary>История</summary>${(r.history||[]).map(h=>`<div class="hud">${mtTime(h.stamp)} · ${MT_STATUS[h.status]} · ID ${h.uid}</div>`).join('')}</details>`};
};
function mtAct(id,status){const body={action:'request',id,status};if(status==='kit'||status==='ready')body.kit=mtReadKit('kit');mtDo(body);}
function mtConfirmAct(id,status,title,text){confirmModal(title,text,()=>mtDo({action:'request',id,status}));}
function mtReject(id){$('overlay').innerHTML=`<div class="modal-veil"><div class="modal"><h3>Отказать с причиной</h3><textarea id="mt-reason" rows="3" maxlength="500" placeholder="Почему не можем выдать оборудование?"></textarea><div class="mt-actions">${mtButton('Отмена',"$('overlay').innerHTML=''",'')}${mtButton('Отказать',`mtDo({action:'request',id:${id},status:'rejected',reason:$('mt-reason').value},()=>{$('overlay').innerHTML='';render()})`,'danger')}</div></div></div>`;}
SCREENS.mediaTripSettings=()=>{
  const gate=mtGate();if(gate)return gate;
  const d=mtData();if(!d.canManage&&!d.canConfigure)return {body:'<div class="card sub">Недостаточно прав.</div>'};
  const s=d.settings;
  return {body:`<h1 class="big">Настройки выезда</h1><p class="sub">Расписание и сроки — по московскому времени.</p>
    <label class="mt-check"><input id="mt-testing" type="checkbox" ${s.testing?'checked':''}> Только тестировщики</label><p class="sub">После отключения участники смогут вступать по коду команды. Панель рентала будет доступна только назначенным сотрудникам.</p>
    ${mtField('Команда рентала: ID или @username через запятую','mt-staff',(s.staff||[]).join(', '))}<p class="sub">По @username можно добавить тех, кто уже открывал бота. По Telegram ID — заранее.</p>
    ${mtField('ID отдельного канала выезда','mt-channel',s.channel||'','text','inputmode="numeric" placeholder="-100…"')}<p class="sub">Добавьте бота администратором канала с правом отправки сообщений. Участники должны запустить бота для личных напоминаний.</p>
    ${mtField('Фиксированное место выдачи','mt-place',s.place,'text','maxlength="300"')}`,
    mainbtn:mainBtn('Сохранить настройки',"mtDo({action:'settings',testing:$('mt-testing').checked,staff:$('mt-staff').value,channel:$('mt-channel').value||0,place:$('mt-place').value})")};
};
SCREENS.mediaTripTeams=()=>{
  const d=mtData();if(!d?.canManage)return {body:'<div class="card sub">Недостаточно прав.</div>'};
  return {body:`<h1 class="big">Команды выезда</h1>${d.teams.map(t=>`<div class="card"><b>Команда ${t.number}</b><p class="sub">Куратор: ${escHtml(t.members.find(m=>m.id===t.curator)?.name||String(t.curator))}</p><div class="mt-actions">${mtButton('Участники и код',`navTo('mediaTripMembers',{number:${t.number}})`,'')}${mtButton('Сменить куратора',`$('mt-team-number').value=${t.number};$('mt-curator').value=${t.curator}`,'')}${mtButton('Удалить команду',`mtDeleteTeam(${t.number})`,'danger')}</div></div>`).join('')}
    <div class="sec-label">Добавить / изменить команду</div>${mtField('Номер команды','mt-team-number','','number','min="1" max="999"')}${mtField('Telegram ID или @username куратора','mt-curator')}`,
    mainbtn:mainBtn('Сохранить команду',"mtDo({action:'team',number:$('mt-team-number').value,curator:$('mt-curator').value})")};
};
function mtDeleteTeam(number){
  if(!mtData()?.canManage)return;
  const history=mtData().requests.some(r=>r.team===number)?' История заявок сохранится; её номер останется занят.':'';
  confirmModal(`Удалить команду ${number}?`,'Участники смогут вступить в другую команду.'+history+' Команду с активными заявками можно удалить после их отмены или возврата оборудования.',()=>mtDo({action:'delete_team',number}));
}
SCREENS.mediaTripMembers=({number})=>{
  const d=mtData(),t=d?.teams?.find(t=>t.number===number);
  if(!t||!t.code)return {body:'<div class="card sub">Недостаточно прав.</div>'};
  return {body:`<h1 class="big">Команда ${number}</h1><div class="card"><b>Код вступления</b><div class="mt-code">${escHtml(t.code)}</div><p class="sub">Участник открывает «Медиа выезд» и вводит этот код.</p></div>
    ${t.members.map(m=>`<div class="mt-member"><span>${escHtml(m.name)}<small>ID ${m.id}${m.id===t.curator?' · куратор':''}</small></span>${m.id!==t.curator?mtButton('Убрать',`mtDo({action:'members',number:${number},remove:${m.id}})`,'danger'):''}</div>`).join('')}
    ${mtField('Добавить участников: ID или @username через запятую','mt-members')}`,
    mainbtn:mainBtn('Добавить участников',`mtDo({action:'members',number:${number},members:$('mt-members').value})`)};
};
SCREENS.mediaTripBlocks=()=>{
  const d=mtData();if(!d?.canManage)return {body:'<div class="card sub">Недостаточно прав.</div>'};
  return {body:`<h1 class="big">Расписание блоков</h1><p class="sub">Московское время. Для ночного блока задайте конец на нужный день — это срок возврата.</p>
    ${d.blocks.map(b=>`<div class="card"><b>${mtKind(b)}</b><div class="hud">${mtTime(b.start)} — ${mtTime(b.end)}</div>${mtButton('Изменить',`mtEditBlock(${b.id})`,'')}</div>`).join('')}
    <input type="hidden" id="mt-block-id" value="0"><label class="mt-field"><span>Тип блока</span><select id="mt-kind"><option value="task">Выполнение задания</option><option value="night">Ночной блок (отбой)</option></select></label>
    ${mtField('Начало','mt-start','','datetime-local')}${mtField('Конец / срок возврата','mt-end','','datetime-local')}<div class="mt-actions">${mtButton('Новый блок',"$('mt-block-id').value=0;$('mt-start').value='';$('mt-end').value=''",'')}</div>`,
    mainbtn:mainBtn('Сохранить блок',"mtDo({action:'block',id:$('mt-block-id').value,kind:$('mt-kind').value,start:$('mt-start').value,end:$('mt-end').value})")};
};
function mtEditBlock(id){const b=mtBlock(id);$('mt-block-id').value=id;$('mt-kind').value=b.kind;$('mt-start').value=mtInputTime(b.start);$('mt-end').value=mtInputTime(b.end);$('mt-kind').scrollIntoView({block:'center',behavior:'smooth'});}
SCREENS.mediaTripCatalog=()=>{
  const d=mtData();if(!d?.canManage)return {body:'<div class="card sub">Недостаточно прав.</div>'};
  return {body:`<h1 class="big">Каталог выезда</h1><p class="sub">Отдельный список оборудования, которое взяли с собой.</p>
    ${d.items.map(i=>`<div class="card mt-card-head"><div><b>${escHtml(i.name)}</b><div class="hud">${i.total} шт. ${i.active?'':'· скрыто'}</div></div>${mtButton('Изменить',`mtEditItem(${i.id})`,'')}</div>`).join('')}
    <input id="mt-item-id" type="hidden" value="0">${mtField('Название','mt-item-name','','text','maxlength="200"')}${mtField('Количество','mt-total',1,'number','min="1" max="999"')}
    <label class="mt-check"><input id="mt-item-active" type="checkbox" checked> Показывать в каталоге</label><div class="mt-actions">${mtButton('Новая позиция',"$('mt-item-id').value=0;$('mt-item-name').value='';$('mt-total').value=1;$('mt-item-active').checked=true",'')}</div>`,
    mainbtn:mainBtn('Сохранить позицию',"mtDo({action:'item',id:$('mt-item-id').value,name:$('mt-item-name').value,total:$('mt-total').value,active:$('mt-item-active').checked})")};
};
function mtEditItem(id){const i=mtData().items.find(i=>i.id===id);$('mt-item-id').value=id;$('mt-item-name').value=i.name;$('mt-total').value=i.total;$('mt-item-active').checked=!!i.active;$('mt-item-name').focus();}
function mtDemoDo(b){
  const d=mtDemo,nextId=list=>Math.max(0,...list.map(x=>x.id||0))+1;
  if(b.action==='settings'){d.settings={...b,staff:String(b.staff).split(/[ ,]+/).filter(Boolean),channel:Number(b.channel)};}
  else if(b.action==='team'){const number=Number(b.number),curator=Number(b.curator);if(!number||!curator)throw Error('Укажите номер команды и Telegram ID куратора.');if(d.deletedTeams.includes(number))throw Error('Номер удалённой команды сохранён в истории. Выберите другой номер.');let t=d.teams.find(t=>t.number===number);if(t)t.curator=curator;else d.teams.push({number,curator,code:'demo-'+number+'-'+crypto.randomUUID(),members:[{id:curator,name:'Куратор'}]});}
  else if(b.action==='delete_team'){
    if(!d.canManage)throw Error('Доступно только команде рентала.');
    const number=Number(b.number);
    if(!d.teams.some(t=>t.number===number))throw Error('Команда не найдена.');
    if(d.requests.some(r=>r.team===number&&['new','assembling','ready','issued'].includes(r.status)))throw Error('У команды есть активные заявки. Сначала отмените их или примите возврат оборудования.');
    if(d.requests.some(r=>r.team===number))d.deletedTeams.push(number);
    d.teams=d.teams.filter(t=>t.number!==number);
    if(d.team===number)d.team=null;
  }
  else if(b.action==='members'){const t=d.teams.find(t=>t.number===b.number);if(b.remove)t.members=t.members.filter(m=>m.id!==b.remove);else String(b.members).split(/[ ,]+/).filter(Boolean).forEach(id=>{if(!t.members.some(m=>m.id===Number(id)))t.members.push({id:Number(id),name:'Участник '+id});});}
  else if(b.action==='join'){const t=d.teams.find(t=>t.code===b.code);if(!t)throw Error('Неверный код команды.');d.team=t.number;}
  else if(b.action==='block'){const start=Date.parse(b.start+':00+03:00')/1000,end=Date.parse(b.end+':00+03:00')/1000;if(!start||end<=start)throw Error('Проверьте начало и конец блока.');const v={id:Number(b.id)||nextId(d.blocks),kind:b.kind,start,end};const old=d.blocks.find(x=>x.id===v.id);if(old)Object.assign(old,v);else d.blocks.push(v);}
  else if(b.action==='item'){if(!b.name||Number(b.total)<1)throw Error('Укажите название и количество.');const v={id:Number(b.id)||nextId(d.items),name:b.name,total:Number(b.total),active:b.active===false?0:1},old=d.items.find(i=>i.id===v.id);if(old)Object.assign(old,v);else d.items.push(v);}
  else if(b.action==='create'){if(!d.team)throw Error('Сначала вступите в команду.');if(!b.purpose.trim()||(!Object.keys(b.needs).length&&!b.wanted.length))throw Error('Опишите задачу и выберите потребности.');if(d.requests.some(r=>r.team===d.team&&r.block===b.block&&['new','assembling','ready','issued'].includes(r.status)))throw Error('У команды уже есть активная заявка.');d.requests.unshift({id:nextId(d.requests),team:d.team,block:b.block,needs:b.needs,wanted:b.wanted,purpose:b.purpose,status:'new',kit:[],history:[]});}
  else if(b.action==='request'){const r=d.requests.find(r=>r.id===b.id);if(b.kit)r.kit=b.kit;if(b.status==='ready'&&!r.kit.length)throw Error('Добавьте оборудование в состав выдачи.');if(b.status==='ready'&&!d.settings.place)throw Error('Сначала укажите место выдачи.');if(b.status==='rejected'&&!b.reason?.trim())throw Error('Укажите причину отказа.');if(b.status!=='kit'){r.status=b.status;r.reason=b.reason||'';r.history.push({uid:0,status:b.status,stamp:Date.now()/1000});}}
}
