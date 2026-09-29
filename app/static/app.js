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
  const names={overview:'Home',opportunities:'Jobs',applications:'Applications',profile:'My profile',intelligence:'Apply tools',interview:'Interview prep',offer:'Offers',settings:'Settings'};
  const heads={overview:'Your job search, on autopilot.',opportunities:'Find and score roles.',applications:'Every application in one place.',profile:'Your details, your source of truth.',intelligence:'Get each application ready.',interview:'Practice for the actual role.',offer:'Plan your counter-offer.',settings:'Control how the agent works.'};
  setText('#viewTitle',names[view]||'Overview'); setText('#headline',heads[view]||heads.overview);
  $('.sidebar')?.classList.remove('open'); document.body.classList.remove('sidebar-open'); window.scrollTo({top:0});
  if(view==='opportunities') loadJobs().catch(e=>toast(`Could not load opportunities: ${e.message}`,'error'));
  if(view==='applications') loadApps().catch(e=>toast(`Could not load applications: ${e.message}`,'error'));
  if(view==='profile') loadProfile().catch(e=>toast(`Could not load profile: ${e.message}`,'error'));
}
$$('.nav').forEach(b=>b.addEventListener('click',()=>nav(b.dataset.view)));

async function loadDashboard(){
  const [d,st]=await Promise.all([api('/api/dashboard'),api('/api/automation/status')]);
  ['jobs','qualified','applications','interviews','submitted'].forEach(k=>setText('#'+k,d[k]??0));
  setText('#capacity',`${st.submitted_today} / ${st.daily_limit}`); setText('#threshold',`${st.threshold}%`);
  const toggle=$('#autoToggle'); if(toggle) toggle.checked=!!st.enabled;
  setText('#modeLabel',st.enabled?'AUTONOMOUS':'SAFE MODE'); setText('#footMode',st.enabled?'Auto-submit on':'Safe mode · asks before sending'); markSteps(d); setText('#settingMode',st.enabled?'ON':'OFF'); setText('#settingLimit',st.daily_limit+'/day'); setText('#settingScore',st.threshold+'%');
}

let profileDone=false;
function markSteps(d){
  $('#stepProfile')?.classList.toggle('done',profileDone);
  $('#stepSearch')?.classList.toggle('done',(d?.jobs||0)>0);
  $('#stepApply')?.classList.toggle('done',(d?.applications||0)>0);
}
let allApps=[];
function fillSelect(id,rows,label,emptyText){
  const el=$(id); if(!el) return; const keep=el.value;
  el.innerHTML=rows.length?`<option value="">${esc(emptyText)}</option>`+rows.map(r=>`<option value="${r.id}">#${r.id} · ${esc(label(r))}</option>`).join(''):`<option value="">${esc(emptyText.replace('Select','No'))} yet</option>`;
  if(keep) el.value=keep;
}
function fillSelects(){
  const appLabel=a=>`${a.title||'Role'} — ${a.company||''}`;
  ['#browserAppId','#atsAppId','#tailorAppId','#offerAppId'].forEach(id=>fillSelect(id,allApps,appLabel,'Select an application'));
  fillSelect('#interviewJobId',allJobs,j=>`${j.title||'Role'} — ${j.company||''}`,'Select a job');
}
function empty(t, action=''){return `<div class="panel empty-state"><div class="empty-icon">⌁</div><p>${esc(t)}</p>${action}</div>`}
function jobCard(j){
  const score=Number(j.score||0); const safeUrl=esc(j.url||'#');
  return `<article class="job-card" data-id="${j.id}"><div class="job-main"><div class="company-icon">${esc((j.company||'?').slice(0,2).toUpperCase())}</div><div class="job-copy"><h4>${esc(j.title||'Untitled role')}</h4><p>${esc(j.company||'Company')} · ${esc(j.location||'Remote / unspecified')}</p><div class="job-meta"><span class="tag">${esc(j.source||'web')}</span>${j.remote?'<span class="tag accent-tag">REMOTE</span>':''}<span class="tag">${esc(j.status||'discovered')}</span></div></div></div><div class="job-side"><div class="score">${score.toFixed(0)}%</div><div class="job-actions"><a class="text-btn" href="${safeUrl}" target="_blank" rel="noopener">Open ↗</a><button class="mini-btn" data-action="qualify" data-id="${j.id}">Analyze</button><button class="mini-btn" data-action="draft" data-id="${j.id}">Prepare</button></div></div></article>`;
}
async function loadJobs(){const rows=await api('/api/jobs'); allJobs=Array.isArray(rows)?rows:[]; renderJobs(allJobs); fillSelects();}
function renderJobs(rows){setHTML('#pipeline',rows.slice(0,6).map(jobCard).join('')||empty('No jobs yet. Run the career agent from Home, or search for a role above.'));setHTML('#jobsList',rows.map(jobCard).join('')||empty('No jobs match this filter yet.'));}
async function loadApps(){
  const rows=await api('/api/applications'); allApps=Array.isArray(rows)?rows:[]; fillSelects();
  setHTML('#appsList',rows.length?`<div class="app-row header"><span>ROLE</span><span>COMPANY</span><span>FIT</span><span>STATUS</span><span>ACTION</span></div>`+rows.map(a=>`<div class="app-row"><div><b>${esc(a.title)}</b></div><div>${esc(a.company)}</div><div>${Number(a.score||0).toFixed(0)}%</div><div><span class="status ${esc(a.status)}">${esc(a.status.replaceAll('_',' ').toUpperCase())}</span></div><div class="row-actions"><button class="mini-btn" data-action="tailor" data-id="${a.id}">Tailor</button><button class="mini-btn" data-action="inspect" data-id="${a.id}">Inspect</button></div></div>`).join(''):empty('No applications yet. Open Jobs and press Prepare on a role to create your first draft.',`<button class="primary" data-view-jump="opportunities" style="margin-top:14px">Browse jobs</button>`));
}
const profileFields=[['name','Full name'],['headline','Professional headline'],['email','Email'],['phone','Phone'],['location','Location'],['address','Address'],['linkedin','LinkedIn'],['github','GitHub'],['website','Portfolio / website'],['skills','Skills'],['projects','Projects'],['experience','Experience'],['education','Education'],['preferences','Job preferences'],['work_authorization','Work authorization'],['sponsorship','Visa sponsorship requirement'],['salary','Salary expectation']];
async function loadProfile(){
  const p=await api('/api/profile'); const vals=profileFields.map(([k])=>p[k]||''); const done=vals.filter(v=>String(v).trim()).length;
  const bar=$('#profileBar'); if(bar) bar.style.width=Math.round(done/profileFields.length*100)+'%'; setText('#profilePercent',Math.round(done/profileFields.length*100)+'% complete');
  profileDone=!!(String(p.name||'').trim()&&String(p.email||'').trim()); markSteps(); const ini=(p.name||'').split(/\s+/).filter(Boolean).slice(0,2).map(x=>x[0].toUpperCase()).join(''); if(ini) setText('#avatar',ini);
  const rn=$('#resumeName'); if(rn) rn.textContent = p.resume_filename ? `✓ On file: ${p.resume_filename}` : 'No resume on file yet';
  setHTML('#profileForm',profileFields.map(([k,l])=>`<div class="field ${['skills','projects','experience','education','preferences'].includes(k)?'full':''}"><label>${l}</label>${['skills','projects','experience','education','preferences'].includes(k)?`<textarea data-key="${k}" placeholder="Add ${l.toLowerCase()}...">${esc(p[k]||'')}</textarea>`:`<input data-key="${k}" value="${esc(p[k]||'')}" placeholder="${esc(l)}">`}</div>`).join(''));
}
function fillProfile(p){
  const filled=[],missing=[]; const core=[['name','name'],['email','email'],['phone','phone'],['skills','skills'],['experience','experience'],['education','education'],['projects','projects']];
  profileFields.forEach(([k])=>{const e=$(`[data-key="${k}"]`); if(e && p[k]){e.value=p[k]; e.closest('.field')?.classList.add('filled');}});
  core.forEach(([k,l])=>((p[k]&&String(p[k]).trim())?filled:missing).push(l));
  const rep=$('#importReport'); if(rep){rep.classList.add('show'); rep.innerHTML=`<b>Filled:</b> ${filled.map(esc).join(', ')||'nothing'}.`+(missing.length?` <span class="miss">Not found: ${missing.map(esc).join(', ')}. Check the resume headings or add them by hand.</span>`:'')+` Review each field, then press Save profile.`; rep.scrollIntoView({behavior:'smooth',block:'center'});}
  const vals=profileFields.map(([k])=>$(`[data-key="${k}"]`)?.value||''); const done=vals.filter(v=>String(v).trim()).length; const pct=Math.round(done/profileFields.length*100); const bar=$('#profileBar'); if(bar) bar.style.width=pct+'%'; setText('#profilePercent',pct+'% complete');
}
async function importResume(){
  const input=$('#resumeFile'); const file=input?.files?.[0]; if(!file){toast('Choose a PDF or DOCX resume first.','error');return;}
  const b=$('#importResume'); if(b){b.disabled=true;b.textContent='Parsing resume…';}
  try{const form=new FormData();form.append('file',file);const r=await api('/api/profile/import-resume',{method:'POST',body:form});fillProfile(r.profile||{});const rn=$('#resumeName'); if(rn && r.profile?.filename) rn.textContent=`✓ On file: ${r.profile.filename}`; toast(r.message||'Resume imported. Review the fields and save your profile.','success');}
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
async function inspect(id){try{const r=await api(`/api/applications/${id}/inspect`,{method:'POST'});const msg=r.ready_for_submission?`ATS ready · ${r.fields?.length||r.inputs||0} fields detected`:`Human action required${r.blocked_signals?.length?': '+r.blocked_signals.join(', '):''}`;toast(msg,r.ready_for_submission?'success':'info');nav('intelligence');const box=$('#atsResult');if(box)box.textContent=JSON.stringify(r,null,2);}catch(e){toast(`Inspection: ${e.message}`,'error')}}

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

function statusMeta(status){
  const m={submitted:['ok','Submitted'],dry_run:['info','Dry run — nothing sent'],inspected:['info','Inspected'],needs_human:['warn','Needs you'],submission_error:['warn','Error'],mapped:['ok','Mapped']};
  return m[status]||['info',status||'Done'];
}
function badge(cls,text){return `<span class="rbadge ${cls}">${esc(text)}</span>`}
function chipList(items,cls){return (items&&items.length)?items.map(x=>`<span class="chip ${cls||''}">${esc(x)}</span>`).join(' '):'<span class="muted-inline">None</span>'}

function renderBrowserResult(el, r){
  const [cls,label]=statusMeta(r.status);
  let html=`<div class="result-head"><span class="rbadge ${cls}">${esc(label)}</span>${r.title?`<span class="result-title">${esc(r.title)}</span>`:''}</div>`;
  if(r.stops?.length) html+=`<div class="notice warn"><b>Stopped for you:</b> ${r.stops.map(esc).join('; ')}</div>`;
  if(r.reason && !r.stops?.length) html+=`<div class="notice warn">${esc(r.reason)}</div>`;
  if(r.confirmation) html+=`<div class="notice ok"><b>Confirmed:</b> ${esc(r.confirmation)}</div>`;
  if(r.fields?.length){
    html+=`<div class="field-table"><div class="field-row head"><span>Field</span><span>Detected as</span><span>Action</span></div>`;
    html+=r.fields.map(f=>{
      const a=f.action, ai=a==='needs_you'?'⚠️':(a==='skip'?'–':'✓');
      return `<div class="field-row"><span>${esc(f.label)}${f.required?' <em>*</em>':''}</span><span>${esc(f.kind)}</span><span class="fa ${a}">${ai} ${esc(a.replace('_',' '))}</span></div>`;
    }).join('');
    html+='</div>';
  }
  if(r.unresolved?.length) html+=`<div class="notice warn"><b>Needs your input:</b> ${r.unresolved.map(esc).join('; ')}</div>`;
  if(r.filled?.length) html+=`<div class="notice ok"><b>Filled:</b> ${r.filled.map(esc).join(', ')}</div>`;
  if(r.screenshot) html+=`<img class="result-shot" src="data:image/jpeg;base64,${r.screenshot}" alt="Page screenshot">`;
  el.innerHTML=html; el.classList.add('rendered');
}

function renderAtsResult(el, r){
  const [cls,label]=statusMeta(r.status);
  const rows=Object.entries(r.mapping||{});
  let html=`<div class="result-head"><span class="rbadge ${cls}">${esc(label)}</span><span class="result-title">${esc(r.platform||'generic')}</span></div>`;
  html+=`<div class="field-table"><div class="field-row head"><span>Field</span><span>Value from your profile</span></div>`;
  html+=rows.map(([k,v])=>`<div class="field-row"><span>${esc(k)}</span><span>${v?esc(v):'<em class="muted-inline">not set</em>'}</span></div>`).join('')||'<div class="field-row"><span colspan=2>No fields</span></div>';
  html+='</div>';
  if(r.unresolved?.length) html+=`<div class="notice warn"><b>Missing for required fields:</b> ${r.unresolved.map(esc).join(', ')}</div>`;
  el.innerHTML=html; el.classList.add('rendered');
}

function scoreRing(score){
  const pct=Math.max(0,Math.min(100,score||0)); const c=2*Math.PI*26;
  const color = pct>=70?'var(--ok)':pct>=40?'var(--warn)':'var(--danger)';
  return `<svg class="score-ring" viewBox="0 0 64 64"><circle cx="32" cy="32" r="26" fill="none" stroke="var(--surface2)" stroke-width="7"/><circle cx="32" cy="32" r="26" fill="none" stroke="${color}" stroke-width="7" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c-(c*pct/100)}" transform="rotate(-90 32 32)"/><text x="32" y="37" text-anchor="middle" font-size="17" font-weight="800" fill="var(--text)">${Math.round(pct)}</text></svg>`;
}
function renderTailorResult(el, r){
  let html=`<div class="score-row">${scoreRing(r.ats_score)}<div><b>Keyword alignment</b><p class="muted">How much of the job's language already appears in your profile.</p></div></div>`;
  html+=`<div class="kw-block"><small>MATCHED</small><div class="chips">${chipList(r.matched_keywords,'ok')}</div></div>`;
  html+=`<div class="kw-block"><small>NOT IN YOUR PROFILE</small><div class="chips">${chipList(r.missing_keywords,'warn')}</div></div>`;
  if(r.bullet_alignment?.length){
    html+=`<div class="kw-block"><small>YOUR EXPERIENCE BULLETS</small>`+r.bullet_alignment.slice(0,6).map(b=>`<div class="bullet-row"><span>${esc((b.original||'').slice(0,90))}</span>${badge(b.alignment_score>=50?'ok':'warn',(b.alignment_score||0)+'%')}</div>`).join('')+'</div>';
  }
  el.innerHTML=html; el.classList.add('rendered');
}

function renderTelemetryResult(el, r){
  let html=`<div class="score-row"><div class="stat-block"><b>${r.observed_open_roles ?? 0}</b><small>open roles seen</small></div><div class="stat-block"><b>${r.observed_applications ?? 0}</b><small>your applications</small></div></div>`;
  const statuses=Object.entries(r.application_statuses||{});
  if(statuses.length) html+=`<div class="kw-block"><small>APPLICATION STATUSES</small><div class="chips">${statuses.map(([k,v])=>badge('info',`${k}: ${v}`)).join('')}</div></div>`;
  if(r.limitations?.length) html+=`<div class="notice info">${r.limitations.map(esc).join(' ')}</div>`;
  el.innerHTML=html; el.classList.add('rendered');
}

function renderTokenResult(el, r){
  const exp=r.expires_at?new Date(r.expires_at*1000).toLocaleTimeString():'';
  const short=(r.token||'').slice(0,18)+'…'+(r.token||'').slice(-10);
  el.innerHTML=`<div class="notice ok">Token issued, expires ${esc(exp)}.</div><div class="token-row"><code>${esc(short)}</code><button class="mini-btn" id="copyTokenBtn">Copy full token</button></div>`;
  el.classList.add('rendered');
  $('#copyTokenBtn')?.addEventListener('click',()=>{navigator.clipboard?.writeText(r.token||'').then(()=>toast('Token copied','success'))});
}

function renderNegotiationResult(el, r){
  const a=r.analysis||{};
  el.innerHTML=`<div class="score-row"><div class="stat-block"><b>${(a.current_offer||0).toLocaleString()}</b><small>current offer</small></div><div class="stat-block"><b>${(a.reference_midpoint||0).toLocaleString()}</b><small>market midpoint</small></div><div class="stat-block"><b>${(a.counter_reference||0).toLocaleString()}</b><small>suggested ask</small></div></div>`+
    `<div class="kw-block"><small>SUGGESTED SCRIPT</small><p class="script-box">${esc(r.script||'')}</p></div>`+
    (a.note?`<div class="notice info">${esc(a.note)}</div>`:'');
  el.classList.add('rendered');
}

async function runFeature(id, path, opts={}, render=null){
  const el=$(id); if(el){el.classList.remove('rendered'); el.textContent='Working…';}
  try{
    const r=await api(path,opts);
    if(el){ if(render) render(el,r); else el.textContent=JSON.stringify(r,null,2); }
    toast('Completed successfully','success'); return r;
  }catch(e){ if(el){el.classList.remove('rendered'); el.textContent=e.message;} toast(e.message,'error'); return null; }
}
$('#atsMapDemo')?.addEventListener('click',async()=>{const id=Number($('#atsAppId')?.value||0);if(!id)return toast('Choose an application first','error');const fields=[{name:'first_name',label:'First Name',required:true},{name:'last_name',label:'Last Name',required:true},{name:'email',label:'Email Address',required:true},{name:'phone',label:'Phone Number'},{name:'city',label:'City',required:true},{name:'resume',label:'Resume',type:'file',required:true}];await runFeature('#atsResult',`/api/applications/${id}/ats-map`,{method:'POST',body:JSON.stringify(fields)},renderAtsResult);});
$('#tailorAnalyze')?.addEventListener('click',async()=>{const id=Number($('#tailorAppId')?.value||0);if(!id)return toast('Choose an application first','error');await runFeature('#tailorResult',`/api/applications/${id}/tailor/analyze`,{method:'POST'},renderTailorResult);});
$('#telemetryBtn')?.addEventListener('click',async()=>{const c=($('#telemetryCompany')?.value||'').trim();if(!c)return toast('Enter a company name','error');await runFeature('#telemetryResult',`/api/companies/${encodeURIComponent(c)}/telemetry`,{method:'POST'},renderTelemetryResult);});
$('#tokenBtn')?.addEventListener('click',async()=>{await runFeature('#tokenResult','/api/candidate/token',{method:'POST'},renderTokenResult);});
$('#interviewBtn')?.addEventListener('click',async()=>{const id=Number($('#interviewJobId')?.value||0);if(!id)return toast('Choose a job first','error');const r=await runFeature('#interviewResult',`/api/interviews/mock?job_id=${id}`,{method:'POST'});if(r){const box=$('#interviewResult');if(box){box.classList.add('rendered');box.innerHTML=(r.questions||[]).map((q,i)=>`<article class="interview-card"><small>${esc((q.type||'question').toUpperCase())}</small><h4>${esc(q.question)}</h4>${q.focus?`<p class="muted">Focus: ${esc(q.focus)}</p>`:''}</article>`).join('');}}});

$('#browserExecuteBtn')?.addEventListener('click',async()=>{const id=Number($('#browserAppId')?.value||0);if(!id)return toast('Choose an application first','error');const dry=$('#browserDryRun')?.checked!==false;const r=await runFeature('#browserResult',`/api/applications/${id}/browser/execute?dry_run=${dry}`,{method:'POST'},renderBrowserResult);if(r)toast(dry?'Dry run complete — nothing was submitted.':(r.submitted?'Application submitted.':'Stopped — see details.'),r.submitted?'success':'info');});
$('#negotiateBtn')?.addEventListener('click',async()=>{const id=Number($('#offerAppId')?.value||0);const offer=Number($('#offerAmount')?.value||0),low=Number($('#marketLow')?.value||0),high=Number($('#marketHigh')?.value||0);if(!id||!offer||!low)return toast('Choose an application and enter the offer and market range','error');await runFeature('#negotiationResult',`/api/applications/${id}/negotiation`,{method:'POST',body:JSON.stringify({offer,market_low:low,market_high:high})},renderNegotiationResult);});

$('#themeToggle')?.addEventListener('click',()=>{const cur=document.documentElement.dataset.theme||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');const next=cur==='dark'?'light':'dark';document.documentElement.dataset.theme=next;try{localStorage.setItem('jh-theme',next)}catch(e){}});
$('#moreTab')?.addEventListener('click',()=>{$('.sidebar')?.classList.add('open');document.body.classList.add('sidebar-open')});
$('#scrim')?.addEventListener('click',()=>{$('.sidebar')?.classList.remove('open');document.body.classList.remove('sidebar-open')});

document.addEventListener('click',e=>{const j=e.target.closest?.('[data-view-jump]');if(j)nav(j.dataset.viewJump)});
