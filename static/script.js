// ── State ─────────────────────────────────────────────
let currentStep    = 1;
let skills         = [];
let lastFilename   = null;
let activeDocType  = 'resume';
let selectedModel  = 'llama-3.3-70b-versatile';
let activeTemplate = 'executive';
let pendingTemplate= 'executive';

const STEP_REQUIRED = {
  1:[
    {id:'name',        label:'Full Name'},
    {id:'target_role', label:'Target Role'},
    {id:'email',       label:'Email', validator:v=>/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)},
  ]
};

// ── 10 Template definitions ───────────────────────────
const TEMPLATES = [
  { id:'executive', name:'Executive Purple', emoji:'👑',
    desc:'Two-column premium layout. Rich purple gradient header, skills sidebar, polished serif name.',
    preview:['#4c1d95','#6d28d9','#f5f0ff'] },
  { id:'minimal',   name:'Clean Minimal',   emoji:'⬜',
    desc:'Timeless black & white. Garamond serif name, clean rules, ATS-perfect single column.',
    preview:['#111111','#555555','#ffffff'] },
  { id:'modern',    name:'Modern Teal',     emoji:'💎',
    desc:'Bold teal gradient header, card-based entries, fresh two-column grid.',
    preview:['#0f766e','#0d9488','#f0fdfa'] },
  { id:'corporate', name:'Corporate Navy',  emoji:'🏢',
    desc:'Deep navy header, left blue accent bars, structured and authoritative.',
    preview:['#0f172a','#3b82f6','#eff6ff'] },
  { id:'creative',  name:'Creative Dark',   emoji:'🌙',
    desc:'Dark-mode timeline layout with neon-purple monospace accents. Stand out.',
    preview:['#09090b','#a78bfa','#18181b'] },
  { id:'academic',  name:'Warm Academic',   emoji:'📚',
    desc:'Amber serif with dotted dividers. Ideal for research, academia, teaching.',
    preview:['#78350f','#92400e','#fde68a'] },
  { id:'rosegold',  name:'Rose Gold',       emoji:'🌸',
    desc:'Pink-rose gradient header, sidebar layout, Cormorant Garamond elegance.',
    preview:['#9f1239','#be185d','#fce7f3'] },
  { id:'forest',    name:'Forest Green',    emoji:'🌿',
    desc:'Earthy green gradient, Merriweather serif, nature-inspired and trustworthy.',
    preview:['#14532d','#16a34a','#dcfce7'] },
  { id:'slatepro',  name:'Slate Pro',       emoji:'🔷',
    desc:'Split dark/medium header, indigo gradient accent bar. Subtle luxury feel.',
    preview:['#1e293b','#334155','#6366f1'] },
  { id:'cyber',     name:'Neon Cyber',      emoji:'⚡',
    desc:'Orbitron font, electric neon-on-dark, glowing accents. Ultra-futuristic.',
    preview:['#8c7a5a','#f8f1e9','#5c4f3d'] },
    {
    id: 'classic',name: 'Classic Clean',emoji: '📄',
    desc: 'Traditional clean one-column layout. Simple, professional and ATS friendly.',
    preview: ['#ffffff', '#000000', '#555555']
  },
  {
    id: 'professional', name: 'Professional Blue', emoji: '💼',
    desc: 'Modern blue-themed layout with a professional appearance.',
    preview: ['#003366', '#0055aa', '#cce5ff']
  },
  {
    id: 'executive_brown', name: 'Executive Brown', emoji: '🪵',
    desc: 'Warm brown-themed layout with an executive feel.',
    preview: ['#5d4037', '#8d6e63', '#d7ccc8']
  },
  {
    id: 'creative_decor', name: 'Creative Decor', emoji: '🎨',
    desc: 'Decorative layout with creative elements and a unique aesthetic.',
    preview: ['#2a2a2a', '#777', '#fdfaf0']
  },
  {
    id: 'modern_sidebar', name: 'Modern Sidebar', emoji: '📊',
    desc: 'Clean two-column layout with a modern sidebar.',
    preview: ['#4f46e5', '#f1f5f9', '#f8f9fa']
  }
];

// ── Canvas BG ─────────────────────────────────────────
(function(){
  const canvas=document.getElementById('bgCanvas');
  const ctx=canvas.getContext('2d');
  let orbs=[],W,H;
  function resize(){W=canvas.width=window.innerWidth;H=canvas.height=window.innerHeight;}
  resize(); window.addEventListener('resize',resize);
  function ga(){return getComputedStyle(document.body).getPropertyValue('--accent').trim()||'#6c63ff';}
  function ga2(){return getComputedStyle(document.body).getPropertyValue('--accent2').trim()||'#ff6b9d';}
  function spawn(){
    orbs=[];
    for(let i=0;i<5;i++) orbs.push({x:Math.random()*W,y:Math.random()*H,
      vx:(Math.random()-.5)*.3,vy:(Math.random()-.5)*.3,r:180+Math.random()*220,
      col:i%2===0?ga():ga2(),alpha:.04+Math.random()*.04});
  }
  spawn();
  function draw(){
    ctx.clearRect(0,0,W,H);
    orbs.forEach(o=>{
      const g=ctx.createRadialGradient(o.x,o.y,0,o.x,o.y,o.r);
      g.addColorStop(0,o.col+'cc'); g.addColorStop(1,o.col+'00');
      ctx.globalAlpha=o.alpha; ctx.fillStyle=g;
      ctx.beginPath(); ctx.arc(o.x,o.y,o.r,0,Math.PI*2); ctx.fill();
      o.x+=o.vx; o.y+=o.vy;
      if(o.x<-o.r) o.x=W+o.r; if(o.x>W+o.r) o.x=-o.r;
      if(o.y<-o.r) o.y=H+o.r; if(o.y>H+o.r) o.y=-o.r;
    });
    ctx.globalAlpha=1; requestAnimationFrame(draw);
  }
  draw();
  window._recolorOrbs=()=>orbs.forEach((o,i)=>{o.col=i%2===0?ga():ga2();});
})();

// ── Theme / Font ──────────────────────────────────────
function setTheme(t){
  document.body.dataset.theme=t;
  document.querySelectorAll('.theme-btn').forEach(b=>b.classList.toggle('active',b.dataset.theme===t));
  setTimeout(window._recolorOrbs,50); showToast('Theme changed ✦','success');
}
function setFont(f){
  document.body.dataset.font=f;
  document.querySelectorAll('.font-btn').forEach(b=>b.classList.toggle('active',b.dataset.font===f));
  showToast('Font updated','success');
}
function toggleSettings(){ document.getElementById('settingsDrawer').classList.toggle('hidden'); }

// ── Toast ─────────────────────────────────────────────
function showToast(msg,type=''){
  const t=document.getElementById('toast');
  t.textContent=msg; t.className=`toast ${type}`; t.classList.remove('hidden');
  clearTimeout(t._to); t._to=setTimeout(()=>t.classList.add('hidden'),3200);
}

function spin(id,on){ const e=document.getElementById(id); if(e) e.classList.toggle('hidden',!on); }

// ── Validation ────────────────────────────────────────
function validateStep(n){
  const rules=STEP_REQUIRED[n]; if(!rules) return true;
  let ok=true; const missed=[];
  rules.forEach(r=>{
    const el=document.getElementById(r.id);
    const val=el?el.value.trim():'';
    const pass=r.validator?r.validator(val):val.length>0;
    const w=document.querySelector(`[data-field="${r.id}"]`);
    if(w) w.classList.toggle('error',!pass);
    if(!pass){ok=false;missed.push(r.label);}
  });
  if(!ok){
    document.getElementById('modalBody').innerHTML=
      'Please fill in:<br><br>'+missed.map(m=>`<b>• ${m}</b>`).join('<br>');
    document.getElementById('modalOverlay').classList.remove('hidden');
  }
  return ok;
}
function clearErr(id){ const w=document.querySelector(`[data-field="${id}"]`); if(w) w.classList.remove('error'); }
function closeModal(){ document.getElementById('modalOverlay').classList.add('hidden'); }

// ── Navigation ────────────────────────────────────────
function nextStep(from,to){ if(!validateStep(from)) return; goStep(to); }
function goStep(n){
  document.getElementById(`step${currentStep}`).classList.remove('active');
  document.querySelectorAll('.nav-step').forEach(el=>{
    const s=+el.dataset.step;
    el.classList.remove('active','done');
    if(s===n) el.classList.add('active');
    else if(s<n) el.classList.add('done');
  });
  document.querySelectorAll('.dot').forEach(d=>{
    const s=+d.dataset.step;
    d.classList.remove('active','done');
    if(s===n) d.classList.add('active');
    else if(s<n) d.classList.add('done');
  });
  currentStep=n;
  document.getElementById(`step${n}`).classList.add('active');
  window.scrollTo({top:0,behavior:'smooth'});
}

// ── Data collector ────────────────────────────────────
function collectData(){
  return {
    name:v('name'), target_role:v('target_role'), experience_years:v('experience_years'),
    email:v('email'), phone:v('phone'), location:v('location'),
    linkedin:v('linkedin'),linkedinUser:v('linkedinUser'), github:v('github'), achievements:v('achievements'), summary:v('summary'),
    skills:[...skills], languages:v('languages'), tools:v('tools'), soft_skills:v('soft_skills'),
    experience:collectExperience(), education:collectEducation(),
    certifications:collectCerts(), projects:collectProjects(),
  };
}
const v=id=>{const e=document.getElementById(id);return e?e.value.trim():'';}

// ── AI helpers ────────────────────────────────────────
async function generateSummary(){
  spin('spnSummary',true); document.getElementById('btnGenSummary').disabled=true;
  try{
    const r=await fetch('/api/enhance-summary',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name:v('name'),target_role:v('target_role'),experience_years:v('experience_years'),
        skills:[...skills],achievements:v('achievements')})});
    const d=await r.json();
    if(d.success){document.getElementById('summary').value=d.summary;showToast('✦ Summary generated!','success');}
    else showToast('Error: '+d.error,'error');
  }catch{showToast('Network error','error');}
  finally{spin('spnSummary',false);document.getElementById('btnGenSummary').disabled=false;}
}

async function suggestSkills(){
  spin('spnSkills',true);
  const btn=document.querySelector('[onclick="suggestSkills()"]'); btn.disabled=true;
  try{
    const r=await fetch('/api/suggest-skills',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({role:v('target_role'),existing_skills:skills})});
    const d=await r.json();
    if(d.success&&d.skills.length){d.skills.forEach(s=>addSkillChip(s));showToast(`✦ Added ${d.skills.length} skills!`,'success');}
    else showToast('Could not suggest skills','error');
  }catch{showToast('Network error','error');}
  finally{spin('spnSkills',false);btn.disabled=false;}
}

async function enhanceBullet(inputEl,jobTitle,company){
  const raw=inputEl.value.trim(); if(!raw){showToast('Write a bullet point first','error');return;}
  inputEl.disabled=true;
  try{
    const r=await fetch('/api/enhance-bullet',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({job_title:jobTitle,company,bullet:raw})});
    const d=await r.json();
    if(d.success){inputEl.value=d.bullet;inputEl.style.borderColor='var(--accent)';showToast('✦ Bullet enhanced!','success');
      setTimeout(()=>inputEl.style.borderColor='',2000);}
    else showToast(d.error,'error');
  }catch{showToast('Network error','error');}
  finally{inputEl.disabled=false;}
}

async function checkATS(){
  const jd = document.getElementById('jobDesc').value.trim();
  if(!jd){ showToast('Paste a job description first','error'); return; }

  spin('spnATS', true);
  const btn = document.querySelector('[onclick="checkATS()"]');
  btn.disabled = true;

  try{
    const resumeData = collectData();
    const res = await fetch('/api/ats-score', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        resume: resumeData,
        job_description: jd
      })
    });

    if(!res.ok){
      const errText = await res.text();
      console.error('ATS HTTP error:', res.status, errText);
      showToast('Server error: ' + res.status, 'error');
      return;
    }

    const d = await res.json();
    if(d.success){
      renderATS(d.result);
    } else {
      console.error('ATS failed:', d.error);
      showToast('ATS failed: ' + (d.error || 'unknown'), 'error');
    }
  } catch(e){
    console.error('ATS fetch error:', e);
    showToast('Network error: ' + e.message, 'error');
  } finally {
    spin('spnATS', false);
    btn.disabled = false;
  }
}

function renderATS(r){
  const el=document.getElementById('atsResult'); el.classList.remove('hidden');
  const sc=r.score||0;
  const col=sc>=70?'var(--green)':sc>=40?'var(--gold)':'var(--red)';
  const verdict=sc>=70?'🟢 Strong match!':sc>=40?'🟡 Moderate match.':'🔴 Weak match.';
  el.innerHTML=`<div class="ats-score-row"><div class="ats-ring" style="border-color:${col}">
    <span class="ring-num" style="color:${col}">${sc}</span><span class="ring-lbl">/ 100</span></div>
    <span class="ats-desc">${verdict}</span></div>
    ${(r.matched_keywords||[]).length?`<div class="ats-kw-label">Matched</div><div class="ats-tags">${(r.matched_keywords||[]).map(k=>`<span class="ats-tag ats-match">✓ ${k}</span>`).join('')}</div>`:''}
    ${(r.missing_keywords||[]).length?`<div class="ats-kw-label">Missing</div><div class="ats-tags">${(r.missing_keywords||[]).map(k=>`<span class="ats-tag ats-miss">✗ ${k}</span>`).join('')}</div>`:''}
    ${(r.suggestions||[]).length?`<div class="ats-kw-label">Suggestions</div><ul class="ats-sug-list">${(r.suggestions||[]).map(s=>`<li>${s}</li>`).join('')}</ul>`:''}`;
}

// ── Doc type ──────────────────────────────────────────
const DOC_LABELS={resume:'📄 Resume',coverLetter:'✉️ Cover Letter',portfolio:'🎨 Portfolio Bio',linkedin:'💼 LinkedIn'};
function setActiveDoc(type){
  activeDocType=type;
  document.querySelectorAll('.doc-card').forEach(d=>d.classList.toggle('active',d.dataset.doc===type));
  document.getElementById('genActiveLbl').textContent=`✨ Generate ${DOC_LABELS[type]}`;
}

// ── GENERATE (triggers direct preview for resume) ──────
async function generateActive(){
  await generateOne(activeDocType,'spnGenActive',document.getElementById('btnGenActive'));
}

async function generateAll(){
  const types=['resume','coverLetter','portfolio','linkedin'];
  const btn=document.getElementById('btnGenAll'); btn.disabled=true; spin('spnGenAll',true);
  for(let i=0;i<types.length;i++){
    setActiveDoc(types[i]);
    await generateOne(types[i],null,null);
    if(i<types.length-1) await new Promise(r=>setTimeout(r,600));
  }
  btn.disabled=false; spin('spnGenAll',false); showToast('✦ All documents generated!','success');
}

async function generateOne(type,spinId,btn){
  if(spinId) spin(spinId,true);
  if(btn) btn.disabled=true;
  hideError();
  const role=v('gen_role')||v('target_role');
  const company=v('gen_company');
  const data=collectData();
  try{
    // For resume type: render visual preview directly, skip text output
    if(type==='resume'){
      await buildPreview(data);
      showToast('✦ Resume rendered!','success');
    } else {
      // For other docs: generate text and show in output box
      const r=await fetch('/api/generate-doc',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({type,data,role,company,model:selectedModel})});
      const d=await r.json();
      if(d.success){
        renderOutput(type,d.text);
        // Also show preview section (so template picker is visible)
        showPreviewSection();
        showToast(`✦ ${DOC_LABELS[type]} generated!`,'success');
      } else showError(d.error||'Generation failed');
    }
  }catch(e){showError('Network error: '+e.message);}
  finally{if(spinId) spin(spinId,false);if(btn) btn.disabled=false;}
}

function showError(msg){const e=document.getElementById('genError');e.textContent='⚠ '+msg;e.classList.remove('hidden');}
function hideError(){document.getElementById('genError').classList.add('hidden');}

// ── BUILD PREVIEW (core renderer) ─────────────────────
async function buildPreview(data){
  const loadingEl = document.getElementById('previewLoading');
  const frame = document.getElementById('previewFrame');

  showPreviewSection();
  loadingEl.classList.remove('hidden');
  frame.style.opacity = '0';

  try{
    const payload = {...(data || collectData()), template: activeTemplate};
    const r = await fetch('/api/generate-resume', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const d = await r.json();
    if(d.success){
      lastFilename = d.filename;
      document.getElementById('btnDownload').classList.remove('hidden');
      document.getElementById('btnDownloadHtml').classList.remove('hidden');
      frame.onload = () => {
        setTimeout(() => {
          loadingEl.classList.add('hidden');
          frame.style.transition = 'opacity .4s';
          frame.style.opacity = '1';
          scalePreviewFrame();
        }, 250);
        // Re-measure after fonts and images settle
        setTimeout(scalePreviewFrame, 600);
        setTimeout(scalePreviewFrame, 1200);
      };

      frame.srcdoc = d.html;

      // Hard fallback
      setTimeout(() => {
        if(frame.style.opacity === '0') {
          loadingEl.classList.add('hidden');
          frame.style.opacity = '1';
          scalePreviewFrame();
        }
      }, 4000);

    } else {
      loadingEl.classList.add('hidden');
      frame.style.opacity = '1';
      showError(d.error);
    }
  } catch(e) {
    loadingEl.classList.add('hidden');
    frame.style.opacity = '1';
    showError('Network error: ' + e.message);
  }
}

function showPreviewSection(){
  document.getElementById('previewSection').classList.remove('hidden');
  setTimeout(scalePreviewFrame, 50);
}

function downloadResumeHTML(){
  if(lastFilename) window.open(`/api/download/${lastFilename}`,'_blank');
}

async function downloadResumePDF(){
  if(!lastFilename){ showToast('Generate a resume first','error'); return; }
  const btn = document.getElementById('btnDownload');
  const origText = btn.textContent;
  btn.textContent = '⏳ Generating PDF…';
  btn.disabled = true;

  try {
    const response = await fetch(`/api/download-pdf/${lastFilename}`);
    if (!response.ok) {
      const err = await response.json().catch(() => ({error: 'Unknown error'}));
      showToast('PDF failed: ' + (err.error || response.statusText), 'error');
      return;
    }
    const blob = await response.blob();
    if (blob.size < 1000) {
      showToast('PDF too small — generation may have failed', 'error');
      return;
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = lastFilename.replace('.html', '.pdf');
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('✦ PDF downloaded!', 'success');
  } catch(e) {
    showToast('Download error: ' + e.message, 'error');
  } finally {
    btn.textContent = origText;
    btn.disabled = false;
  }
}

// ── Responsive preview iframe scaler ─────────────────
function scalePreviewFrame() {
  const wrap  = document.getElementById('previewScaleContainer');
  const frame = document.getElementById('previewFrame');
  if (!wrap || !frame) return;

  const A4_W = 794;

  // Get real content height from iframe
  let contentH = 1123;
  try {
    const fd = frame.contentDocument || frame.contentWindow?.document;
    if (fd && fd.body) {
      contentH = Math.max(fd.body.scrollHeight, fd.documentElement.scrollHeight, 1123);
    }
  } catch(e) {}

  // Calculate available width correctly:
  // Use the panel-chrome (parent panel) width, not the frame-wrap
  // because frame-wrap overflow:visible means clientWidth may be wrong
  const panelChrome = document.querySelector('#step6 .panel-chrome');
  const panelW = panelChrome ? panelChrome.clientWidth : 860;
  // Subtract: panel padding (32px each side = 64) + frame-wrap border+padding (10+12 each side = 44)
  const available = panelW - 64 - 44;
  const scale = Math.min(1, available / A4_W);

  frame.style.width           = A4_W + 'px';
  frame.style.height          = contentH + 'px';
  frame.style.transform       = `scale(${scale})`;
  frame.style.transformOrigin = 'top left';

  // Set container size to exactly the scaled frame size
  wrap.style.width    = Math.round(A4_W * scale) + 'px';
  wrap.style.height   = Math.round(contentH * scale) + 'px';
}

function scaleModalFrame() {
  const wrap  = document.getElementById('previewModalScaleContainer');
  const frame = document.getElementById('previewModalFrame');
  if (!wrap || !frame) return;

  const A4_W = 794;

  let contentH = 1123;
  try {
    const fd = frame.contentDocument || frame.contentWindow?.document;
    if (fd && fd.body) {
      contentH = Math.max(fd.body.scrollHeight, fd.documentElement.scrollHeight, 1123);
    }
  } catch(e) {}

  // Modal inner available space
  const modalEl = document.querySelector('.preview-modal');
  const modalW  = modalEl ? modalEl.clientWidth  : Math.min(window.innerWidth  - 40, 900);
  const modalH  = modalEl ? modalEl.clientHeight : Math.min(window.innerHeight - 40, 900);
  const availW  = modalW  - 32;   // subtract padding
  const availH  = modalH  - 60;   // subtract header bar

  const scale = Math.min(1, availW / A4_W, availH / contentH);

  frame.style.width           = A4_W + 'px';
  frame.style.height          = contentH + 'px';
  frame.style.transform       = `scale(${scale})`;
  frame.style.transformOrigin = 'top left';

  wrap.style.width    = Math.round(A4_W * scale) + 'px';
  wrap.style.height   = Math.round(contentH * scale) + 'px';
}

// Add to window resize listener (existing line):
window.addEventListener('resize', () => { scalePreviewFrame(); scaleModalFrame(); });

// ── Text output (non-resume docs) ─────────────────────
function typewrite(el,text,speed=8){
  el.textContent=''; let i=0;
  const cursor=document.createElement('span');
  cursor.className='cursor-blink'; cursor.textContent='|';
  el.appendChild(cursor);
  const iv=setInterval(()=>{
    if(i<text.length){el.insertBefore(document.createTextNode(text[i]),cursor);i++;el.scrollTop=el.scrollHeight;}
    else{clearInterval(iv);cursor.remove();}
  },speed);
}

function renderOutput(type,text){
  const container=document.getElementById('generatedOutputs');
  const existing=container.querySelector(`[data-doc-out="${type}"]`);
  if(existing) existing.remove();
  const div=document.createElement('div');
  div.className='gen-output'; div.dataset.docOut=type;
  div.innerHTML=`<div class="gen-output-head">
    <div class="gen-output-label">${DOC_LABELS[type]}</div>
    <button class="btn-copy" onclick="copyOutput(this,'${type}')">📋 Copy</button>
    </div><div class="gen-output-body" id="out-${type}"></div>`;
  container.appendChild(div);
  typewrite(document.getElementById(`out-${type}`),text);
  div.scrollIntoView({behavior:'smooth',block:'start'});
}

function copyOutput(btn,type){
  const el=document.getElementById(`out-${type}`); if(!el) return;
  navigator.clipboard.writeText(el.textContent);
  btn.textContent='✓ Copied!'; btn.classList.add('copied');
  setTimeout(()=>{btn.textContent='📋 Copy';btn.classList.remove('copied');},2000);
}

// ══════════════════════════════════════════════════════
// TEMPLATE PICKER
// ══════════════════════════════════════════════════════
function buildTplGrid(){
  const grid=document.getElementById('tplGrid'); grid.innerHTML='';
  TEMPLATES.forEach((tpl,idx)=>{
    const card=document.createElement('div');
    card.className='tpl-card'+(tpl.id===activeTemplate?' active':'');
    card.dataset.id=tpl.id;
    const swatches=tpl.preview.map(c=>`<div class="tpl-swatch" style="background:${c}"></div>`).join('');
    card.innerHTML=`
      <div class="tpl-card-swatches">${swatches}</div>
      <div class="tpl-card-top-row">
        <span class="tpl-card-emoji">${tpl.emoji}</span>
        ${tpl.id===activeTemplate?'<span class="tpl-active-tick">✓ Active</span>':''}
      </div>
      <div class="tpl-card-name">${tpl.name}</div>
      <div class="tpl-card-desc">${tpl.desc}</div>
      <div class="tpl-card-actions">
        <button class="tpl-btn-preview" onclick="previewTemplate('${tpl.id}','${tpl.name}',event)">👁 Preview</button>
        <button class="tpl-btn-select${tpl.id===activeTemplate?' selected':''}" onclick="selectTemplate('${tpl.id}',this,event)">
          ${tpl.id===activeTemplate?'✓ Selected':'Select'}</button>
      </div>`;
    card.addEventListener('click',()=>selectTemplate(tpl.id,card.querySelector('.tpl-btn-select')));
    // Staggered entrance
    card.style.animationDelay=`${idx*0.04}s`;
    grid.appendChild(card);
  });
}

function openTplModal(){
  pendingTemplate=activeTemplate;
  buildTplGrid();
  const ov=document.getElementById('tplOverlay');
  ov.classList.remove('hidden');
  requestAnimationFrame(()=>ov.classList.add('visible'));
}

function closeTplModal(e){
  if(e&&e.target!==document.getElementById('tplOverlay')) return;
  const ov=document.getElementById('tplOverlay');
  ov.classList.remove('visible');
  setTimeout(()=>ov.classList.add('hidden'),300);
}

function selectTemplate(id,btn,e){
  if(e) e.stopPropagation();
  pendingTemplate=id;
  document.querySelectorAll('.tpl-card').forEach(c=>{
    const is=c.dataset.id===id;
    c.classList.toggle('active',is);
    const sb=c.querySelector('.tpl-btn-select');
    if(sb){sb.textContent=is?'✓ Selected':'Select';sb.classList.toggle('selected',is);}
    const tick=c.querySelector('.tpl-active-tick');
    if(tick) tick.remove();
    if(is){
      const top=c.querySelector('.tpl-card-top-row');
      if(top){const t=document.createElement('span');t.className='tpl-active-tick';t.textContent='✓ Active';top.appendChild(t);}
    }
  });
}

async function previewTemplate(id,name,e){
  if(e) e.stopPropagation();
  selectTemplate(id,null);
  const ov=document.getElementById('previewOverlay');
  document.getElementById('previewModalLabel').textContent=`Preview: ${name}`;
  document.getElementById('previewModalFrame').srcdoc=
    '<div style="font-family:sans-serif;text-align:center;padding:80px 40px;color:#999;background:#f8f8f8;min-height:100vh"><div style="font-size:32px;margin-bottom:16px">⏳</div><p>Generating preview…</p></div>';
  ov.classList.remove('hidden');
    setTimeout(scaleModalFrame, 50);
  requestAnimationFrame(()=>ov.classList.add('visible'));
  try{
    const r=await fetch('/api/generate-resume',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({...collectData(),template:id})});
    const d=await r.json();
     const frame = document.getElementById('previewModalFrame');
    frame.srcdoc = d.success ? d.html : `<p style="color:red;padding:20px">Error: ${d.error}</p>`;
    
    // Scale again after new content loads
    frame.onload = () => setTimeout(scaleModalFrame, 50);
    document.getElementById('previewModalFrame').srcdoc=d.success?d.html:
      `<p style="color:red;padding:20px">Error: ${d.error}</p>`;
  }catch{document.getElementById('previewModalFrame').srcdoc='<p style="color:red;padding:20px">Network error</p>';}
}

function closePreviewModal(e){
  if(e&&e.target!==document.getElementById('previewOverlay')) return;
  const ov=document.getElementById('previewOverlay');
  ov.classList.remove('visible');
  setTimeout(()=>ov.classList.add('hidden'),300);
}

function applyFromPreview(){
  closePreviewModal();
  applyTemplate();
}

// APPLY TEMPLATE — immediately re-renders preview
async function applyTemplate(){
  activeTemplate=pendingTemplate;
  const tpl=TEMPLATES.find(t=>t.id===activeTemplate);
  document.getElementById('activeTplName').textContent=tpl?tpl.name:activeTemplate;
  // Close modal
  const ov=document.getElementById('tplOverlay');
  ov.classList.remove('visible');
  setTimeout(()=>ov.classList.add('hidden'),300);
  showToast(`✦ "${tpl?.name}" applied!`,'success');
  // Immediately rebuild the preview — no extra click needed
  await buildPreview();
}

// ── Skills ────────────────────────────────────────────
function handleSkillKey(e){
  if(e.key==='Enter'){e.preventDefault();const inp=document.getElementById('skillInput');
    const val=inp.value.trim();if(val){addSkillChip(val);inp.value='';}}
}
function addSkillChip(name){
  if(skills.includes(name)) return; skills.push(name);
  const cloud=document.getElementById('skillsCloud');
  const hint=cloud.querySelector('.cloud-hint'); if(hint) hint.remove();
  const chip=document.createElement('div'); chip.className='skill-chip';
  chip.innerHTML=`${name} <span class="skill-del" onclick="removeSkill('${name.replace(/'/g,"\\'")}',this)">×</span>`;
  cloud.appendChild(chip);
}
function removeSkill(name,el){
  skills=skills.filter(s=>s!==name);
  const chip=el.closest('.skill-chip');
  chip.style.transition='all .2s'; chip.style.transform='scale(0)'; chip.style.opacity='0';
  setTimeout(()=>chip.remove(),200);
  if(skills.length===0) document.getElementById('skillsCloud').innerHTML='<span class="cloud-hint">Your skills will appear here…</span>';
}

// ── Experience ────────────────────────────────────────
let expCount=0;
const EXP_TYPES=['internship','part-time','full-time','research','freelance'];
function addExperience(){
  expCount++;const id=`exp${expCount}`;
  const div=document.createElement('div'); div.className='exp-card'; div.id=id;
  const typeBtns=EXP_TYPES.map((t,i)=>
    `<button class="exp-type-btn ${i===0?'active':''}" data-type="${t}" onclick="setExpType('${id}','${t}',this)">${t}</button>`
  ).join('');
  div.innerHTML=`<div class="exp-card-top">
    <div><div class="exp-card-label">Position #${expCount}</div>
    <div class="exp-type-btns" id="${id}-types">${typeBtns}</div></div>
    <button class="btn-remove" onclick="removeCard('${id}')">Remove</button></div>
    <div class="form-grid g2">
      <div class="field"><label>Job Title</label><input class="exp-title" placeholder="Frontend Developer Intern"/></div>
      <div class="field"><label>Company</label><input class="exp-company" placeholder="Google"/></div>
      <div class="field"><label>Location</label><input class="exp-location" placeholder="Bangalore, India"/></div>
      <div class="field"><label>Duration</label><input class="exp-duration" placeholder="May 2024 – Aug 2024"/></div>
    </div>
    <div class="bullets-head">Bullet Points <span style="text-transform:none;font-size:10px;opacity:.6;font-weight:400">— click ✦ AI to enhance</span></div>
    <div id="${id}-bullets">
      ${[1,2,3].map(()=>`<div class="bullet-row"><input class="bullet-input" type="text" placeholder="Describe an accomplishment…"/>
      <button class="btn-ai-bullet" onclick="enhanceBulletBtn('${id}',this)">✦ AI</button></div>`).join('')}
    </div>
    <button class="btn-add" style="margin-top:8px" onclick="addBulletRow('${id}')">＋ Add Bullet</button>`;
  document.getElementById('experienceList').appendChild(div);
}
function setExpType(cardId,type,btn){
  document.querySelectorAll(`#${cardId}-types .exp-type-btn`).forEach(b=>b.classList.toggle('active',b===btn));
}
function addBulletRow(id){
  const list=document.getElementById(`${id}-bullets`);
  const row=document.createElement('div'); row.className='bullet-row';
  row.innerHTML=`<input class="bullet-input" type="text" placeholder="Describe an accomplishment…"/>
    <button class="btn-ai-bullet" onclick="enhanceBulletBtn('${id}',this)">✦ AI</button>`;
  list.appendChild(row); list.lastElementChild.querySelector('input').focus();
}
function enhanceBulletBtn(cardId,btn){
  const card=document.getElementById(cardId);
  const inp=btn.previousElementSibling;
  btn.textContent='⟳'; btn.disabled=true;
  enhanceBullet(inp,card.querySelector('.exp-title')?.value||'',card.querySelector('.exp-company')?.value||'')
    .finally(()=>{btn.textContent='✦ AI';btn.disabled=false;});
}
function collectExperience(){
  return Array.from(document.querySelectorAll('#experienceList .exp-card')).map(c=>{
    const rawTitle = c.querySelector('.exp-title')?.value||'';
    const expType  = c.querySelector('.exp-type-btn.active')?.dataset.type||'';
    const title = rawTitle && expType ? rawTitle+' ('+expType+')' : rawTitle;
    return {
      title,
      company:  c.querySelector('.exp-company')?.value||'',
      location: c.querySelector('.exp-location')?.value||'',
      duration: c.querySelector('.exp-duration')?.value||'',
      bullets:  Array.from(c.querySelectorAll('.bullet-input')).map(i=>i.value).filter(v=>v.trim()),
    };
  });
}

// ── Education ─────────────────────────────────────────
let eduCount=0;
function addEducation(){
  eduCount++;const id=`edu${eduCount}`;
  const div=document.createElement('div'); div.className='exp-card'; div.id=id;
  div.innerHTML=`<div class="exp-card-top">
    <div class="exp-card-label">Education #${eduCount}</div>
    <button class="btn-remove" onclick="removeCard('${id}')">Remove</button></div>
    <div class="form-grid g2">
      <div class="field"><label>Degree &amp; Major</label><input class="edu-degree" placeholder="B.Tech Computer Science"/></div>
      <div class="field"><label>Institution</label><input class="edu-inst" placeholder="IIT Bombay"/></div>
      <div class="field"><label>Graduation Year</label><input class="edu-year" placeholder="2025"/></div>
      <div class="field"><label>GPA / Percentage</label><input class="edu-gpa" placeholder="8.5 / 85%"/></div>
    </div>`;
  document.getElementById('educationList').appendChild(div);
}
function collectEducation(){
  return Array.from(document.querySelectorAll('#educationList .exp-card')).map(c=>({
    degree:c.querySelector('.edu-degree')?.value||'',institution:c.querySelector('.edu-inst')?.value||'',
    graduation_year:c.querySelector('.edu-year')?.value||'',gpa:c.querySelector('.edu-gpa')?.value||'',
    achievements:c.querySelector('.edu-ach')?.value||'',
  }));
}

// ── Certifications ────────────────────────────────────
function addCert(){
  const container=document.getElementById('certList');
  const row=document.createElement('div'); row.style.cssText='display:flex;gap:8px;margin-bottom:8px';
  row.innerHTML=`<input type="text" class="cert-input" placeholder="AWS Certified Developer…"/>
    <button class="btn-remove" onclick="this.parentElement.remove()">✕</button>`;
  container.appendChild(row); row.querySelector('input').focus();
}
function collectCerts(){
  return Array.from(document.querySelectorAll('.cert-input')).map(i=>i.value).filter(v=>v.trim());
}

// ── Projects ──────────────────────────────────────────
let projCount=0;
function addProject(){
  projCount++;const id=`proj${projCount}`;
  const div=document.createElement('div'); div.className='exp-card'; div.id=id;
  div.innerHTML=`<div class="exp-card-top">
    <div class="exp-card-label">Project #${projCount}</div>
    <button class="btn-remove" onclick="removeCard('${id}')">Remove</button></div>
    <div class="form-grid g2">
      <div class="field"><label>Project Name</label><input class="proj-name" placeholder="EcoTrack App"/></div>
      <div class="field"><label>GitHub / Live Link</label><input class="proj-link" placeholder="github.com/…"/></div>
      <div class="field full"><label>Technologies Used</label>
        <input class="proj-tech" placeholder="React, Node.js, MongoDB…"/></div>
      <div class="field full"><label>Description</label>
        <textarea class="proj-desc" rows="2" placeholder="What did you build and what problem does it solve?"></textarea></div>
    </div>`;
  document.getElementById('projectList').appendChild(div);
}
function collectProjects(){
  return Array.from(document.querySelectorAll('#projectList .exp-card')).map(c=>({
    name:c.querySelector('.proj-name')?.value||'',tech_stack:c.querySelector('.proj-tech')?.value||'',
    description:c.querySelector('.proj-desc')?.value||'',link:c.querySelector('.proj-link')?.value||'',
    highlights:c.querySelector('.proj-hl')?.value||'',
  }));
}

function removeCard(id){
  const el=document.getElementById(id); if(!el) return;
  el.style.transition='all .25s'; el.style.opacity='0'; el.style.transform='translateY(-8px)';
  setTimeout(()=>el.remove(),250);
}

// ── Keyboard shortcuts ────────────────────────────────
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){ closeTplModal(); closePreviewModal(); }
});

// ── Init ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded',()=>{
  addExperience(); addEducation(); addProject();
});
