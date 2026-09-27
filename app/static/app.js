const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
let currentView = 'overview';
let allJobs = [];
let toastTimer;

async function api(url, opt = {}) {
  const isForm = opt.body instanceof FormData;
  const options = {...opt, headers: {...(isForm ? {} : {'Content-Type':'application/json'}), ...(opt.headers || {})}};
  const r = await fetch(url, options);
  const text = await r.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = {detail:text}; }
  if (!r.ok) throw new Error(data.detail || data.message || `Request failed (${r.status})`);
  return data;
}
function esc(x){return String(x ?? '').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
function setText(selector, value){const e=$(selector); if(e) e.textContent=String(value ?? ''); return e;}
function setHTML(selector, value){const e=$(selector); if(e) e.innerHTML=String(value ?? ''); return e;}
function toast(msg, type='info'){
  const e=$('#toast'); if(!e){console.warn('[JobHunt]',msg);return;}
  e.textContent=String(msg ?? ''); e.dataset.type=type; e.classList.add('show');
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>e?.classList.remove('show'),3600);
}
function nav(view){
  currentView=view;
  $$('.nav').forEach(x=>x.classList.toggle('active',x.dataset.view===view));
  $$('.view').forEach(x=>x.classList.toggle('active-view',x.id===view));
  const names={overview:'Overview',opportunities:'Opportunities',applications:'Applications',profile:'Candidate',settings:'Agent settings'};
  const heads={overview:'Your career, on autopilot.',opportunities:'Find your next opportunity.',applications:'Every application, accounted for.',profile:'Your professional source of truth.',settings:'Control how the agent operates.'};
  setText('#viewTitle',names[view]||'Overview'); setText('#headline',heads[view]||heads.overview);
  $('.sidebar')?.classList.remove('open'); document.body.classList.remove('sidebar-open');
  if(view==='opportunities') loadJobs().catch(e=>toast(`Could not load opportunities: ${e.message}`,'error'));
  if(view==='applications') loadApps().catch(e=>toast(`Could not load applications: ${e.message}`,'error'));
  if(view==='profile') loadProfile().catch(e=>toast(`Could not load profile: ${e.message}`,'error'));
}
$$('.nav').forEach(b=>b.addEventListener('click',()=>nav(b.dataset.view)));
$$('[data-view-jump]').forEach(b=>b.addEventListener('click',()=>nav(b.dataset.viewJump)));

async function loadDashboard(){
  const [d,st]=await Promise.all([api('/api/dashboard'),api('/api/automation/status')]);
  ['jobs','qualified','applications','interviews','submitted'].forEach(k=>setText('#'+k,d[k]??0));
  setText('#capacity',`${st.submitted_today} / ${st.daily_limit}`); setText('#threshold',`${st.threshold}%`);
  const toggle=$('#autoToggle'); if(toggle) toggle.checked=!!st.enabled;
  setText('#modeLabel',st.enabled?'AUTONOMOUS':'SAFE MODE'); setText('#settingMode',st.enabled?'ON':'OFF'); setText('#settingLimit',st.daily_limit+'/day'); setText('#settingScore',st.threshold+'%');
}
function empty(t, action=''){return `<div class="panel empty-state"><div class="empty-icon">⌁</div><p>${esc(t)}</p>${action}</div>`}
function jobCard(j){
  const score=Number(j.score||0); const safeUrl=esc(j.url||'#');
  return `<article class="job-card" data-id="${j.id}"><div class="job-main"><div class="company-icon">${esc((j.company||'?').slice(0,2).toUpperCase())}</div><div class="job-copy"><h4>${esc(j.title||'Untitled role')}</h4><p>${esc(j.company||'Company')} · ${esc(j.location||'Remote / unspecified')}</p><div class="job-meta"><span class="tag">${esc(j.source||'web')}</span>${j.remote?'<span class="tag accent-tag">REMOTE</span>':''}<span class="tag">${esc(j.status||'discovered')}</span></div></div></div><div class="job-side"><div class="score">${score.toFixed(0)}%</div><div class="job-actions"><a class="text-btn" href="${safeUrl}" target="_blank" rel="noopener">Open ↗</a><button class="mini-btn" data-action="qualify" data-id="${j.id}">Analyze</button><button class="mini-btn" data-action="draft" data-id="${j.id}">Prepare</button></div></div></article>`;
}
async function loadJobs(){const rows=await api('/api/jobs'); allJobs=Array.isArray(rows)?rows:[]; renderJobs(allJobs);}
function renderJobs(rows){setHTML('#pipeline',rows.slice(0,6).map(jobCard).join('')||empty('No opportunities yet. Run the career agent or search for a role.'));setHTML('#jobsList',rows.map(jobCard).join('')||empty('No opportunities yet. Run the career agent or search for a role.'));}
async function loadApps(){
  const rows=await api('/api/applications');
  setHTML('#appsList',rows.length?`<div class="app-row header"><span>ROLE</span><span>COMPANY</span><span>FIT</span><span>STATUS</span><span>ACTION</span></div>`+rows.map(a=>`<div class="app-row"><div><b>${esc(a.title)}</b></div><div>${esc(a.company)}</div><div>${Number(a.score||0).toFixed(0)}%</div><div><span class="status ${esc(a.status)}">${esc(a.status.replaceAll('_',' ').toUpperCase())}</span></div><div class="row-actions"><button class="mini-btn" data-action="tailor" data-id="${a.id}">Tailor</button><button class="mini-btn" data-action="inspect" data-id="${a.id}">Inspect</button></div></div>`).join(''):empty('No applications yet. Prepare an opportunity to create the first application.'));
}
const profileFields=[['name','Full name'],['headline','Professional headline'],['email','Email'],['location','Location'],['skills','Skills'],['projects','Projects'],['experience','Experience'],['education','Education'],['preferences','Job preferences']];
async function loadProfile(){
  const p=await api('/api/profile'); const vals=profileFields.map(([k])=>p[k]||''); const done=vals.filter(v=>String(v).trim()).length;
  const bar=$('#profileBar'); if(bar) bar.style.width=Math.round(done/profileFields.length*100)+'%'; setText('#profilePercent',Math.round(done/profileFields.length*100)+'% complete');
  setHTML('#profileForm',profileFields.map(([k,l])=>`<div class="field ${['skills','projects','experience','education','preferences'].includes(k)?'full':''}"><label>${l}</label>${['skills','projects','experience','education','preferences'].includes(k)?`<textarea data-key="${k}" placeholder="Add ${l.toLowerCase()}...">${esc(p[k]||'')}</textarea>`:`<input data-key="${k}" value="${esc(p[k]||'')}" placeholder="${esc(l)}">`}</div>`).join(''));
}
function fillProfile(p){
  profileFields.forEach(([k])=>{const e=$(`[data-key="${k}"]`); if(e && p[k] != null) e.value=p[k];});
  const vals=profileFields.map(([k])=>$(`[data-key="${k}"]`)?.value||''); const done=vals.filter(v=>String(v).trim()).length; const pct=Math.round(done/profileFields.length*100); const bar=$('#profileBar'); if(bar) bar.style.width=pct+'%'; setText('#profilePercent',pct+'% complete');
}
async function importResume(){
  const input=$('#resumeFile'); const file=input?.files?.[0]; if(!file){toast('Choose a PDF or DOCX resume first.','error');return;}
  const b=$('#importResume'); if(b){b.disabled=true;b.textContent='Parsing resume…';}
  try{const form=new FormData();form.append('file',file);const r=await api('/api/profile/import-resume',{method:'POST',body:form});fillProfile(r.profile||{});toast(r.message||'Resume imported. Review the fields and save your profile.','success');}
  catch(e){toast(`Resume import failed: ${e.message}`,'error');}
  finally{if(b){b.disabled=false;b.textContent='Parse & auto-fill';}}
}
async function search(){
  const q=$('#q')?.value.trim(); if(!q){toast('Enter a role, skill or job type first','error');$('#q')?.focus();return;}
  const b=$('#searchBtn'); if(b){b.disabled=true;b.textContent='Discovering…';}
  try{const r=await api('/api/jobs/ingest',{method:'POST',body:JSON.stringify({query:q,max_results:20})});toast(`${r.added||0} new opportunities discovered`,r.added?'success':'info');await loadJobs();nav('opportunities');}
  catch(e){toast(`Discovery failed: ${e.message}`,'error');} finally{if(b){b.disabled=false;b.textContent='Discover roles →';}}
}
function showAgentResult(r){
  setText('#agentDiscovered',r.discovered??0);setText('#agentQualified',r.qualified??0);setText('#agentPrepared',r.prepared??r.drafts??0);setText('#agentSkipped',r.skipped??0);setText('#agentTotal',r.total_roles??'—');
  const panel=$('#agentResult'); if(panel) panel.classList.add('show');
}
async function runAgent(){
  const b=$('#runAgent'); if(b){b.disabled=true;b.innerHTML='<span class="button-pulse"></span> Running agent…';}
  try{
    const ready=await api('/api/agent/readiness');
    if(!ready.ready){nav('profile');toast(ready.message||'Complete the candidate profile before running the agent.','error');return;}
    const r=await api('/api/agent/run',{method:'POST'}); showAgentResult(r);
    const message=r.skipped ? `Agent reused ${r.skipped} existing roles · ${r.qualified||0} qualified · ${r.prepared??r.drafts??0} prepared.` : `Agent discovered ${r.discovered||0} · ${r.qualified||0} qualified · ${r.prepared??r.drafts??0} prepared.`;
    toast(r.message||message,'success');
    await refreshAll(); nav('opportunities');
  }catch(e){toast(`Agent stopped: ${e.message}`,'error');}
  finally{if(b){b.disabled=false;b.innerHTML='Run career agent <span>→</span>';}}
}
async function qualify(id){try{const r=await api(`/api/jobs/${id}/qualify`,{method:'POST'});toast(`Fit analyzed: ${Number(r.score||0).toFixed(0)}%`,'success');await refreshAll();}catch(e){toast(`Analysis failed: ${e.message}`,'error')}}
async function prepare(id){try{const r=await api('/api/applications',{method:'POST',body:JSON.stringify({job_id:Number(id)})});toast(`Application draft #${r.id} created`,'success');await loadApps();nav('applications');}catch(e){toast(`Could not prepare application: ${e.message}`,'error')}}
async function tailor(id){try{await api(`/api/applications/${id}/tailor`,{method:'POST'});toast('Application tailored from your profile','success');await loadApps();}catch(e){toast(`Tailoring failed: ${e.message}`,'error')}}
async function inspect(id){try{const r=await api(`/api/applications/${id}/inspect`,{method:'POST'});toast(r.ready_for_submission?'Application page is ready for review':'Human action is required before submission',r.ready_for_submission?'success':'info');}catch(e){toast(`Inspection: ${e.message}`,'error')}}

$('#searchBtn')?.addEventListener('click',search); $('#q')?.addEventListener('keydown',e=>{if(e.key==='Enter')search()}); $('#runAgent')?.addEventListener('click',runAgent);
$('#refresh')?.addEventListener('click',async()=>{const b=$('#refresh');b?.classList.add('spinning');if(b)b.disabled=true;try{await refreshAll();toast('Workspace refreshed','success')}catch(e){toast(`Refresh failed: ${e.message}`,'error')}finally{b?.classList.remove('spinning');if(b)b.disabled=false}});
$('#avatar')?.addEventListener('click',()=>nav('profile'));
$('#mobileMenu')?.addEventListener('click',()=>{$('.sidebar')?.classList.toggle('open');document.body.classList.toggle('sidebar-open')});
$('#importResume')?.addEventListener('click',importResume);
$('#resumeFile')?.addEventListener('change',e=>{const name=e.target.files?.[0]?.name||'No file selected';setText('#resumeName',name)});
$('#saveProfile')?.addEventListener('click',async()=>{const body={};$$('[data-key]').forEach(e=>body[e.dataset.key]=e.value);try{await api('/api/profile',{method:'POST',body:JSON.stringify(body)});toast('Candidate profile saved','success');await Promise.all([loadDashboard(),loadProfile()]);}catch(e){toast(`Could not save profile: ${e.message}`,'error')}});
$('#autoToggle')?.addEventListener('change',()=>{const on=$('#autoToggle')?.checked;if(on&&$('#autoToggle'))$('#autoToggle').checked=false;toast(on?'Autonomous submission is controlled by AUTO_SUBMIT in Vercel. Review policy before enabling.':'Autonomous submission remains OFF.',on?'info':'info')});
document.addEventListener('click',e=>{const b=e.target.closest?.('[data-action]');if(!b)return;const id=b.dataset.id;const actions={qualify, draft:prepare, tailor, inspect};actions[b.dataset.action]?.(id)});
function bindFilters(){$$('.filter').forEach(btn=>btn.onclick=()=>{$$('.filter').forEach(x=>x.classList.remove('active'));btn.classList.add('active');const f=btn.textContent.trim().toLowerCase();let rows=allJobs;if(f==='remote')rows=allJobs.filter(j=>j.remote);if(f==='new grad')rows=allJobs.filter(j=>/graduate|junior|entry|intern|new grad/i.test(`${j.title} ${j.description||''}`));if(f==='ai / ml')rows=allJobs.filter(j=>/\b(ai|ml|machine learning|artificial intelligence)\b/i.test(`${j.title} ${j.description||''}`));renderJobs(rows)})}
async function refreshAll(){await Promise.all([loadDashboard(),loadJobs(),loadApps(),loadProfile()]);bindFilters()}
window.addEventListener('DOMContentLoaded',()=>refreshAll().catch(e=>toast(`Workspace load failed: ${e.message}`,'error')));

async function runFeature(id, path, opts={}){const el=$(id);try{const r=await api(path,opts);if(el)el.textContent=JSON.stringify(r,null,2);toast('Completed successfully','success');return r}catch(e){if(el)el.textContent=e.message;toast(e.message,'error');return null}}
$('#atsMapDemo')?.addEventListener('click',async()=>{const id=Number($('#atsAppId')?.value||0);if(!id)return toast('Enter an application ID','error');const fields=[{name:'first_name',label:'First Name',required:true},{name:'last_name',label:'Last Name',required:true},{name:'email',label:'Email Address',required:true},{name:'phone',label:'Phone Number'},{name:'city',label:'City',required:true},{name:'state',label:'State'},{name:'country',label:'Country',required:true},{name:'resume',label:'Resume',required:true},{name:'cover_letter',label:'Cover Letter'}];await runFeature('#atsResult',`/api/applications/${id}/ats-map`,{method:'POST',body:JSON.stringify(fields)});});
$('#tailorAnalyze')?.addEventListener('click',async()=>{const id=Number($('#tailorAppId')?.value||0);if(!id)return toast('Enter an application ID','error');await runFeature('#tailorResult',`/api/applications/${id}/tailor/analyze`,{method:'POST'});});
$('#telemetryBtn')?.addEventListener('click',async()=>{const c=($('#telemetryCompany')?.value||'').trim();if(!c)return toast('Enter a company name','error');await runFeature('#telemetryResult',`/api/companies/${encodeURIComponent(c)}/telemetry`,{method:'POST'});});
$('#tokenBtn')?.addEventListener('click',async()=>{await runFeature('#tokenResult','/api/candidate/token',{method:'POST'});});
$('#interviewBtn')?.addEventListener('click',async()=>{const id=Number($('#interviewJobId')?.value||0);if(!id)return toast('Enter a job ID','error');const r=await runFeature('#interviewResult',`/api/interviews/mock?job_id=${id}`,{method:'POST'});if(r){const box=$('#interviewResult');if(box)box.innerHTML=(r.questions||[]).map((q,i)=>`<article class="interview-card"><small>${esc(q.type||'QUESTION')} · ${esc(q.focus||'')}</small><h4>${i+1}. ${esc(q.question||'')}</h4></article>`).join('');}});
$('#negotiateBtn')?.addEventListener('click',async()=>{const id=Number($('#offerAppId')?.value||0);const offer=Number($('#offerAmount')?.value||0),low=Number($('#marketLow')?.value||0),high=Number($('#marketHigh')?.value||0);if(!id||!offer||!low)return toast('Enter application, offer and market range','error');await runFeature('#negotiationResult',`/api/applications/${id}/negotiation`,{method:'POST',body:JSON.stringify({offer,market_low:low,market_high:high})});});
