const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
let currentView = 'overview';
let allJobs = [];
let refreshTimer;

async function api(url, opt = {}) {
  const options = {...opt, headers: {'Content-Type':'application/json', ...(opt.headers || {})}};
  const r = await fetch(url, options);
  const text = await r.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = {detail:text}; }
  if (!r.ok) throw new Error(data.detail || data.message || `Request failed (${r.status})`);
  return data;
}
function esc(x){return String(x ?? '').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
function toast(msg, type='info'){
  const e=$('#toast'); e.textContent=msg; e.dataset.type=type; e.classList.add('show');
  clearTimeout(refreshTimer); refreshTimer=setTimeout(()=>e.classList.remove('show'),3200);
}
function nav(view){
  currentView=view;
  $$('.nav').forEach(x=>x.classList.toggle('active',x.dataset.view===view));
  $$('.view').forEach(x=>x.classList.toggle('active-view',x.id===view));
  const names={overview:'Overview',opportunities:'Opportunities',applications:'Applications',profile:'Candidate',settings:'Agent settings'};
  const heads={overview:'Your career, on autopilot.',opportunities:'Find your next opportunity.',applications:'Every application, accounted for.',profile:'Your professional source of truth.',settings:'Control how the agent operates.'};
  $('#viewTitle').textContent=names[view]||'Overview'; $('#headline').textContent=heads[view]||heads.overview;
  $('.sidebar')?.classList.remove('open'); document.body.classList.remove('sidebar-open');
  if(view==='opportunities') loadJobs(); if(view==='applications') loadApps(); if(view==='profile') loadProfile();
}
$$('.nav').forEach(b=>b.addEventListener('click',()=>nav(b.dataset.view)));
$$('[data-view-jump]').forEach(b=>b.addEventListener('click',()=>nav(b.dataset.viewJump)));

async function loadDashboard(){
  const [d,st]=await Promise.all([api('/api/dashboard'),api('/api/automation/status')]);
  ['jobs','qualified','applications','interviews','submitted'].forEach(k=>{if($('#'+k)) $('#'+k).textContent=d[k]??0});
  $('#capacity').textContent=`${st.submitted_today} / ${st.daily_limit}`; $('#threshold').textContent=`${st.threshold}%`;
  $('#autoToggle').checked=!!st.enabled; $('#modeLabel').textContent=st.enabled?'AUTONOMOUS':'SAFE MODE';
  $('#settingMode').textContent=st.enabled?'ON':'OFF'; $('#settingLimit').textContent=st.daily_limit+'/day'; $('#settingScore').textContent=st.threshold+'%';
}
function empty(t, action=''){return `<div class="panel empty-state"><div class="empty-icon">⌁</div><p>${esc(t)}</p>${action}</div>`}
function jobCard(j){
  const score=Number(j.score||0); const safeUrl=esc(j.url||'#');
  return `<article class="job-card" data-id="${j.id}">
    <div class="job-main"><div class="company-icon">${esc((j.company||'?').slice(0,2).toUpperCase())}</div><div class="job-copy"><h4>${esc(j.title||'Untitled role')}</h4><p>${esc(j.company||'Company')} · ${esc(j.location||'Remote / unspecified')}</p><div class="job-meta"><span class="tag">${esc(j.source||'web')}</span>${j.remote?'<span class="tag accent-tag">REMOTE</span>':''}<span class="tag">${esc(j.status||'discovered')}</span></div></div></div>
    <div class="job-side"><div class="score">${score.toFixed(0)}%</div><div class="job-actions"><a class="text-btn" href="${safeUrl}" target="_blank" rel="noopener">Open ↗</a><button class="mini-btn" data-action="qualify" data-id="${j.id}">Analyze</button><button class="mini-btn" data-action="draft" data-id="${j.id}">Prepare</button></div></div>
  </article>`;
}
async function loadJobs(){
  const rows=await api('/api/jobs'); allJobs=rows;
  renderJobs(rows);
}
function renderJobs(rows){
  const html=rows.map(jobCard).join('')||empty('No opportunities yet. Run the career agent or search for a role.');
  $('#pipeline').innerHTML=rows.slice(0,6).map(jobCard).join('')||empty('No opportunities yet. Run the career agent or search for a role.');
  $('#jobsList').innerHTML=html;
}
async function loadApps(){
  const rows=await api('/api/applications');
  $('#appsList').innerHTML=rows.length?`<div class="app-row header"><span>ROLE</span><span>COMPANY</span><span>FIT</span><span>STATUS</span><span>ACTION</span></div>`+rows.map(a=>`<div class="app-row"><div><b>${esc(a.title)}</b></div><div>${esc(a.company)}</div><div>${Number(a.score||0).toFixed(0)}%</div><div><span class="status ${esc(a.status)}">${esc(a.status.replaceAll('_',' ').toUpperCase())}</span></div><div class="row-actions"><button class="mini-btn" data-action="tailor" data-id="${a.id}">Tailor</button><button class="mini-btn" data-action="inspect" data-id="${a.id}">Inspect</button></div></div>`).join(''):empty('No applications yet. Prepare an opportunity to create the first application.');
}
async function loadProfile(){
  const p=await api('/api/profile');
  const fields=[['name','Full name'],['headline','Professional headline'],['email','Email'],['location','Location'],['skills','Skills'],['projects','Projects'],['experience','Experience'],['education','Education'],['preferences','Job preferences']];
  const vals=fields.map(([k])=>p[k]||''); const done=vals.filter(v=>String(v).trim()).length; if($('#profileBar')) $('#profileBar').style.width=Math.round(done/fields.length*100)+'%'; $('#profileForm').innerHTML=fields.map(([k,l])=>`<div class="field ${['skills','projects','experience','education','preferences'].includes(k)?'full':''}"><label>${l}</label>${['skills','projects','experience','education','preferences'].includes(k)?`<textarea data-key="${k}" placeholder="Add ${l.toLowerCase()}...">${esc(p[k]||'')}</textarea>`:`<input data-key="${k}" value="${esc(p[k]||'')}" placeholder="${esc(l)}">`}</div>`).join('');
}
async function search(){
  const q=$('#q').value.trim(); if(!q){toast('Enter a role, skill or job type first','error');$('#q').focus();return;}
  const b=$('#searchBtn'); b.disabled=true; b.textContent='Discovering…';
  try{const r=await api('/api/jobs/ingest',{method:'POST',body:JSON.stringify({query:q,max_results:20})}); toast(`${r.added||0} new opportunities discovered`,r.added?'success':'info'); await loadJobs(); nav('opportunities');}
  catch(e){toast(`Discovery failed: ${e.message}`,'error');} finally{b.disabled=false;b.textContent='Discover roles →';}
}
async function runAgent(){
  const b=$('#runAgent'); b.disabled=true; b.innerHTML='<span class="button-pulse"></span> Running agent…';
  try{
    const ready=await api('/api/agent/readiness');
    if(!ready.ready){nav('profile');toast(ready.message,'error');return;}
    const r=await api('/api/agent/run',{method:'POST'});
    toast(r.mode==='safe'?`Agent discovered ${r.discovered||0}, qualified ${r.qualified||0}, prepared ${r.drafts||0}`:`Agent processed ${r.processed||0} applications`,'success');
    await refreshAll(); nav('opportunities');
  }catch(e){toast(`Agent stopped: ${e.message}`,'error');}
  finally{b.disabled=false;b.innerHTML='Run career agent <span>→</span>';}
}
async function qualify(id){try{const r=await api(`/api/jobs/${id}/qualify`,{method:'POST'});toast(`Fit analyzed: ${Number(r.score).toFixed(0)}%`,'success');await refreshAll();}catch(e){toast(`Analysis failed: ${e.message}`,'error')}}
async function prepare(id){try{const r=await api('/api/applications',{method:'POST',body:JSON.stringify({job_id:Number(id)})});toast(`Application draft #${r.id} created`,'success');await loadApps();nav('applications');}catch(e){toast(`Could not prepare application: ${e.message}`,'error')}}
async function tailor(id){try{await api(`/api/applications/${id}/tailor`,{method:'POST'});toast('Application tailored from your profile','success');await loadApps();}catch(e){toast(`Tailoring failed: ${e.message}`,'error')}}
async function inspect(id){try{const r=await api(`/api/applications/${id}/inspect`,{method:'POST'});toast(r.ready_for_submission?'Application page is ready for review':'Human action is required before submission',r.ready_for_submission?'success':'info');}catch(e){toast(`Inspection: ${e.message}`,'error')}}
$('#searchBtn').onclick=search; $('#q').onkeydown=e=>{if(e.key==='Enter')search()}; $('#runAgent').onclick=runAgent;
$('#refresh').onclick=async()=>{const b=$('#refresh');b.classList.add('spinning');b.disabled=true;try{await refreshAll();toast('Workspace refreshed','success')}catch(e){toast(`Refresh failed: ${e.message}`,'error')}finally{b.classList.remove('spinning');b.disabled=false}};
$('#avatar').onclick=()=>nav('profile');
$('#mobileMenu').onclick=()=>{$('.sidebar')?.classList.toggle('open');document.body.classList.toggle('sidebar-open')};
$('#saveProfile').onclick=async()=>{const body={};$$('[data-key]').forEach(e=>body[e.dataset.key]=e.value);try{await api('/api/profile',{method:'POST',body:JSON.stringify(body)});toast('Candidate profile saved','success');await loadDashboard()}catch(e){toast(`Could not save profile: ${e.message}`,'error')}};
$('#autoToggle').onchange=()=>{const on=$('#autoToggle').checked;$('#autoToggle').checked=false;toast(on?'Autonomous submission is controlled by AUTO_SUBMIT in Vercel. Review policy before enabling.':'Autonomous submission remains OFF.')};
document.addEventListener('click',e=>{const b=e.target.closest('[data-action]');if(!b)return;const id=b.dataset.id;({qualify:()=>qualify(id),draft:()=>prepare(id),tailor:()=>tailor(id),inspect:()=>inspect(id)}[b.dataset.action]||(()=>{}))()});
function bindFilters(){
  $$('.filter').forEach(btn=>btn.onclick=()=>{$$('.filter').forEach(x=>x.classList.remove('active'));btn.classList.add('active');const f=btn.textContent.trim().toLowerCase();let rows=allJobs;if(f==='remote')rows=allJobs.filter(j=>j.remote);if(f==='new grad')rows=allJobs.filter(j=>/graduate|junior|entry|intern|new grad/i.test(`${j.title} ${j.description||''}`));if(f==='ai / ml')rows=allJobs.filter(j=>/\b(ai|ml|machine learning|artificial intelligence)\b/i.test(`${j.title} ${j.description||''}`));renderJobs(rows)})
}
async function refreshAll(){await Promise.all([loadDashboard(),loadJobs(),loadApps(),loadProfile()]);bindFilters()}
refreshAll().catch(e=>toast(`Workspace load failed: ${e.message}`,'error'));
