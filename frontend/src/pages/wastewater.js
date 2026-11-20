import {field,sync} from '../store.js';import {request,identity} from '../api.js';import {lead} from '../components/field.js';import {safe,fixed,dataFrom,message,localTime} from '../utils.js';
const STATE={declared:'待核验',verified:'已核验',receiving:'分批收水中',closed:'已收齐'};
const TRIP={loading:'装车中',weighed:'已过磅待签收',received:'已签收',rejected:'接收站拒收',returned:'拒收水已清退'};
const state=x=>`<span class="badge ${x==='closed'||x==='received'?'accepted':''}">${safe(STATE[x]||TRIP[x]||x)}</span>`;
const tripCode=id=>field.trips.find(t=>t.id===id)?.trip_code||('车次'+id);
function manifestCard(m){
  const mission=field.missions.find(x=>x.id===m.mission_id);
  const trips=m.trip_ids.map(id=>field.trips.find(t=>t.id===id)).filter(Boolean);
  const returns=m.returns||[];
  return `<article class="surface" data-manifest="${m.id}"><span class="code">${safe(m.manifest_no)} / WASH-${m.mission_id}</span><h3>${safe(m.station)} ${state(m.state)}</h3>
  <div class="cols two"><div>核定水量<div class="reading">${fixed(m.verified_liters,0)}<small> L</small></div></div><div>已签收<div class="reading">${fixed(m.received_liters,0)}<small> L</small></div></div></div>
  <p>申报 ${fixed(m.declared_liters,0)}L · 已装车 ${fixed(m.loaded_liters,0)}L · 核验余量 ${fixed(m.room_liters,0)}L · 途中损耗 ${fixed(m.loss_liters,0)}L<br>任务用水 ${fixed(mission?.water_liters,0)}L · 核验人 ${safe(m.verified_by||'待核')}</p>
  <p class="note">签收人 ${safe(m.received_by||'待签收')} · ${safe(m.receipt||'无凭证')}<br>签收时间 ${localTime(m.received_at)}</p>
  ${m.state==='declared'&&identity().role==='admin'?`<form class="verify-form" data-id="${m.id}"><label>主管核定水量 / L<input name="verified_liters" type="number" min="0.1" step="0.1" value="${m.declared_liters}" required></label><button class="primary">核定联单</button></form>`:''}
  <div class="tablewrap"><table><thead><tr><th>车次 / 车辆</th><th>装车</th><th>净收</th><th>分摊</th><th>状态</th></tr></thead><tbody>${trips.map(t=>{const load=t.loads.find(l=>l.manifest_id===m.id)||{};return `<tr><td>${safe(t.trip_code)}<br><span class="note">${safe(t.vehicle_code)}</span></td><td>${fixed(load.loaded_liters,0)}L</td><td>${fixed(t.net_liters,0)}L</td><td>${fixed(load.allocated_liters,0)}L</td><td>${state(t.state)}</td></tr>`;}).join('')||'<tr><td colspan="5" class="note">尚未装车</td></tr>'}</tbody></table></div>
  ${returns.length?`<div class="rule">退回去向：${returns.map(r=>`${safe(r.destination)} · ${fixed(r.liters,0)}L · ${safe(r.received_by)} · ${safe(r.receipt)} · ${localTime(r.created_at)}`).join('<br>')}</div>`:''}
  </article>`;
}
export function render(){const edit=identity().role!=='viewer';
  const openMissions=field.missions.filter(m=>m.status==='accepted');
  const loadable=field.manifests.filter(m=>m.state!=='declared'&&m.state!=='closed'&&m.room_liters>0);
  return lead('RECOVERY & MANIFESTS','一张联单几次装车，一车废水几张联单','接收站只出整车磅单。历史磅单与实收量估算净收水，误差过大须补实测；装车不超过联单核验余量，混装按各联单余量分摊，拒收水清退回水点后才能重装。')+`<div class="twocol expansion-layout">
  <section class="surface"><h2>登记废水联单</h2><form id="manifest-form"><label>已验收任务<select name="mission_id">${openMissions.map(m=>`<option value="${m.id}">WASH-${m.id} · 用水${m.water_liters}L</option>`).join('')}</select></label><label>联单编号<input name="manifest_no" placeholder="WW-1117-01" required></label><label>接收站<input name="station" value="北岭接收站" required></label><label>申报水量 / L<input name="declared_liters" type="number" min="0.1" step="0.1" placeholder="留空取任务用水" required></label><button class="primary" ${edit?'':'disabled'}>登记联单</button></form>
  <div class="rule">同一任务的各联单申报量合计不得超过任务用水。联单装车前由主管核验数量；核验后数量冻结。</div>
  <h2>建立车次与装车</h2><form id="trip-form"><label>车次编号<input name="trip_code" placeholder="TR-1117-01" required></label><label>车辆<input name="vehicle_code" placeholder="甘A·W2302" required></label><label>接收站<input name="station" value="北岭接收站" required></label><button ${edit?'':'disabled'}>建立空车次</button></form>
  <form id="load-form"><label>装车车次<select name="trip_id">${field.trips.filter(t=>t.state==='loading').map(t=>`<option value="${t.id}">${safe(t.trip_code)} · ${safe(t.vehicle_code)}</option>`).join('')}</select></label><label>联单<select name="manifest_id">${loadable.map(m=>`<option value="${m.id}">${safe(m.manifest_no)} · 余量${fixed(m.room_liters,0)}L</option>`).join('')}</select></label><label>本联单装车量 / L<input name="loaded_liters" type="number" min="0.1" step="0.1" required></label><button ${edit?'':'disabled'}>登记装车</button></form>
  <div class="rule">同张联单可分多趟装车；在途车次继续占用核验余量，并发装车合计不得超出核验量。</div></section>
  <section><h2>联单签收与退回去向</h2>${field.manifests.map(manifestCard).join('')||'<div class="empty">暂无废水联单</div>'}</section></div>
  <section class="surface" style="margin-top:24px"><h2>车次磅单、签收与拒收</h2><div class="tablewrap"><table><thead><tr><th>车次 / 车辆</th><th>磅单</th><th>净收估算</th><th>状态</th><th>操作</th></tr></thead><tbody>${field.trips.map(t=>`<tr data-trip="${t.id}"><td>${safe(t.trip_code)}<br><span class="note">${safe(t.vehicle_code)} · ${safe(t.station)}</span></td><td>${safe(t.weigh_ticket||'待过磅')}<br><span class="note">毛${fixed(t.gross_kg,0)} 皮${fixed(t.tare_kg,0)} kg</span></td><td>${fixed(t.estimated_net_liters,0)}L<br><span class="note">${t.estimated_net_liters==null?'':(t.estimate_evidence?.measured?'实测记收':'估算采用')}</span></td><td>${state(t.state)}<br><span class="note">${safe(t.reject_reason||'')}</span></td><td>${tripActions(t,edit)}</td></tr>`).join('')||'<tr><td colspan="5" class="note">暂无车次</td></tr>'}</tbody></table></div><div class="rule">磅单重试按磅单号幂等，不重复记收。净收估算按车辆留出验证，误差过大或历史不足须现场实测。拒收须整趟清退回水点并登记去向，未清退前该车不得重装。</div></section>`;}
function tripActions(t,edit){
  if(!edit)return '<span class="note">只读</span>';
  const forms=[];
  if(t.state==='loading')forms.push(`<form class="weigh-form" data-id="${t.id}"><input name="weigh_ticket" placeholder="磅单号" required><input name="gross_kg" type="number" min="1" value="9500" placeholder="毛重kg" required><input name="tare_kg" type="number" min="1" value="6500" placeholder="皮重kg" required><input name="ambient_temp_c" type="number" step="0.1" value="22" placeholder="气温" required><input name="haul_km" type="number" step="0.1" value="20" placeholder="运距km" required><input name="tank_capacity_l" type="number" min="1" value="4000" placeholder="罐容L" required><input name="measured_net_liters" type="number" step="0.1" placeholder="实测净收L（估算不可靠时必填）"><button>过磅估算</button></form>`);
  if(t.state==='weighed')forms.push(`<form class="receive-form" data-id="${t.id}"><input name="received_by" value="接收站 赵工" placeholder="签收人" required><input name="receipt" placeholder="接收凭证" required><button class="primary">接收站签收</button></form>`);
  if(['loading','weighed'].includes(t.state))forms.push(`<form class="reject-form" data-id="${t.id}"><input name="reason" placeholder="拒收原因（≥5字）" required><button>整车站拒收</button></form>`);
  if(['rejected','returned'].includes(t.state))for(const l of t.loads)forms.push(`<form class="return-form" data-id="${t.id}" data-manifest="${l.manifest_id}"><strong class="note">${safe(l.manifest_no)} 待清退 ${fixed(l.loaded_liters-l.returned_liters,0)}L</strong><input name="liters" type="number" step="0.1" value="${Math.max(0,l.loaded_liters-l.returned_liters)}" required><input name="destination" value="西坡蓄水池" placeholder="退回水点" required><input name="received_by" value="水点 李工" placeholder="接收人" required><input name="receipt" placeholder="水点回执编号" required><input name="reason" placeholder="拒收退回原因（≥5字）" required><button>登记清退</button></form>`);
  return forms.join('')||'<span class="note">已完结</span>';
}
export function bind(render){async function act(path,body,method='POST'){try{await request(path,method,body);await sync();render();message('废水台账已更新');}catch(e){message(e.message);}}
  const on=(sel,fn)=>document.querySelectorAll(sel).forEach(f=>f.onsubmit=e=>{e.preventDefault();fn(f,dataFrom(f));});
  document.querySelector('#manifest-form').onsubmit=e=>{e.preventDefault();const b=dataFrom(e.target);b.mission_id=Number(b.mission_id);b.declared_liters=b.declared_liters?Number(b.declared_liters):null;act('/waste-manifests',b);};
  document.querySelector('#trip-form').onsubmit=e=>{e.preventDefault();act('/waste-trips',dataFrom(e.target));};
  document.querySelector('#load-form').onsubmit=e=>{e.preventDefault();const b=dataFrom(e.target);b.trip_id=Number(b.trip_id);b.manifest_id=Number(b.manifest_id);b.loaded_liters=Number(b.loaded_liters);act('/waste-trips/'+b.trip_id+'/loads',b);};
  on('.weigh-form',(f,b)=>{b=Object.fromEntries(Object.entries(b).map(([k,v])=>[k,v===''?null:(k==='weigh_ticket'?v:Number(v))]));act('/waste-trips/'+f.dataset.id+'/weigh',b);});
  on('.receive-form',(f,b)=>act('/waste-trips/'+f.dataset.id+'/receive',b));
  on('.reject-form',(f,b)=>act('/waste-trips/'+f.dataset.id+'/reject',b));
  on('.return-form',(f,b)=>{act('/waste-trips/'+f.dataset.id+'/returns',{manifest_id:Number(f.dataset.manifest),liters:Number(b.liters),destination:b.destination,received_by:b.received_by,receipt:b.receipt,reason:b.reason});});
  on('.verify-form',(f,b)=>act('/waste-manifests/'+f.dataset.id+'/verify',{verified_liters:Number(b.verified_liters)}));
}
