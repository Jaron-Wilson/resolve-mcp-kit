"""The browser page for the queue. All requests are relative, so it also works behind a proxy under a sub-path."""

PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Site videos</title><style>
:root{color-scheme:dark;--bg:#14161a;--card:#1d2025;--line:#2c3036;--txt:#e7e9ec;--dim:#959ca5;--acc:#4f9dff;--ok:#3ecf8e;--warn:#f5b942;--bad:#ef5b5b}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--txt)}
main{max-width:1100px;margin:0 auto;padding:20px 16px 60px}h1{font-size:21px;margin:0 0 4px}a{color:var(--acc);text-decoration:none}
.sub{color:var(--dim);margin:0 0 16px}h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);margin:24px 0 10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
label{display:block;font-size:12px;color:var(--dim);text-transform:uppercase;letter-spacing:.05em;margin:0 0 6px}
input,select,textarea{font:inherit;color:var(--txt);background:#191c21;border:1px solid var(--line);border-radius:9px;padding:9px 11px;width:100%}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--acc)}textarea{resize:vertical;min-height:64px}
.row{display:grid;grid-template-columns:2fr 1.6fr .9fr;gap:12px;margin-bottom:12px}.row2{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:12px}
@media(max-width:720px){.row,.row2{grid-template-columns:1fr}}
.seg{display:flex;gap:4px}.seg button{flex:1;min-width:0;padding:9px 4px}
button{font:inherit;font-size:13px;color:var(--txt);background:#262a30;border:1px solid var(--line);border-radius:8px;padding:7px 11px;cursor:pointer;white-space:nowrap}
button:hover{border-color:#4a5058}button.on{border-color:var(--acc);background:#1c2a3d}button:disabled{opacity:.5;cursor:wait}
button.pri{background:var(--acc);border-color:var(--acc);color:#081221;font-weight:650;padding:10px 20px;font-size:15px}
.actions{display:flex;align-items:center;gap:12px;margin-top:14px;flex-wrap:wrap}.msg{color:var(--dim)}.msg.bad{color:var(--bad)}
.job{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-bottom:10px}
.top{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.top .u{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}
.pill{font-size:12px;border:1px solid var(--line);border-radius:999px;padding:1px 9px;white-space:nowrap}
.pill.done{color:var(--ok);border-color:#1f4a37}.pill.failed{color:var(--bad);border-color:#5a2a2a}.pill.preparing,.pill.editing{color:var(--acc);border-color:#2b3f63}
.pill.waiting,.pill.queued{color:var(--warn);border-color:#5a4520}.pill.cancelled{color:var(--dim)}
.meta{color:var(--dim);font-size:13px;margin-top:4px;overflow-wrap:anywhere}.err{color:var(--bad);font-size:13px;margin-top:6px;overflow-wrap:anywhere}
.bar{height:5px;background:#2a2e34;border-radius:3px;overflow:hidden;margin-top:8px}.bar i{display:block;height:100%;background:var(--acc);transition:width .5s}
.btns{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}video{width:100%;border-radius:8px;margin-top:10px;background:#000}
pre{white-space:pre-wrap;font-size:12px;color:var(--dim);max-height:260px;overflow:auto;background:#111317;border-radius:8px;padding:10px;margin:10px 0 0}
.empty{color:var(--dim)}
</style></head><body><main>
<h1>Site videos</h1><p class="sub">Give it a link. It reads the site, writes a script, records the site in a browser, adds a voiceover and edits a promo video.</p>
<div class="card">
  <div class="row">
    <div><label for="url">Website</label><input id="url" placeholder="https://example.com" autocomplete="off"></div>
    <div><label>Length</label><div class="seg" id="len"></div></div>
    <div><label for="lenc">or exactly</label><input id="lenc" placeholder="e.g. 2:30 or 90s"></div>
  </div>
  <label for="notes">Make sure it... <span style="text-transform:none;letter-spacing:0">(leave empty for auto)</span></label>
  <textarea id="notes" placeholder="e.g. Show the pricing page and end on the sign-up button. Upbeat, for small business owners."></textarea>
  <div class="row2">
    <div><label for="voice">Voice</label><select id="voice"></select></div>
    <div><label for="vname">Voice name or id</label><input id="vname" placeholder="optional"></div>
    <div><label for="editor">Editor</label><select id="editor"><option value="auto">Auto (Resolve if it is open)</option><option value="resolve">DaVinci Resolve</option><option value="ffmpeg">Plain ffmpeg</option></select></div>
  </div>
  <div class="actions"><button class="pri" id="go">Make the video</button><span class="msg" id="msg"></span></div>
</div>
<h2>Queue</h2><div id="jobs"><p class="empty">Nothing yet.</p></div>
</main><script>
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const LENS=[['auto','Auto'],['30s','30s'],['1min','1m'],['2min','2m'],['5min','5m']];let LEN='auto';
const lenSeg=()=>$('#len').innerHTML=LENS.map(([v,l])=>`<button data-v="${v}" class="${v===LEN&&!$('#lenc').value?'on':''}">${l}</button>`).join('');
$('#len').onclick=e=>{const b=e.target.closest('button');if(!b)return;LEN=b.dataset.v;$('#lenc').value='';lenSeg()};$('#lenc').oninput=lenSeg;lenSeg();
let INFO={voices:['none']};
async function api(path,opt){const r=await fetch(path,opt);const t=await r.text();let d;try{d=JSON.parse(t)}catch(e){d={error:t}}if(!r.ok)throw new Error(d.error||r.status);return d}
async function info(){try{INFO=await api('api/info')}catch(e){}
  const names={none:'No voice',openai:'OpenAI-compatible',elevenlabs:'ElevenLabs',odysseus:'Odysseus'};
  $('#voice').innerHTML=INFO.voices.map(v=>`<option value="${v}" ${v===INFO.default_voice?'selected':''}>${names[v]||v}</option>`).join('');
  const sv=localStorage.getItem('svVoice');if(sv&&INFO.voices.includes(sv))$('#voice').value=sv;voiceHint()}
function voiceHint(){const v=$('#voice').value;$('#vname').disabled=(v==='none'||v==='odysseus');
  $('#vname').placeholder=v==='elevenlabs'?(INFO.elevenlabs_voice||'voice id'):v==='openai'?(INFO.openai_voice||'alloy'):'not needed';}
$('#voice').onchange=()=>{localStorage.setItem('svVoice',$('#voice').value);voiceHint()};
$('#go').onclick=async()=>{const v=$('#voice').value,n=$('#vname').value.trim()||(v==='elevenlabs'?INFO.elevenlabs_voice:v==='openai'?INFO.openai_voice:'');
  const body={url:$('#url').value.trim(),length:$('#lenc').value.trim()||LEN,notes:$('#notes').value.trim()||'auto',
    voice:(v==='elevenlabs'||v==='openai')&&n?v+':'+n:v,editor:$('#editor').value};
  $('#go').disabled=true;$('#msg').className='msg';$('#msg').textContent='adding...';
  try{const j=await api('api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    $('#msg').textContent='Queued.';$('#url').value='';$('#notes').value='';load()}
  catch(e){$('#msg').className='msg bad';$('#msg').textContent=e.message}finally{$('#go').disabled=false}};
const OPEN={};
const ago=t=>{if(!t)return'';const s=(Date.now()/1000-t);return s<60?Math.round(s)+'s ago':s<3600?Math.round(s/60)+'m ago':s<86400?Math.round(s/3600)+'h ago':new Date(t*1000).toLocaleDateString()};
const dur=s=>s?Math.floor(s/60)+':'+String(Math.round(s%60)).padStart(2,'0'):'';
async function load(){let js;try{js=await api('api/jobs')}catch(e){return}
  if(!js.length){$('#jobs').innerHTML='<p class="empty">Nothing yet.</p>';return}
  $('#jobs').innerHTML=js.map(j=>{const r=j.request||{},live=['preparing','waiting','editing','queued'].includes(j.status);
    const len=r.length==='auto'?'auto length':dur(r.length);
    return `<div class="job" data-id="${j.id}"><div class="top"><span class="pill ${j.status}">${j.status}</span><span class="u" title="${esc(r.url)}">${esc(r.url)}</span><span class="meta" style="margin:0">${ago(j.created)}</span></div>
      <div class="meta">${esc(len)} &middot; voice ${esc(r.voice)} &middot; ${r.notes&&r.notes!=='auto'?'&ldquo;'+esc(r.notes.slice(0,140))+'&rdquo;':'auto'}${j.status==='done'?' &middot; '+dur(j.seconds)+' made with '+esc(j.editor):''}${live?' &middot; '+esc(j.step||''):''}</div>
      ${live?`<div class="bar"><i style="width:${Math.round((j.progress||0)*100)}%"></i></div>`:''}
      ${j.error?`<div class="err">${esc(j.error)}</div>`:''}
      <div class="btns">${j.status==='done'?`<button data-a="watch">Watch</button><a href="api/jobs/${j.id}/video" download><button>Download</button></a>`:''}
        ${live?'<button data-a="cancel">Cancel</button>':''}${['failed','cancelled'].includes(j.status)?'<button data-a="retry">Try again</button>':''}
        <button data-a="log">Log</button></div>
      ${OPEN[j.id]==='watch'?`<video controls src="api/jobs/${j.id}/video"></video>`:''}${OPEN[j.id]==='log'?`<pre data-log="${j.id}">loading...</pre>`:''}</div>`}).join('');
  document.querySelectorAll('pre[data-log]').forEach(async p=>{try{p.textContent=await (await fetch('api/jobs/'+p.dataset.log+'/log')).text()||'(empty)'}catch(e){}})}
$('#jobs').onclick=async e=>{const b=e.target.closest('button[data-a]');if(!b)return;const id=b.closest('.job').dataset.id,a=b.dataset.a;
  if(a==='watch'||a==='log'){OPEN[id]=OPEN[id]===a?null:a;load();return}
  b.disabled=true;try{await api(`api/jobs/${id}/${a}`,{method:'POST'})}catch(err){alert(err.message)}load()};
info();load();setInterval(()=>{if(!Object.values(OPEN).includes('watch'))load()},4000);   // not while a video plays
</script></body></html>"""
