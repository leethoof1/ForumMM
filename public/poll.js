const role=document.body.dataset.pollRole,token=decodeURIComponent(location.hash.slice(1));
const $=s=>document.querySelector(s),escapeText=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let busy=false,stopped=false,resultsKey='',voterKey='';
async function api(action,body={}){const r=await fetch('/api/poll/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Forum-Request':'1'},body:JSON.stringify({token,...body})});const d=await r.json();if(!r.ok){if(r.status===403)stopped=true;throw Error(d.error||'Ошибка сервера')}return d}
function text(node,value){const s=String(value);if(node.textContent!==s)node.textContent=s}
function attr(node,name,value){const s=String(value);if(node.getAttribute(name)!==s)node.setAttribute(name,s)}
function render(d){
 const options=d.options||[];
 if(role!=='vote'){renderResults(d,options);return}
 const key=JSON.stringify([d.question,options,d.opened,d.choice]);
 if(key===voterKey)return;voterKey=key;
 let html=`<span class="label">${d.opened?'Голосование открыто':'Голосование закрыто'}</span><h1>${escapeText(d.question)}</h1>`;
 html+=d.choice?`<section class="next"><h2>Твой голос учтён!</h2><p>${escapeText(options.find(x=>x.id===d.choice)?.label)}</p><p class="muted">Изменить ответ нельзя.</p></section>`:`<p>${d.opened?'Выбери один вариант. Голос можно отдать один раз.':'Ведущий скоро откроет голосование. Оставь эту страницу открытой.'}</p><div class="poll-options">${options.map(o=>`<button class="primary" data-choice="${o.id}" ${!d.opened?'disabled':''}>${escapeText(o.label)}</button>`).join('')}</div>`;
 $('#poll-content').innerHTML=html;
 document.querySelectorAll('[data-choice]').forEach(b=>b.onclick=()=>vote(b.dataset.choice));
}
function renderResults(d,options){
 const key=JSON.stringify([d.question,options]);
 if(key!==resultsKey){
  resultsKey=key;
  $('#poll-content').innerHTML=`<span class="label" id="poll-status"></span><h1>${escapeText(d.question)}</h1><div class="poll-total">Всего голосов: <b id="poll-total-count">0</b></div><section class="poll-comparison"><div class="poll-legends">${options.map((o,i)=>`<div class="poll-side ${i===0?'poll-side-red':'poll-side-blue'}"><h2>${escapeText(o.label)}</h2><div class="poll-score"><b class="poll-count" data-count="${o.id}">0</b><span class="poll-percent" data-percent="${o.id}">0%</span></div></div>`).join('')}</div><svg class="poll-shared-bar" viewBox="0 0 1000 120" preserveAspectRatio="none" role="img" aria-label="Соотношение голосов"><defs><clipPath id="poll-bar-clip"><rect width="1000" height="120" rx="18"/></clipPath></defs><g clip-path="url(#poll-bar-clip)"><rect class="poll-share-empty" width="1000" height="120"/><rect id="poll-red" class="poll-share-red" x="0" width="0" height="120"/><rect id="poll-blue" class="poll-share-blue" x="0" width="0" height="120"/></g></svg></section>${role==='control'?'<div class="actions"><button class="primary" data-command="open">Открыть голосование</button><button class="primary" data-command="close">Закрыть голосование</button><button class="textbutton" data-command="reset">Обнулить голоса и закрыть</button></div>':''}`;
  document.querySelectorAll('[data-command]').forEach(b=>b.onclick=()=>command(b.dataset.command));
 }
 const total=Number(d.total)||0;
 text($('#poll-status'),d.opened?'Голосование открыто':'Голосование закрыто');
 text($('#poll-total-count'),total);
 const first=Number(d.counts[options[0]?.id])||0,firstPercent=total?Math.round(first/total*1000)/10:0;
 options.forEach((o,i)=>{const n=Number(d.counts[o.id])||0;const percent=total?(i===0?firstPercent:Math.round((100-firstPercent)*10)/10):0;text(document.querySelector(`[data-count="${o.id}"]`),n);text(document.querySelector(`[data-percent="${o.id}"]`),`${percent.toLocaleString('ru-RU',{maximumFractionDigits:1})}%`)});
 const left=total?first/total*1000:0,right=total?1000-left:0;
 attr($('#poll-red'),'width',left);attr($('#poll-blue'),'x',left);attr($('#poll-blue'),'width',right);
 attr($('.poll-shared-bar'),'aria-label',options.map(o=>`${o.label}: ${Number(d.counts[o.id])||0} голосов`).join('; '));
}
async function vote(choice){if(busy)return;busy=true;document.querySelectorAll('[data-choice]').forEach(b=>b.disabled=true);try{const d=await api('vote',{choice});$('#poll-error').textContent='';render(d)}catch(e){$('#poll-error').textContent=e.message==='Failed to fetch'?'Нет связи. Повтори: второй голос не будет добавлен.':e.message}finally{busy=false;refresh()}}
async function command(action){if(busy)return;if(action==='reset'&&!confirm('Удалить все голоса этого опроса и закрыть голосование?'))return;busy=true;try{render(await api('manage',{action,confirm:action==='reset'?'RESET-POLL':undefined}));$('#poll-error').textContent=''}catch(e){$('#poll-error').textContent=e.message}finally{busy=false}}
async function refresh(){if(stopped||busy||document.hidden)return;busy=true;try{const d=await api(role==='vote'?'view':role==='results'?'results':'manage');$('#poll-error').textContent='';render(d)}catch(e){$('#poll-error').textContent=e.message==='Failed to fetch'?'Связь потеряна. Повторяем подключение…':e.message}finally{busy=false}}
async function qr(){try{const d=await api('qr');const img=document.createElement('img');img.src=d.image;img.alt='QR-код для голосования';const p=document.createElement('p');p.textContent='Отсканируй QR-код и выбери свой вариант';const link=document.createElement('a');link.href=d.url;link.textContent='Ссылка для участников';$('#poll-qr').append(img,p,link)}catch(e){$('#poll-error').textContent=e.message}}
if(!token&&role!=='vote'){stopped=true;$('#poll-content').textContent='Открой полную ссылку организатора или отсканируй QR-код на экране.'}else{refresh();if(role==='results')qr();setInterval(refresh,role==='vote'?3000:2000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()})}
