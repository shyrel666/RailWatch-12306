// Offline synthetic controls following the saved 2026-10-10 public form and
// order templates. Used on multi-alternate.html; never calls railway services.
document.head.insertAdjacentHTML('beforeend', '<style>.sel-list{display:none}.sel.active .sel-list{display:block}.sel{display:inline-block;margin:4px}</style>');
document.getElementById('form').insertAdjacentHTML('beforeend', '<div id="contact_train_time_content"></div>');
document.body.insertAdjacentHTML('beforeend', '<div class="dzp-confirm hidden" id="new-dialog"><div class="modal"><div class="modal-tit"></div><a class="modal-close">关闭</a><div class="modal-bd"></div></div></div>');
fixture.windows = [];
fixture.windowDates = ['2026-10-10', '2026-10-09', '2026-10-11'];
fixture.ruleRoute = '北京-上海';
fixture.ruleSeat = '二等座';
fixture.newSaves = 0;
fixture.newDetails = 0;
const dialog = document.getElementById('new-dialog');
const body = dialog.querySelector('.modal-bd');
const summary = () => `乘车区间：${fixture.ruleRoute} 席别类型：${fixture.ruleSeat} ` + fixture.windows.map(w =>
  `${Number(w.date.slice(5,7))}月${Number(w.date.slice(8))}日：${w.start_hour}点-${w.end_hour}点`).join(' ');
function closeNew() {
  dialog.classList.add('hidden');
  if(fixture.onNewClose) fixture.onNewClose();
}
dialog.querySelector('.modal-close').onclick = closeNew;
function editor() {
  dialog.querySelector('.modal-tit').textContent = '新增列车兑现条件设置';
  body.innerHTML = `<div class="mt-sm clearfix"><div class="pull-left">乘车区间：${fixture.ruleRoute}</div><div class="pull-left">席别：${fixture.ruleSeat}</div></div>` +
    fixture.windowDates.map(date => {
      const saved = fixture.windows.find(w=>w.date===date);
      return `<div data-date="${date.replaceAll('-','')}"><label><input type="checkbox" class="linkeTime" ${saved || date==='2026-10-10'?'checked':''}>${date}</label>` +
        [saved?.start_hour??14,saved?.end_hour??15].map((hour,i)=>`<div class="sel"><div class="sel-hd"><div class="sel-inner">${hour}点</div></div><ul class="sel-list Time${i+1}">${Array.from({length:25},(_,h)=>`<li>${h}点</li>`).join('')}</ul></div>`).join('') + '</div>';
    }).join('') + '<a id="saveTime">保存设置</a>';
  for(const box of body.querySelectorAll('.sel')) {
    box.querySelector('.sel-hd').onclick=()=>box.classList.add('active');
    for(const item of box.querySelectorAll('li')) item.onclick=()=>{
      if(item.classList.contains('disabled'))return;
      box.querySelector('.sel-inner').textContent=item.textContent;box.classList.remove('active');limits();
    };
  }
  function limits() {
    for(const row of body.querySelectorAll('[data-date]')) {
      const [start,end]=[...row.querySelectorAll('.sel-inner')].map(e=>Number(e.textContent.replace('点','')));
      [...row.querySelectorAll('.Time1 li')].forEach((e,h)=>e.classList.toggle('disabled',h>=end));
      [...row.querySelectorAll('.Time2 li')].forEach((e,h)=>e.classList.toggle('disabled',h<=start));
    }
  }
  limits();
  body.querySelector('#saveTime').onclick=()=>{
    fixture.newSaves++;
    fixture.windows=[...body.querySelectorAll('[data-date]')].filter(r=>r.querySelector('input').checked).map(row=>{
      const values=[...row.querySelectorAll('.sel-inner')].map(e=>Number(e.textContent.replace('点','')));
      const date=row.dataset.date;
      return {date:`${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6)}`,start_hour:values[0],end_hour:values[1]};
    });
    if(fixture.changeSavedWindow) fixture.windows[0].end_hour++;
    document.getElementById('contact_train_time_content').innerHTML=summary()+' <a class="linKeEdit">编辑</a>';
    document.querySelector('.linKeEdit').onclick=editor;
    document.getElementById('toPayBtn').innerHTML='提交订单<br>预估成功率(<span id="probability">40%</span>)';
  };
  dialog.classList.remove('hidden');
  if(fixture.onNewOpen) fixture.onNewOpen(body);
}
document.getElementById('contact_train').onchange=e=>{
  if(e.target.checked) editor();
  else { fixture.windows=[];document.getElementById('contact_train_time_content').textContent=''; }
};
const originalRecord=fixture.record;
fixture.record=(state='待支付',choices=fixture.selected,order='E123456')=>{
  originalRecord(state,choices,order);
  if(document.getElementById('contact_train').checked) {
    document.querySelector('.order-item').insertAdjacentHTML('beforeend', '<div>已接受新增列车：<a class="hb-add-train">详情</a></div>');
    document.querySelector('.hb-add-train').onclick=()=>{
      fixture.newDetails++;
      dialog.querySelector('.modal-tit').textContent='已接受新增列车';
      body.textContent=fixture.orderSummary || summary();
      dialog.classList.remove('hidden');
    };
  }
};
fixture.summary=summary;
