// Sends the sign-in this browser has for the site in the current tab (its cookies and page storage) to the
// site-video queue. It runs only when you press the button, and only for that one site.
const $ = id => document.getElementById(id);
// the queue this extension was downloaded from (config.js, written by the queue), else this computer
const DEFAULT = (self.SITE_VIDEO_DEFAULT_SERVER || "http://127.0.0.1:8940").replace(/\/+$/, "");
let tab, site, confirmed = false;

const SAME_SITE = {no_restriction: "None", lax: "Lax", strict: "Strict", unspecified: "Lax"};

// runs inside the page: its local storage, and IndexedDB records that are plain JSON (where Firebase-style
// "Sign in with Google" keeps its login)
async function readPage() {
  const ls = [];
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    ls.push({name: k, value: localStorage.getItem(k)});
  }
  const plain = v => { try { const s = JSON.stringify(v); return s !== undefined && JSON.stringify(JSON.parse(s)) === s; } catch { return false; } };
  const req = r => new Promise((ok, no) => { r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error); });
  const dbs = [];
  try {
    for (const info of (indexedDB.databases ? await indexedDB.databases() : [])) {
      if (!info.name) continue;
      const db = await req(indexedDB.open(info.name));
      try {
        const stores = [];
        for (const name of db.objectStoreNames) {
          const st = db.transaction(name, "readonly").objectStore(name);
          // the indexes are read before anything is awaited, while the transaction is still open
          const indexes = [...st.indexNames].map(n => { const x = st.index(n);
            return {name: x.name, keyPath: typeof x.keyPath === "string" ? x.keyPath : undefined,
                    keyPathArray: Array.isArray(x.keyPath) ? x.keyPath : undefined, multiEntry: x.multiEntry, unique: x.unique}; });
          const [keys, vals] = await Promise.all([req(st.getAllKeys()), req(st.getAll())]);
          const records = [];
          keys.forEach((k, i) => {
            if (!plain(vals[i]) || (st.keyPath === null && !plain(k))) return;
            const r = {value: vals[i]};
            if (st.keyPath === null) r.key = k;
            records.push(r);
          });
          stores.push({name, autoIncrement: st.autoIncrement, records, indexes,
                       keyPath: typeof st.keyPath === "string" ? st.keyPath : undefined,
                       keyPathArray: Array.isArray(st.keyPath) ? st.keyPath : undefined});
        }
        dbs.push({name: db.name, version: db.version, stores});
      } finally { db.close(); }
    }
  } catch (e) { /* storage that cannot be read is left out; cookies and local storage still go */ }
  return {origin: location.origin, localStorage: ls, indexedDB: dbs};
}

const serverValue = () => $("server").value.trim().replace(/\/+$/, "") || DEFAULT;

// plain http to another computer: the cookies (and the token) would cross the network readable by anyone on the path
function showWarning() {
  const server = serverValue(), risky = isInsecureRemote(server);
  $("warn").style.display = risky ? "block" : "none";
  $("warn").textContent = risky ? `${server} is plain http and not this computer. Your sign-in cookies and the queue ` +
    "token would cross the network unencrypted. Use https, a VPN you trust, or a queue on this computer." : "";
  if (!risky) confirmed = false;
  $("go").textContent = "Send my sign-in";
  return risky;
}

function say(text, cls) { $("out").textContent = text; $("out").className = cls || ""; }

async function init() {
  [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  const saved = await chrome.storage.local.get(["server", "token"]);
  $("server").value = saved.server || DEFAULT;
  $("token").value = saved.token || "";
  $("server").oninput = () => { confirmed = false; showWarning(); };
  showWarning();
  try { site = new URL(tab.url); } catch { site = null; }
  if (!site || !/^https?:$/.test(site.protocol)) {
    $("site").textContent = "none";
    $("go").disabled = true;
    return say("Open your site in this tab, signed in, then press this again.");
  }
  $("site").textContent = site.host;
}

$("go").onclick = async () => {
  const server = serverValue(), token = $("token").value.trim();
  if (isInsecureRemote(server) && !confirmed) {          // ask once, then a second press sends
    confirmed = true;
    $("go").textContent = "Send anyway (unencrypted)";
    return say("Check the warning above. Press the button again only if you accept that.", "bad");
  }
  await chrome.storage.local.set({server, token});
  $("go").disabled = true;
  say("Reading the sign-in...");
  try {
    const seen = new Map();
    const host = site.hostname.replace(/^www\./, "");
    for (const c of [...await chrome.cookies.getAll({url: site.origin + "/"}), ...await chrome.cookies.getAll({domain: host})])
      seen.set(c.name + "\n" + c.domain + "\n" + c.path, {
        name: c.name, value: c.value, domain: c.domain, path: c.path, expires: c.session ? -1 : c.expirationDate,
        httpOnly: c.httpOnly, secure: c.secure, sameSite: SAME_SITE[c.sameSite] || "Lax"});
    let origins = [];
    try {
      const [res] = await chrome.scripting.executeScript({target: {tabId: tab.id}, func: readPage});
      if (res && res.result) origins = [res.result];
    } catch (e) { /* a page that blocks scripts: cookies only */ }
    const r = await fetch(server + "/api/signin/import", {method: "POST",
      headers: {"Content-Type": "application/json", ...(token ? {Authorization: "Bearer " + token} : {})},
      body: JSON.stringify({url: site.origin, state: {cookies: [...seen.values()], origins}})});
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || ("the queue answered " + r.status));
    say(`Saved. Videos of ${body.site} will be recorded signed in as you (${body.cookies} cookies, ${body.storage} stored items).`, "ok");
  } catch (e) {
    say("Not saved: " + (e.message || e) + (/fetch/i.test(String(e)) ? `\nIs the queue at ${server} running and reachable from here?` : ""), "bad");
  } finally { $("go").disabled = false; confirmed = false; $("go").textContent = "Send my sign-in"; }
};

init();
