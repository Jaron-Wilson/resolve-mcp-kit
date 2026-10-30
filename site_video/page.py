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
.row{display:grid;grid-template-columns:2fr 1.6fr .9fr;gap:12px;margin-bottom:12px}.row2{display:grid;grid-template-columns:1fr 1fr 1.3fr 1fr 1fr;gap:12px;margin-top:12px}
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
.chips{display:flex;flex-wrap:wrap;gap:6px}.chips button{border-radius:999px;padding:6px 12px}
.chips button.on{border-color:var(--acc);background:#1c2a3d}.chips button[disabled]{opacity:1;cursor:default}
.chips small{color:var(--dim);margin-left:4px}
.files{margin-top:10px;display:grid;gap:4px}.files .k{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.05em;margin-top:6px}
.files a{font-size:13px;overflow-wrap:anywhere}.files .sz{color:var(--dim);font-size:12px;margin-left:6px}
pre{white-space:pre-wrap;font-size:12px;color:var(--dim);max-height:260px;overflow:auto;background:#111317;border-radius:8px;padding:10px;margin:10px 0 0}
.empty{color:var(--dim)}
.src{display:flex;gap:4px;margin-bottom:14px;max-width:560px}.src button{flex:1;padding:9px 6px}
.vids{border:1px dashed var(--line);border-radius:10px;padding:12px;margin-bottom:12px}.vids.drag{border-color:var(--acc)}
.vid{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,2fr) auto;gap:8px;align-items:center;margin-bottom:8px}
.vid .n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.vid .n small{color:var(--dim);margin-left:6px}
@media(max-width:720px){.vid{grid-template-columns:1fr}}
.chg{border-top:1px solid var(--line);margin-top:12px;padding-top:4px}.chg label{margin-top:12px}.chg textarea{min-height:46px;margin-top:6px}
.chg>input{margin-top:6px}.sc{border:1px solid var(--line);border-radius:10px;padding:10px;margin:8px 0;background:#191c21}
.sh{display:flex;gap:6px;align-items:center}.sh b{white-space:nowrap}.sh input{flex:1;min-width:0}
.sr{display:flex;gap:6px;align-items:center;margin-top:6px;flex-wrap:wrap}.sr input{flex:1;min-width:140px}.sr input[type=number]{flex:0 0 90px;min-width:0}
.sr select{width:auto;max-width:100%}.g3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}@media(max-width:720px){.g3{grid-template-columns:1fr}}
.diff{color:var(--ok);font-size:13px;margin:8px 0;padding-left:18px}.hint{color:var(--dim);font-size:13px;margin:6px 0 0}
</style></head><body><main>
<h1>Site videos</h1><p class="sub">Give it a link, your own videos, or both. It writes a script, records the site in a browser, picks the best moments of your videos, adds a voiceover and edits a promo video.</p>
<div class="card">
  <label>What to use</label>
  <div class="src" id="src"><button data-v="site">A website</button><button data-v="videos">My videos</button><button data-v="both">Website + my videos</button></div>
  <div class="vids" id="vbox" hidden>
    <label>Your videos</label><div id="vlist"></div>
    <input type="file" id="vfile" accept="video/*,.mp4,.mov,.m4v,.mkv,.webm,.avi" multiple hidden>
    <button id="vadd">Add videos</button> <span class="hint">or drop them here. Tell it what each one is and what to use from it.</span>
    <p class="hint" id="vhint"></p>
  </div>
  <div class="row">
    <div id="urlbox"><label for="url">Website</label><input id="url" placeholder="https://example.com" autocomplete="off"></div>
    <div><label>Length</label><div class="seg" id="len"></div></div>
    <div><label for="lenc">or exactly</label><input id="lenc" placeholder="e.g. 2:30 or 90s"></div>
  </div>
  <label for="notes">Make sure it... <span style="text-transform:none;letter-spacing:0">(leave empty for auto)</span></label>
  <textarea id="notes" placeholder="e.g. Show the pricing page and end on the sign-up button. Upbeat, for small business owners."></textarea>
  <div class="row2">
    <div><label for="voice">Voice</label><select id="voice"></select></div>
    <div><label for="vname">Voice name or id</label><input id="vname" placeholder="optional"></div>
    <div><label for="model">Script model</label><input id="model" list="models" placeholder="default" autocomplete="off"><datalist id="models"></datalist></div>
    <div><label for="cursor">Cursor</label><select id="cursor"><option value="arrow">Arrow</option><option value="hand">Pointing hand</option><option value="ring">Arrow with highlight</option><option value="none">No cursor</option></select></div>
    <div><label for="editor">Editor</label><select id="editor"><option value="auto">Auto (Resolve if it is open)</option><option value="resolve">DaVinci Resolve</option><option value="ffmpeg">Plain ffmpeg</option></select></div>
  </div>
  <label style="margin-top:14px">Deliverables</label><div class="chips" id="deliv"></div>
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
let SRC=localStorage.getItem('svSrc')||'site',VIDS=[];
function srcDraw(){document.querySelectorAll('#src button').forEach(b=>b.classList.toggle('on',b.dataset.v===SRC));
  $('#vbox').hidden=SRC==='site';$('#urlbox').style.visibility=SRC==='videos'?'hidden':'';
  $('#vlist').innerHTML=VIDS.map((v,i)=>`<div class="vid"><span class="n" title="${esc(v.f.name)}">${esc(v.f.name)}<small>${SIZE(v.f.size)}${v.pct!=null?' &middot; '+v.pct+'%':''}</small></span>
    <input data-i="${i}" placeholder="What is it? What should it use? e.g. app demo, use the part where I add a card" value="${esc(v.note)}">
    <button data-x="${i}">Remove</button></div>`).join('')}
$('#src').onclick=e=>{const b=e.target.closest('button');if(!b)return;SRC=b.dataset.v;localStorage.setItem('svSrc',SRC);srcDraw()};
$('#vadd').onclick=()=>$('#vfile').click();
const addFiles=fs=>{for(const f of fs)if(/^video\/|\.(mp4|mov|m4v|mkv|webm|avi)$/i.test(f.type+' '+f.name))VIDS.push({f,note:'',pct:null});srcDraw()};
$('#vfile').onchange=()=>{addFiles($('#vfile').files);$('#vfile').value=''};
$('#vlist').oninput=e=>{if(e.target.dataset.i!=null)VIDS[+e.target.dataset.i].note=e.target.value};
$('#vlist').onclick=e=>{const b=e.target.closest('button[data-x]');if(b){VIDS.splice(+b.dataset.x,1);srcDraw()}};
['dragover','dragenter'].forEach(k=>$('#vbox').addEventListener(k,e=>{e.preventDefault();$('#vbox').classList.add('drag')}));
['dragleave','drop'].forEach(k=>$('#vbox').addEventListener(k,e=>{e.preventDefault();$('#vbox').classList.remove('drag')}));
$('#vbox').addEventListener('drop',e=>addFiles(e.dataTransfer.files));
function upload(v){return new Promise((ok,bad)=>{const x=new XMLHttpRequest();x.open('POST','api/uploads?name='+encodeURIComponent(v.f.name));
  x.upload.onprogress=e=>{if(e.lengthComputable){v.pct=Math.round(e.loaded/e.total*100);srcDraw()}};
  x.onload=()=>{let d={};try{d=JSON.parse(x.responseText)}catch(e){}x.status<300?ok(d.file):bad(new Error(d.error||('upload failed: '+x.status)))};
  x.onerror=()=>bad(new Error('upload failed'));x.send(v.f)})}
const DELIV=[['video','Video'],['script','Script'],['voiceover','Voiceover'],['clips','Clips'],['timeline','Timeline','Resolve'],
  ['resolve_project','Resolve project','Resolve'],['package','Full package (zip)']];
let PICK=new Set(JSON.parse(localStorage.getItem('svDeliv')||'["video"]'));PICK.add('video');
const delivDraw=()=>$('#deliv').innerHTML=DELIV.map(([k,l,n])=>`<button data-k="${k}" class="${PICK.has(k)||PICK.has('package')?'on':''}" ${k==='video'?'disabled title="always"':''}>${l}${n?'<small>needs '+n+'</small>':''}</button>`).join('');
$('#deliv').onclick=e=>{const b=e.target.closest('button[data-k]');if(!b||b.dataset.k==='video')return;const k=b.dataset.k;
  if(PICK.has(k))PICK.delete(k);else PICK.add(k);if(k==='package'&&!PICK.has('package'))PICK=new Set(['video',...[...PICK].filter(x=>x!=='package')]);
  localStorage.setItem('svDeliv',JSON.stringify([...PICK]));delivDraw()};delivDraw();
const SIZE=b=>b>1e9?(b/1e9).toFixed(1)+' GB':b>1e6?(b/1e6).toFixed(1)+' MB':Math.max(1,Math.round(b/1e3))+' KB';
const KNAME={video:'Video',script:'Script',voiceover:'Voiceover',clips:'Clips',timeline:'Timeline',resolve_project:'Resolve project',package:'Full package'};
function files(j){const fs=j.files||[];if(!fs.length)return'';const by={};fs.forEach(f=>(by[f.kind]=by[f.kind]||[]).push(f));
  return '<div class="files">'+Object.keys(KNAME).filter(k=>by[k]).map(k=>`<div class="k">${KNAME[k]}</div>`+by[k].map(f=>
    `<div><a href="api/jobs/${j.id}/files/${f.name.split('/').map(encodeURIComponent).join('/')}" download>${esc(f.name)}</a><span class="sz">${SIZE(f.bytes)}</span></div>`).join('')).join('')+'</div>'}
async function api(path,opt){const r=await fetch(path,opt);const t=await r.text();let d;try{d=JSON.parse(t)}catch(e){d={error:t}}if(!r.ok)throw new Error(d.error||r.status);return d}
async function info(){try{INFO=await api('api/info')}catch(e){}
  const names={none:'No voice',openai:'OpenAI-compatible',elevenlabs:'ElevenLabs',odysseus:'Odysseus'};
  $('#voice').innerHTML=INFO.voices.map(v=>`<option value="${v}" ${v===INFO.default_voice?'selected':''}>${names[v]||v}</option>`).join('');
  const sv=localStorage.getItem('svVoice');if(sv&&INFO.voices.includes(sv))$('#voice').value=sv;voiceHint();
  $('#models').innerHTML=(INFO.models||[]).map(m=>`<option value="${esc(m)}">`).join('');
  $('#model').placeholder='default'+(INFO.default_model?' ('+INFO.default_model+')':'');
  $('#model').value=localStorage.getItem('svModel')||'';
  $('#vhint').textContent=(INFO.vision_model?'It watches your videos with '+INFO.vision_model:'No vision model is set up here, so it only knows your notes and each video\'s length: describe them well')
    +(INFO.stt?' and listens to what is said.':'.')+(INFO.max_upload_mb?' Up to '+INFO.max_upload_mb+' MB each.':'')}
$('#model').onchange=()=>localStorage.setItem('svModel',$('#model').value.trim());
function voiceHint(){const v=$('#voice').value;$('#vname').disabled=(v==='none'||v==='odysseus');
  $('#vname').placeholder=v==='elevenlabs'?(INFO.elevenlabs_voice||'voice id'):v==='openai'?(INFO.openai_voice||'alloy'):'not needed';}
$('#voice').onchange=()=>{localStorage.setItem('svVoice',$('#voice').value);voiceHint()};
$('#go').onclick=async()=>{const v=$('#voice').value,n=$('#vname').value.trim()||(v==='elevenlabs'?INFO.elevenlabs_voice:v==='openai'?INFO.openai_voice:'');
  const body={url:SRC==='videos'?'':$('#url').value.trim(),length:$('#lenc').value.trim()||LEN,notes:$('#notes').value.trim()||'auto',
    voice:(v==='elevenlabs'||v==='openai')&&n?v+':'+n:v,editor:$('#editor').value,cursor:$('#cursor').value,model:$('#model').value.trim(),deliverables:[...PICK]};
  if(SRC!=='site'&&!VIDS.length){$('#msg').className='msg bad';$('#msg').textContent='Add your videos first.';return}
  if(SRC!=='videos'&&!body.url){$('#msg').className='msg bad';$('#msg').textContent='Give the website link.';return}
  $('#go').disabled=true;$('#msg').className='msg';$('#msg').textContent='adding...';
  try{if(SRC!=='site'){body.media=[];for(const [i,v] of VIDS.entries()){$('#msg').textContent=`uploading video ${i+1} of ${VIDS.length}...`;
      v.file=v.file||await upload(v);body.media.push({file:v.file,note:v.note.trim()})}}
    const j=await api('api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    $('#msg').textContent='Queued.';$('#url').value='';$('#notes').value='';VIDS=[];srcDraw();load()}
  catch(e){$('#msg').className='msg bad';$('#msg').textContent=e.message}finally{$('#go').disabled=false}};
const OPEN={},EDIT={};
const CUR={arrow:'arrow',hand:'pointing hand',ring:'arrow with highlight',none:'none'};
const pathGet=(o,k)=>k.split('.').reduce((x,p)=>x==null?x:x[/^[0-9]+$/.test(p)?+p:p],o);
function pathSet(o,k,v){const ps=k.split('.');const last=ps.pop();const t=pathGet(o,ps.join('.'))??o;t[/^[0-9]+$/.test(last)?+last:last]=v}
async function openChange(id){if(!EDIT[id]){const d=await api(`api/jobs/${id}/plan`);
    EDIT[id]={plan:d.plan,targets:d.targets,cursor:d.cursor,cursors:d.cursors,changes:null,ask:'',msg:''}}
  OPEN[id]='change';load()}
function chgHtml(id){const E=EDIT[id];if(!E)return '<p class="meta">loading the script...</p>';
  const p=E.plan,pages=E.targets.pages||[],vids=E.targets.videos||[];
  const dls=pages.map((pg,i)=>`<datalist id="dl-${id}-${i}">${[...pg.headings,...pg.buttons].map(t=>`<option value="${esc(t)}">`).join('')}</datalist>`).join('');
  const scenes=p.scenes.map((s,i)=>{const vid='video' in s,last=p.scenes.length-1;
    let body;
    if(vid){body=`<div class="sr"><select data-k="s.${i}.video">${vids.map(v=>`<option ${v.file===s.video?'selected':''}>${esc(v.file)}</option>`).join('')}</select>
      from <input type="number" step="0.1" min="0" data-n="1" data-k="s.${i}.from" value="${s.from}"> to <input type="number" step="0.1" min="0" data-n="1" data-k="s.${i}.to" value="${s.to}"> s
      <select data-k="s.${i}.sound"><option value="voice" ${s.sound!=='keep'?'selected':''}>Narration over it</option><option value="keep" ${s.sound==='keep'?'selected':''}>Its own sound</option></select></div>`}
    else{const pi=Math.max(0,pages.findIndex(pg=>pg.url===s.url));
      body=`<div class="sr"><select data-k="s.${i}.url">${pages.map(pg=>`<option ${pg.url===s.url?'selected':''}>${esc(pg.url)}</option>`).join('')}</select>
        <input type="number" step="0.5" min="4" data-n="1" data-k="s.${i}.seconds" value="${s.seconds}" title="seconds"> s</div>`
        +(s.actions||[]).map((a,k)=>`<div class="sr"><select data-k="s.${i}.actions.${k}.do">${['scroll','hover','click','pause'].map(o=>`<option ${o===a.do?'selected':''}>${o}</option>`).join('')}</select>`
          +(a.do==='pause'?`<input type="number" step="0.5" min="0.5" data-n="1" data-k="s.${i}.actions.${k}.seconds" value="${a.seconds||1}"> s`
            :`<input list="dl-${id}-${pi}" data-k="s.${i}.actions.${k}.${a.do==='scroll'?'to':'text'}" value="${esc(a.do==='scroll'?a.to:a.text)}" placeholder="${a.do==='scroll'?'a heading, top, bottom or 0 to 1':'the text to point at'}">`)
          +`<button data-c="adel" data-i="${i}" data-j="${k}" title="remove this step">&times;</button></div>`).join('')
        +`<div class="sr"><button data-c="aadd" data-i="${i}">+ step</button></div>`}
    const keep=vid&&s.sound==='keep';
    return `<div class="sc"><div class="sh"><b>${i+1}.</b><input data-k="s.${i}.caption" value="${esc(s.caption)}" placeholder="caption">
      <button data-c="up" data-i="${i}" ${i?'':'disabled'} title="move up">&uarr;</button><button data-c="down" data-i="${i}" ${i<last?'':'disabled'} title="move down">&darr;</button><button data-c="del" data-i="${i}">Remove</button></div>
      ${body}<textarea data-k="s.${i}.narration" placeholder="${keep?'its own sound plays here':'narration'}" ${keep?'disabled':''}>${esc(s.narration)}</textarea></div>`}).join('');
  return dls+`<div class="chg"><label>Describe the change</label>
    <textarea class="ask" placeholder="e.g. In scene 3, point at the Pro plan instead of Sign up. Make the intro shorter.">${esc(E.ask)}</textarea>
    <div class="btns"><button data-c="suggest">Apply to the script</button><span class="msg">${esc(E.msg)}</span></div>
    ${E.changes?`<ul class="diff">${E.changes.map(c=>`<li>${esc(c)}</li>`).join('')}</ul>`:''}
    <label>Or edit the script yourself</label>
    <div class="g3"><input data-k="title" value="${esc(p.title)}" placeholder="title"><input data-k="tagline" value="${esc(p.tagline)}" placeholder="tagline">
      <select data-k="__cursor">${E.cursors.map(c=>`<option value="${c}" ${c===E.cursor?'selected':''}>Cursor: ${CUR[c]||c}</option>`).join('')}</select></div>
    <textarea data-k="intro.narration" placeholder="intro narration">${esc(p.intro.narration)}</textarea>${scenes}
    <div class="btns">${pages.length?'<button data-c="addsite">+ website scene</button>':''}${vids.length?'<button data-c="addvid">+ video scene</button>':''}</div>
    <textarea data-k="outro.narration" placeholder="outro narration">${esc(p.outro.narration)}</textarea>
    <input data-k="outro.call_to_action" value="${esc(p.outro.call_to_action)}" placeholder="call to action">
    <div class="actions"><button class="pri" data-c="redo">Redo the video</button><button data-c="close">Close</button>
      <span class="msg">Only the scenes you changed are recorded again.</span></div></div>`}
const drawChange=id=>{const b=document.querySelector(`.chgbox[data-id="${id}"]`);if(b)b.innerHTML=chgHtml(id)};
async function chgClick(b){const id=b.closest('.chgbox').dataset.id,E=EDIT[id],c=b.dataset.c,i=+b.dataset.i,S=E&&E.plan.scenes;
  if(!E)return;const pages=E.targets.pages||[],vids=E.targets.videos||[];
  if(c==='up'&&i>0)S.splice(i-1,0,S.splice(i,1)[0]);
  if(c==='down'&&i<S.length-1)S.splice(i+1,0,S.splice(i,1)[0]);
  if(c==='del')S.splice(i,1);
  if(c==='aadd')(S[i].actions=S[i].actions||[]).push({do:'hover',text:''});
  if(c==='adel')S[i].actions.splice(+b.dataset.j,1);
  if(c==='addsite')S.push({url:pages[0].url,caption:'',narration:'',seconds:8,actions:[{do:'scroll',to:'top'}]});
  if(c==='addvid')S.push({video:vids[0].file,from:0,to:Math.min(10,vids[0].seconds),sound:'voice',caption:'',narration:''});
  if(c==='close'){delete EDIT[id];OPEN[id]=null;load();return}
  if(c==='suggest'){if(!E.ask.trim()){E.msg='Say what to change first.';drawChange(id);return}
    E.msg='Asking the script model (this can take a minute or two)...';drawChange(id);
    try{const d=await api(`api/jobs/${id}/suggest`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({change:E.ask})});
      E.plan=d.plan;E.changes=d.changes;E.msg='Done. Check it below, then press Redo the video.'}
    catch(err){E.msg=err.message}}
  if(c==='redo'){b.disabled=true;try{await api(`api/jobs/${id}/revise`,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({plan:E.plan,cursor:E.cursor})});delete EDIT[id];OPEN[id]=null;load();return}
    catch(err){E.msg=err.message;b.disabled=false}}
  drawChange(id)}
const ago=t=>{if(!t)return'';const s=(Date.now()/1000-t);return s<60?Math.round(s)+'s ago':s<3600?Math.round(s/60)+'m ago':s<86400?Math.round(s/3600)+'h ago':new Date(t*1000).toLocaleDateString()};
const dur=s=>s?Math.floor(s/60)+':'+String(Math.round(s%60)).padStart(2,'0'):'';
async function load(){let js;try{js=await api('api/jobs')}catch(e){return}
  if(!js.length){$('#jobs').innerHTML='<p class="empty">Nothing yet.</p>';return}
  $('#jobs').innerHTML=js.map(j=>{const r=j.request||{},live=['preparing','waiting','editing','queued'].includes(j.status);
    const len=r.length==='auto'?'auto length':dur(r.length);
    const mine=(r.media||[]).map(m=>m.file.split(/[\\/]/).pop()),what=[r.url,mine.length?mine.length+' of your videos ('+mine.join(', ')+')':''].filter(Boolean).join(' + ');
    return `<div class="job" data-id="${j.id}"><div class="top"><span class="pill ${j.status}">${j.status}</span><span class="u" title="${esc(what)}">${esc(what)}</span><span class="meta" style="margin:0">${ago(j.created)}</span></div>
      <div class="meta">${esc(len)} &middot; voice ${esc(r.voice)}${r.model?' &middot; model '+esc(r.model):''} &middot;${r.notes&&r.notes!=='auto'?'&ldquo;'+esc(r.notes.slice(0,140))+'&rdquo;':'auto'}${j.status==='done'?' &middot; '+dur(j.seconds)+' made with '+esc(j.editor):''}${j.revisions?' &middot; changed '+j.revisions+'&times;':''}${live?' &middot; '+esc(j.step||''):''}</div>
      ${live?`<div class="bar"><i style="width:${Math.round((j.progress||0)*100)}%"></i></div>`:''}
      ${j.error?`<div class="err">${esc(j.error)}</div>`:''}
      <div class="btns">${j.status==='done'?`<button data-a="watch">Watch</button><a href="api/jobs/${j.id}/video" download><button>Download video</button></a>`
        +((j.files||[]).some(f=>f.kind==='package')?`<a href="api/jobs/${j.id}/files/${encodeURIComponent((j.files.find(f=>f.kind==='package')||{}).name||'')}" download><button>Download all (zip)</button></a>`:'')
        +((j.files||[]).length>1?'<button data-a="files">Files</button>':''):''}
        ${live?'<button data-a="cancel">Cancel</button>':''}${['failed','cancelled'].includes(j.status)?'<button data-a="retry">Try again</button>':''}${['done','failed'].includes(j.status)?'<button data-a="change">Change</button>':''}${live?'':'<button data-a="remove">Remove</button>'}
        <button data-a="log">Log</button></div>
      ${OPEN[j.id]==='change'?`<div class="chgbox" data-id="${j.id}">${chgHtml(j.id)}</div>`:''}
      ${OPEN[j.id]==='watch'?`<video controls src="api/jobs/${j.id}/video"></video>`:''}${OPEN[j.id]==='files'?files(j):''}${OPEN[j.id]==='log'?`<pre data-log="${j.id}">loading...</pre>`:''}</div>`}).join('');
  document.querySelectorAll('pre[data-log]').forEach(async p=>{try{p.textContent=await (await fetch('api/jobs/'+p.dataset.log+'/log')).text()||'(empty)'}catch(e){}})}
$('#jobs').addEventListener('input',e=>{const el=e.target,box=el.closest('.chgbox');if(!box)return;const E=EDIT[box.dataset.id];if(!E)return;
  if(el.classList.contains('ask')){E.ask=el.value;return}const k=el.dataset.k;if(!k)return;
  if(k==='__cursor'){E.cursor=el.value;return}pathSet(E.plan,k,el.dataset.n?parseFloat(el.value)||0:el.value)});
$('#jobs').addEventListener('change',e=>{const el=e.target,box=el.closest('.chgbox');if(!box||el.tagName!=='SELECT')return;const E=EDIT[box.dataset.id],k=el.dataset.k||'';
  if(k.endsWith('.do')){const a=pathGet(E.plan,k.slice(0,-3));a.to=a.to||a.text||'';a.text=a.text||a.to||''}
  drawChange(box.dataset.id)});
$('#jobs').onclick=async e=>{const cb=e.target.closest('.chgbox button[data-c]');if(cb){chgClick(cb);return}
  const b=e.target.closest('button[data-a]');if(!b)return;const id=b.closest('.job').dataset.id,a=b.dataset.a;
  if(a==='change'){if(OPEN[id]==='change'){delete EDIT[id];OPEN[id]=null;load()}else openChange(id).catch(err=>alert(err.message));return}
  if(a==='watch'||a==='log'||a==='files'){OPEN[id]=OPEN[id]===a?null:a;load();return}
  if(a==='remove'&&!confirm('Remove this video from the queue and delete its files?'))return;
  b.disabled=true;try{await api(`api/jobs/${id}/${a}`,{method:'POST'})}catch(err){alert(err.message)}load()};
srcDraw();info();load();setInterval(()=>{if(!Object.values(OPEN).some(v=>v==='watch'||v==='change'))load()},4000);   // not while a video plays or a script is open
</script></body></html>"""
