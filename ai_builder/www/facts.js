/* Facts page: library of saved facts, editor, helper and settings.
   Each fact is a Home Assistant script (ask the AI Task for one fact, publish it over MQTT) plus an optional schedule automation. */
let S = {}, F = {}, ENT = [], LIB = [], mem = {};
let cur = {id: null, isNew: true, pushed: false}, E = null, dirty = false, view = "lib", HEL = {entity: "", goal: "", idea: "", back: false};

const aiName = () => S.helper_ai_task_entity || S.ai_task_entity || "";
const fapi = (path, body) => api("facts/" + path, body);
const FASK = "Made with Fact Maker";  // marker the server uses to recognise scripts made here
const RESERVED = /^(current_time|seed|old_fact|fact_.*|src_.*|fc_.*|cal_.*|todo_.*|test_result)$/;
const fslug = s => slug(s, "fact").slice(0, 54).replace(/_$/, "") || "fact";

/* ---------- presets (modeled on the Random Fact, Dark History, Music Fact and City Fact automations) ---------- */
const lines = a => a.join("\n");
const ANGLES = ["a disgusting detail", "an absurd record", "a dark moment", "a myth that is actually false", "a tiny obscure detail", "a dumb mistake", "a wild coincidence"];
const PRE = {
  "Random trivia": {name: "Random Fact", file: "random_fact.txt", swear: "rated",
    task: "Share one real trivia fact about the topic.",
    skip: "honey never spoils, octopus hearts, Cleopatra and the pyramids, bananas being berries",
    picks: [{name: "topic", items: lines(["space and astronomy", "animals and insects", "the human body", "food and drink", "geography", "inventions and technology", "language and words", "sports history", "architecture and engineering", "weather and nature", "money and economics", "transportation"])}, {name: "angle", items: lines(ANGLES)}]},
  "Dark history": {name: "Dark History", file: "random_fact.txt", swear: "rated",
    task: "Share one real dark history fact about the topic.",
    skip: "Vlad the Impaler, iron maidens, Jack the Ripper, plague doctors, Salem witch trials",
    extra: "Only use events that are well documented and verifiable. If you are not sure a detail is real, pick a different fact. No urban legends presented as truth, and no made up dates or numbers. Skip anything involving sexual violence.",
    picks: [{name: "topic", items: lines(["a brutal historical execution or punishment method", "a horrifying medical practice from the past", "a government or corporate cover-up", "a bizarre or ironic historical death", "a disaster caused by pure incompetence", "a forgotten massacre or atrocity", "a creepy unsolved mystery or disappearance", "a messed up old law or tradition", "a notorious prison, asylum, or torture device", "a deadly industrial or workplace horror", "a plague, famine, or mass hysteria event", "a wartime horror most people never heard of"])},
      {name: "angle", items: lines(["a disgusting detail", "a dark moment", "a myth that is actually false", "a tiny obscure detail", "a dumb mistake that got people killed", "a wild coincidence", "a detail that sounds fake but is documented"])}]},
  "Music fact": {name: "Music Fact", file: "music_fact.txt", swear: "rated", style: "titled", obscure: false,
    titleHint: "the artist or band name", heading: "## 🎶MUSIC🎻 Fact About - {{ fact_title }}",
    task: "Pick a real artist or band from the genre given who was active in the decade given. If that genre did not exist in that decade, use the closest real match. Choose one with a well-documented public history, and do NOT pick the most famous name in that genre. Then share one cool, unique music trivia fact about that artist. Skip the famous stuff everyone already knows.",
    extra: "The fact must be real public music history.",
    picks: [{name: "genre", items: lines(["heavy metal", "hip hop", "trap", "punk", "hardcore", "metalcore", "grunge", "southern rap", "industrial", "classic rock", "death metal", "nu metal", "emo", "blues", "outlaw country", "reggae", "funk", "gangsta rap", "post-hardcore", "alternative rock", "jazz", "soul", "electronic", "Latin"])},
      {name: "decade", items: lines(["1980s", "1990s", "2000s", "2010s", "2020s"])},
      {name: "angle", items: lines(["a studio disaster", "a lyric origin story", "a wild feud", "a record or chart oddity", "a tiny obscure detail", "a dumb mistake", "a banned or censored moment", "a weird instrument or gear detail", "a wild coincidence", "a myth that is actually false"])}]},
  "City fact": {name: "City Cool Fact", file: "location_fact.txt", types: ["locations"], obscure: false,
    task: "Pick one city or town from the places listed above at random and share one fascinating, obscure historical or cultural fact about it. Open with the place name, then give the fact. Talk ONLY about the place. Warm and a little playful in tone.",
    picks: []},
  "Blank": {name: "My fact", picks: [], task: ""}
};

/* ---------- state ---------- */
const defAuto = () => ({on: false, every: 10, unit: "minutes", watch: "", watchAttr: "", watchFor: 10, home: []});
const blankState = () => ({name: "My fact", src: [], task: "", picks: [], seed: true, len: F.default_length || 180, style: "plain", titleHint: "", heading: "", count: 5,
  file: "", swear: "none", real: true, obscure: true, skip: "", noPeople: true, avoidLast: true, lastEntity: "", lastAttr: "", extra: "", ai: "", auto: defAuto()});
const clone = o => JSON.parse(JSON.stringify(o));
const full = s => Object.assign(blankState(), clone(s || {}), {auto: Object.assign(defAuto(), (s && s.auto) || {})});

const cleanName = n => { n = String(n || "").toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "").replace(/^[0-9]+/, ""); n = n.slice(0, 24); if (!n) return ""; return RESERVED.test(n) ? "pick_" + n : n; };
const itemsOf = p => String(p.items || "").split("\n").map(x => x.trim()).filter(Boolean);
const pickList = s => { const seen = new Set(); return (s.picks || []).map(p => ({name: cleanName(p.name), items: itemsOf(p)})).filter(p => p.name && p.items.length && !seen.has(p.name) && seen.add(p.name)); };
const fileOf = s => (s.file || "").trim() || fslug(s.name) + ".txt";
function topicOf(s) {
  const f = fileOf(s); if (f.includes("/")) return f;
  let pre = F.mqtt_prefix || ""; if (pre && !pre.endsWith("/")) pre += "/";
  return pre + f;
}
const lastRef = s => ({entity: s.lastEntity || F.last_entity || "", attr: s.lastEntity ? s.lastAttr : (s.lastAttr || F.last_attribute || "")});
const q1 = t => "'" + String(t).replace(/'/g, "''") + "'";  // single-quoted YAML string

/* ---------- the script ---------- */
function buildPrompt(s, chosen) {
  const P = [], picks = pickList(s), lr = lastRef(s);
  if (chosen.length) P.push("Current time: {{ current_time }}.");
  chosen.forEach(c => P.push(c.label.toUpperCase() + ":\n{{ src_" + c.id + " }}"));
  const L = picks.map(p => p.name.replace(/_/g, " ").toUpperCase() + " FOR THIS RUN: {{ " + p.name + " }}");
  if (s.seed) L.push("Random seed for variety: {{ seed }}.");
  if (L.length) P.push(L.join("\n"));
  P.push("YOUR TASK: " + ((s.task || "").trim() || "Share one surprising, true fact."));
  if (s.real) P.push("The fact must be real public knowledge that can be verified. If you are not sure a detail is true, pick a different fact. Never invent anything: no made up names, dates or numbers.");
  if (s.obscure) P.push("Go obscure. Deep cuts only. Do NOT use famous, overused facts" + ((s.skip || "").trim() ? " (for example: " + s.skip.trim() + ")" : "") + ".");
  if (s.noPeople) P.push("The fact must NOT reference or be about any person in our household or friend group, or their pets, jobs or relationships. Do not say things like \"someone is in\" or \"our\".");
  const rules = [s.extra, F.extra_rules].map(x => (x || "").trim()).filter(Boolean); rules.forEach(r => P.push(r));
  if (s.avoidLast && lr.entity) P.push("{% if old_fact %}Do not repeat or rephrase this previous fact" + (s.style === "titled" ? ", and do not reuse its subject (named in its heading)" : "") + ": {{ old_fact }}{% endif %}");
  P.push({none: "Keep the language clean, no profanity.", mild: "Light language is fine, keep it PG-13.", rated: "Use profanity as needed."}[s.swear] || "");
  const n = +s.len || 180;
  if (s.style === "list") P.push("Each line must be " + n + " characters or less.");
  else P.push("The fact part must be " + n + " characters or less.");
  if (s.style === "titled") P.push("Return exactly ONE line in this format, with three pipe characters between the two parts:\nTitle ||| The fact text\nThe title part is: " + ((s.titleHint || "").trim() || "a short name for what the fact is about") + ".\nNo markdown, no quotes, no preamble, no explanation.");
  else if (s.style === "list") P.push("Return exactly " + (+s.count || 5) + " lines, one item per line, with no numbering, bullets, markdown, quotes, preamble or explanation.");
  else P.push("Return ONLY the fact as plain text. No JSON, no markdown, no quotes, no preamble, no explanation.");
  return P.filter(x => x !== "").join("\n\n");
}

function makeYaml(s0, o) {
  if (s0.raw != null) return s0.raw;  /* a pasted script is pushed exactly as written */
  const s = full(s0), name = JSON.stringify(s.name || "Fact"), picks = pickList(s), lr = lastRef(s);
  const chosen = (s.src || []).map(id => usable().find(x => x.id === id)).filter(Boolean);
  let y = "alias: " + name + "\ndescription: " + FASK + "\nmode: restart\nsequence:\n";
  if (chosen.length) y += "  - variables:\n      current_time: '{{ now().strftime(''%A, %B %-d %Y %-I:%M %p %Z'') }}'\n";
  chosen.forEach(c => { y += genPre(c) });
  if (chosen.length) y += "  - alias: Load data sources\n    variables:\n" + chosen.map(c => { const b = body(c).trim(); return b ? `      src_${c.id}: |-\n` + ind(b, 8) : `      src_${c.id}: ""` }).join("\n") + "\n";
  const useLast = s.avoidLast && !!lr.entity, V = [];
  if (useLast) V.push("      old_fact: |-\n" + ind(lr.attr
    ? `{{ state_attr('${lr.entity}', '${lr.attr}') | default('', true) }}`
    : `{% set v = states('${lr.entity}') %}{{ '' if v in ['unknown', 'unavailable'] else v }}`, 8));
  picks.forEach(p => V.push(`      ${p.name}: |-\n` + ind("{{ [" + p.items.map(i => JSON.stringify(i)).join(", ") + "] | random }}", 8)));
  if (s.seed) V.push("      seed: '{{ range(1, 100000) | random }}'");
  if (V.length) y += "  - alias: Pick random details\n    variables:\n" + V.join("\n") + "\n";
  const ai = s.ai || S.ai_task_entity || "ai_task.SET_ME";
  y += "  - alias: Ask the AI\n    action: ai_task.generate_data\n    data:\n      task_name: " + name + "\n      entity_id: " + ai + "\n      instructions: |-\n" + ind(buildPrompt(s, chosen), 8) + "\n    response_variable: fact_raw\n";
  const P = [];
  if (s.style === "titled") {
    P.push("      fact_parts: |-\n        {{ (fact_raw.data | string).split('|||') }}");
    P.push("      fact_title: |-\n        {{ (fact_parts[0] | trim | replace('*', '') | replace('\"', '')) if fact_parts | length > 1 else '' }}");
    P.push("      fact_text: |-\n        {{ (fact_parts[1:] | join(' ') | trim | replace('\"', '')) if fact_parts | length > 1 else '' }}");
  } else if (s.style === "list") {
    P.push("      fact_text: |-\n        {% set ns = namespace(items=[]) %}{% for line in (fact_raw.data | string).split('\\n') %}{% set t = line | trim | replace('\"', '') %}{% if t %}{% set ns.items = ns.items + [t] %}{% endif %}{% endfor %}{{ ns.items[:" + (+s.count || 5) + "] | join('\\n') }}");
  } else P.push("      fact_text: |-\n        {{ fact_raw.data | string | trim | replace('\"', '') }}");
  const head = (s.heading || "").trim();
  P.push("      fact_out: |-\n" + ind((head ? head + "\n\n" : "") + "{{ fact_text }}", 8));
  y += "  - alias: Clean up the answer\n    variables:\n" + P.join("\n") + "\n";
  if (!(o && o.test)) y += `  - alias: Publish\n    if:\n      - condition: template\n        value_template: "{{ fact_text | length > 0 }}"\n    then:\n      - action: mqtt.publish\n        data:\n          topic: ${JSON.stringify(topicOf(s))}\n          payload: "{{ fact_out }}"\n`;
  return y;
}

const autoSummary = a => {
  const p = [];
  if (+a.every > 0) p.push("every " + Math.round(+a.every) + (a.unit === "hours" ? " h" : " min"));
  if (a.watch) p.push("when " + a.watch + " changes");
  return p.join(" and ") || "no trigger set";
};
function makeAuto(s0, sid) {
  if (s0.raw != null) return "";
  const s = full(s0), a = s.auto;
  if (!a.on) return "";
  const T = [];
  if (+a.every > 0) {
    if (a.unit === "hours") T.push(`  - trigger: time_pattern\n    hours: "/${Math.min(23, Math.max(1, Math.round(+a.every)))}"\n    minutes: 0\n`);
    else T.push(`  - trigger: time_pattern\n    minutes: "/${Math.min(59, Math.max(1, Math.round(+a.every)))}"\n`);
  }
  if (a.watch) T.push(`  - trigger: state\n    entity_id: ${a.watch}\n` + (a.watchAttr ? `    attribute: ${a.watchAttr}\n` : "") + (+a.watchFor > 0 ? `    for:\n      seconds: ${Math.round(+a.watchFor)}\n` : ""));
  if (!T.length) return "";
  let y = "alias: " + JSON.stringify((s.name || "Fact") + " (auto)") + "\ndescription: " + FASK + "\nmode: restart\ntriggers:\n" + T.join("");
  const C = (a.home || []).map(e => {
    const d = e.split(".")[0];
    if (d === "zone") return `numeric_state\n        entity_id: ${e}\n        above: 0`;
    if (d === "person" || d === "device_tracker") return `state\n        entity_id: ${e}\n        state: home`;
    return `state\n        entity_id: ${e}\n        state: "on"`;
  });
  if (C.length === 1) y += "conditions:\n  - condition: " + C[0].replace(/\n        /g, "\n    ") + "\n";
  else if (C.length) y += "conditions:\n  - condition: or\n    conditions:\n" + C.map(c => "      - condition: " + c + "\n").join("");
  y += "actions:\n  - action: script." + sid + "\n";
  return y;
}
const hasTrigger = s => !!(s.auto && ((+s.auto.every > 0) || s.auto.watch));

/* ---------- DOM ---------- */
/* ---------- views ---------- */
function showView(v) {
  view = v;
  $("#chrome").hidden = v === "edit";
  ["lib", "help", "set", "edit"].forEach(k => $("#v-" + k).hidden = k !== v);
  $$("#tabs .tab").forEach(b => b.classList.toggle("on", b.dataset.v === v));
  $("#dock").hidden = v !== "set";
  try { window.scrollTo(0, 0) } catch (e) {}
}
$$("#tabs .tab").forEach(b => b.onclick = () => { showView(b.dataset.v); if (b.dataset.v === "lib") loadLib(); });

function setupNote() {
  const miss = [];
  if (!S.ai_task_entity) miss.push("an AI Task (set it in Announcements > Settings or the add-on options)");
  const box = $("#setupnote"); box.replaceChildren();
  if (!miss.length) return;
  box.append(el("div", {class: "note warn"}, el("div", {}, el("b", {}, "Finish setup to make facts. "), "Still needed: " + miss.join(", ") + "."),
    el("button", {class: "btn sm", onclick: () => showView("set")}, "Open Settings")));
}

/* ---------- library ---------- */
function flash(text, cls) { const m = $("#libmsg"); m.className = "msg " + (cls || ""); m.textContent = text || ""; }
async function loadLib() {
  const d = await fapi("library");
  if (d.error) { flash(d.error, "bad"); return; }
  LIB = d.items || [];
  $("#libcount").textContent = LIB.length;
  renderLib();
}
function renderLib() {
  const live = LIB.filter(x => x.pushed_at || x.in_ha).length;
  $("#libsub").textContent = LIB.length ? LIB.length + " fact" + (LIB.length === 1 ? "" : "s") + ", " + live + " in Home Assistant" : "";
  $("#updall").hidden = !LIB.some(x => x.pushed_at);
  const box = $("#cards"); box.replaceChildren();
  if (!LIB.length) {
    box.style.display = "block";
    box.append(el("div", {class: "card empty"}, el("h3", {}, "No facts yet"),
      el("p", {}, "Say what the fact should be about, add some random topics to keep it fresh, and choose where it is saved."),
      el("div", {class: "row"}, el("button", {class: "btn primary", onclick: () => openNew()}, "Make your first fact"))));
  } else box.style.display = "";
  LIB.forEach(it => box.append(libCard(it)));
}
function libCard(it) {
  const st = it.state || {}, raw = st.raw != null;
  const status = !it.pushed_at && !it.in_ha ? ["warn", "Draft, not in Home Assistant"] : it.in_ha ? ["ok", "In Home Assistant"] : ["bad", "Missing in Home Assistant"];
  const msg = el("div", {class: "msg", style: "margin:0"});
  const del = el("button", {class: "btn danger sm"}, "Delete");
  confirmTap(del, it.in_ha ? "Tap again: removes the script too" : "Tap again to delete", () => removeFact(it.id, !!it.in_ha));
  const run = el("button", {class: "btn sm", disabled: !it.in_ha, title: it.in_ha ? "Run it now" : "Push it to Home Assistant first", onclick: async () => {
    run.disabled = true; msg.className = "msg"; msg.textContent = "Starting...";
    const r = await fapi("run", {id: it.id}); msg.className = "msg " + (r.ok ? "ok" : "bad"); msg.textContent = r.ok ? "Started." : (r.detail || r.error); run.disabled = false;
  }}, "Run now");
  const dup = el("button", {class: "btn sm", onclick: async () => {
    const nm = (it.name || it.id) + " copy", id = uniqueId(fslug(nm));
    const r = await fapi("library/save", {id, name: nm, state: Object.assign({}, st, {name: nm}, raw ? {raw: setAlias(st.raw, nm)} : {})});
    if (r.ok) { flash("Copied as a draft: " + id, "ok"); loadLib(); } else flash(r.error, "bad");
  }}, "Duplicate");
  const a = st.auto || {}, pills = [];
  if (raw) pills.push(el("span", {class: "pill plain"}, "Own script"));
  else {
    pills.push(el("span", {class: "pill plain"}, fileOf(Object.assign({}, st, {name: st.name || it.name}))));
    if (a.on) pills.push(!it.auto_in_ha ? el("span", {class: "pill warn"}, "Schedule not pushed") : it.auto_on ? el("span", {class: "pill ok"}, "Runs " + autoSummary(a)) : el("span", {class: "pill warn"}, "Schedule is off in HA"));
    else pills.push(el("span", {class: "pill plain"}, "Manual only"));
  }
  pills.push(el("span", {class: "pill plain"}, "Edited " + ago(it.updated)));
  return el("div", {class: "card ann"},
    el("div", {class: "top"}, el("div", {style: "min-width:0"}, el("h3", {}, it.name || it.id), el("div", {class: "dim small mono"}, "script." + it.id)), el("span", {class: "pill " + status[0]}, status[1])),
    el("div", {class: "clamp"}, raw ? "Your own script, kept exactly as you wrote it." : (st.task || "No instructions yet.")),
    el("div", {class: "meta"}, pills),
    el("div", {class: "acts"}, el("button", {class: "btn primary sm", onclick: () => openItem(it)}, "Edit"), run, dup, del), msg);
}
async function removeFact(id, alsoScript) {
  const r = await fapi("library/delete", {id, delete_script: !!alsoScript});
  if (r.ok) { flash(r.script_deleted ? "Deleted " + id + " and its script in Home Assistant." : "Deleted " + id + ".", "ok"); loadLib(); } else flash(r.error, "bad");
}
$("#updall").onclick = () => {
  const b = $("#updall");
  if (!b.dataset.armed) {
    b.dataset.armed = 1; b.textContent = "Tap again to push all"; b.classList.add("primary");
    setTimeout(() => { delete b.dataset.armed; b.textContent = "Update all in Home Assistant"; b.classList.remove("primary") }, 4000); return;
  }
  delete b.dataset.armed; b.classList.remove("primary"); b.textContent = "Update all in Home Assistant"; updateAll();
};
async function updateAll() {
  const todo = LIB.filter(x => x.pushed_at); let ok = 0; const bad = [];
  flash("Updating " + todo.length + "...", "");
  for (const it of todo) {
    const s = it.state || {}, r = await fapi("push", {id: it.id, yaml: makeYaml(s), auto_yaml: makeAuto(s, it.id), state: s});
    if (r.ok) ok++; else bad.push(it.name + ": " + (r.detail || r.error));
  }
  flash("Updated " + ok + " of " + todo.length + " with your current settings." + (bad.length ? " Failed: " + bad.join("; ") : ""), bad.length ? "bad" : "ok");
  loadLib();
}

/* ---------- ids ---------- */
function takenIds() {
  const s = new Set(LIB.map(x => x.id));
  ENT.forEach(e => { if (e.id.startsWith("script.")) s.add(e.id.slice(7)); });
  return s;
}
function uniqueId(base) {
  const t = takenIds(); let id = base, n = 2;
  while (t.has(id)) id = base.slice(0, 50) + "_" + (n++);
  return id;
}

/* ---------- your own pasted script ---------- */
const cleanId = x => { x = String(x || "").trim().toLowerCase().replace(/^script\./, ""); return /^[a-z0-9_]{1,54}$/.test(x) ? x : "" };
function getAlias(y) {
  const m = String(y).match(/^alias:[ \t]*(.+?)[ \t]*$/m); if (!m) return "";
  let v = m[1]; if (/^[>|]/.test(v)) return "";
  if (v[0] === '"' && v.endsWith('"')) { try { return JSON.parse(v) } catch (e) { return v.slice(1, -1) } }
  if (v[0] === "'" && v.endsWith("'")) return v.slice(1, -1).replace(/''/g, "'");
  return v;
}
function setAlias(y, name) {
  const line = "alias: " + JSON.stringify(name || "Fact");
  return /^alias:.*$/m.test(y) ? y.replace(/^alias:.*$/m, () => line) : line + "\n" + y;
}
const imsg = (t, c) => { const m = $("#impmsg"); m.className = "msg " + (c || ""); m.textContent = t || ""; };
function fillPick() {
  const sel = $("#imppick"); sel.replaceChildren(el("option", {value: ""}, "Choose a script..."));
  ENT.filter(e => e.id.startsWith("script.")).forEach(e => sel.append(el("option", {value: e.id.slice(7)}, e.name + " (" + e.id + ")")));
}
$("#importbtn").onclick = () => { $("#importbox").hidden = false; imsg(""); fillPick(); $("#impyaml").focus(); };
$("#impcancel").onclick = () => { $("#importbox").hidden = true; imsg(""); };
$("#imppickgo").onclick = async () => {
  const id = $("#imppick").value; if (!id) { imsg("Choose a script first.", "warn"); return; }
  imsg("Loading...");
  const r = await api("ann/script?id=" + encodeURIComponent(id));
  if (!r.ok) { imsg(r.error, "bad"); return; }
  $("#impyaml").value = r.yaml; $("#impid").value = id; imsg("Loaded. Press Import to take it over.", "ok");
};
$("#impgo").onclick = async () => {
  const b = $("#impgo"), typed = $("#impid").value.trim();
  if (typed && !cleanId(typed)) { imsg("The script id can only use lowercase letters, numbers and underscores (54 at most).", "bad"); return; }
  b.disabled = true; imsg("Checking your script...");
  const r = await api("ann/import", {yaml: $("#impyaml").value});
  b.disabled = false;
  if (!r.ok) { imsg(r.error || "That failed.", "bad"); return; }
  const id = cleanId(typed) || cleanId(r.id) || uniqueId(fslug(r.alias)), takeover = !!(cleanId(typed) || cleanId(r.id));
  if (LIB.some(x => x.id === id)) { imsg("script." + id + " is already in My facts. Open it from the list below.", "bad"); return; }
  const inHA = ENT.some(e => e.id === "script." + id);
  $("#importbox").hidden = true; $("#impyaml").value = ""; $("#impid").value = ""; imsg("");
  openEditor(Object.assign(blankState(), {name: r.alias, raw: r.yaml}), {id, isNew: true, pushed: false, saved: false, fixedId: true},
    "Imported. Your script is kept exactly as written. " + (inHA ? "script." + id + " already exists in Home Assistant, so pushing replaces it." : "Pushing creates script." + id + " in Home Assistant.") + (takeover ? "" : " Nothing is in Home Assistant yet."));
  markDirty();
};

/* ---------- editor ---------- */
const changed = () => { gen(); markDirty(); };
const add = (parent, ...kids) => { kids.flat(Infinity).forEach(x => { if (x != null && x !== false) parent.append(x); }); return parent; };
const rawMode = () => E && E.raw != null;

function tf(label, key, o) {
  o = o || {};
  const i = el(o.area ? "textarea" : "input", {value: E[key] ?? "", placeholder: o.ph || "", type: o.num ? "number" : null, class: o.cls || null, style: o.style || null, min: o.min != null ? o.min : null, step: o.step || null});
  i.oninput = () => { E[key] = o.num ? (i.value === "" ? "" : +i.value) : i.value; if (o.after) o.after(); changed(); };
  return [el("label", {class: "l"}, label), i, o.help ? el("p", {class: "help"}, o.help) : null];
}
function cb(label, key, o) {
  o = o || {};
  const i = el("input", {type: "checkbox", checked: !!E[key]});
  i.onchange = () => { E[key] = i.checked; changed(); if (o.redraw) drawForm(); };
  return [el("label", {class: "check"}, i, el("span", {}, label, o.sub ? el("small", {}, " " + o.sub) : null)), o.help ? el("p", {class: "help"}, o.help) : null];
}
function sel(label, key, opts, o) {
  o = o || {};
  const s = el("select", {style: o.style || null}, opts.map(([v, t]) => el("option", {value: v}, t)));
  s.value = E[key]; s.onchange = () => { E[key] = s.value; changed(); if (o.redraw) drawForm(); };
  return [el("label", {class: "l"}, label), s, o.help ? el("p", {class: "help"}, o.help) : null];
}
const card = (n, title, sub, ...kids) => el("section", {class: "card"}, el("div", {class: "ch"}, el("h2", {}, n ? el("span", {class: "n"}, n) : null, title), sub ? el("p", {}, sub) : null), kids);

function drawForm() {
  const f = $("#form"); f.replaceChildren();
  const raw = rawMode();
  /* 1. name */
  const c1 = card(1, "Name");
  const nm = tf("Script name", "name", {after: () => { if (raw) E.raw = setAlias(E.raw, E.name); }});
  add(c1, nm, el("p", {class: "help", id: "idhelp"}));
  if (cur.isNew && !raw) {
    const chips = el("div", {class: "chips"});
    Object.entries(PRE).forEach(([k, p]) => chips.append(el("button", {class: "chip", onclick: () => applyPreset(p)}, k)));
    add(c1, el("label", {class: "l"}, "Start from"), chips, el("p", {class: "msg warn", id: "pnote"}));
  }
  f.append(c1);
  if (raw) {
    const t = el("textarea", {class: "code", spellcheck: "false", style: "min-height:440px", value: E.raw});
    t.oninput = () => { E.raw = t.value; const a = getAlias(t.value); if (a) { E.name = a; $("#form input").value = a; } changed(); };
    const chk = el("button", {class: "btn sm", onclick: async () => {
      say("Checking..."); const r = await api("ann/import", {yaml: E.raw});
      say(r.ok ? "That is a valid script with " + (r.config.sequence || []).length + " top-level steps." : r.error, r.ok ? "ok" : "bad");
    }}, "Check YAML");
    f.append(card(2, "Your script", "Kept exactly as you wrote it. Edit the YAML here, then Save or Save and push.", t, el("div", {class: "row", style: "margin-top:10px"}, chk)));
    return;
  }

  /* 2. what it is about */
  const c2 = card(2, "What it's about", "Everything here is optional except the instructions.");
  const U = usable();
  add(c2, el("label", {class: "l"}, "Data to include (optional)"));
  const g = el("div", {class: "pickgrid"});
  U.forEach(s => { const i = el("input", {type: "checkbox", checked: (E.src || []).includes(s.id)}); i.onchange = () => { E.src = i.checked ? [...E.src, s.id] : E.src.filter(x => x !== s.id); changed(); }; g.append(el("label", {class: "pick", title: s.label}, i, el("span", {}, s.label))); });
  if (!U.length) g.append(el("p", {class: "dim small"}, "No data sources yet. Add some in Announcements > Settings, or use Helper > Add something to talk about."));
  add(c2, g, el("p", {class: "help"}, "Shared with Announcements. Ticked ones are given to the AI as extra context."));
  add(c2, tf("What should it say?", "task", {area: 1, cls: "tall", ph: "e.g. Share one real trivia fact about the topic. Keep it weird and specific."}));
  add(c2, el("div", {class: "row", style: "margin-top:8px"}, el("button", {class: "btn sm", onclick: () => { showView("help"); $("#chrome").hidden = true; $("#tabs").hidden = true; HEL.back = true; drawHelper(); }}, "Help me write this")));
  add(c2, el("label", {class: "l"}, "Random lists, so every run is different"));
  const pk = el("div", {});
  (E.picks || []).forEach((p, i) => {
    const n = el("input", {value: p.name, placeholder: "name, e.g. topic"}), it = el("textarea", {value: p.items, placeholder: "One option per line", style: "min-height:92px"});
    n.oninput = () => { p.name = n.value; changed(); }; n.onblur = () => { const c = cleanName(n.value); if (c !== n.value) { n.value = c; p.name = c; changed(); } };
    it.oninput = () => { p.items = it.value; changed(); };
    const rm = el("button", {class: "btn danger sm"}, "Remove"); confirmTap(rm, "Tap again", () => { E.picks.splice(i, 1); changed(); drawForm(); });
    pk.append(el("div", {class: "pickrow"}, n, it, rm));
  });
  add(c2, pk, el("div", {class: "row", style: "margin-top:10px"}, el("button", {class: "btn sm", onclick: () => { E.picks.push({name: ["topic", "angle", "genre", "decade", "style", "era"].find(x => !E.picks.some(p => p.name === x)) || "pick" + (E.picks.length + 1), items: ""}); changed(); drawForm(); }}, "Add a random list")),
    el("p", {class: "help"}, "Each run picks one option from every list, and the AI is told what was picked (for example \"TOPIC FOR THIS RUN: ...\"). Mention a list by name in your instructions if you like. Names use lowercase letters and underscores."));
  add(c2, cb("Add a random number so repeats are less likely", "seed"));
  f.append(c2);

  /* 3. how it reads */
  const c3 = card(3, "How it reads");
  add(c3, sel("Format", "style", [["plain", "Just the fact"], ["titled", "A title and the fact"], ["list", "A short list"]], {redraw: 1, style: "max-width:260px"}));
  if (E.style === "titled") add(c3, tf("What is the title?", "titleHint", {ph: "e.g. the artist or band name", help: "The AI answers as \"Title ||| fact\" and the script splits it. Use it in the heading as {{ fact_title }}."}));
  if (E.style === "list") add(c3, tf("How many lines", "count", {num: 1, min: 1, step: 1, style: "max-width:120px"}));
  add(c3, tf(E.style === "list" ? "Max length of each line (characters)" : "Max length (characters)", "len", {num: 1, min: 40, step: 20, style: "max-width:160px"}));
  add(c3, tf("Heading above it (optional)", "heading", {area: 1, ph: "e.g. ## 🎶 MUSIC Fact About - {{ fact_title }}", style: "min-height:60px", help: "Saved in the file above the fact. You can use {{ fact_title }}" + (pickList(E).length ? ", " + pickList(E).map(p => "{{ " + p.name + " }}").join(", ") : "") + " and any Home Assistant template."}));
  add(c3, sel("Language", "swear", [["none", "Clean"], ["mild", "Light (PG-13)"], ["rated", "Profanity as needed"]], {style: "max-width:260px"}));
  add(c3, el("label", {class: "l"}, "Rules"));
  add(c3, cb("Only real, verifiable facts", "real", {sub: "if unsure it picks a different one"}));
  add(c3, cb("Go obscure, skip the famous ones", "obscure", {redraw: 1}));
  if (E.obscure) add(c3, tf("Famous ones to skip (optional)", "skip", {ph: "e.g. honey never spoils, octopus hearts", style: "margin-bottom:4px"}));
  add(c3, cb("Keep our household, pets and jobs out of it", "noPeople"));
  add(c3, cb("Don't repeat the last fact", "avoidLast", {redraw: 1, sub: "the AI is shown the previous one"}));
  if (E.avoidLast) {
    const lr = lastRef(E);
    add(c3, el("label", {class: "l"}, "Where the last fact is read from"), picker(null, false, () => E.lastEntity ? [E.lastEntity] : [], a => { E.lastEntity = a[0] || ""; changed(); }),
      el("p", {class: "help"}, lr.entity ? "Reading " + lr.entity + (lr.attr ? " attribute " + lr.attr : " state") + (E.lastEntity ? "." : " (the default from Settings).") : "Nothing set. Pick the sensor that reads your fact file, or set a default in Settings."));
    if (E.lastEntity) add(c3, tf("Attribute (blank = state)", "lastAttr", {style: "max-width:260px"}));
  }
  add(c3, tf("Extra rules (optional)", "extra", {area: 1, ph: "Anything else the AI must follow.", style: "min-height:70px"}));
  f.append(c3);

  /* 4. where it goes */
  const c4 = card(4, "Where it goes", "Saved over MQTT. A dashboard card (for example file_reader) shows the file.");
  add(c4, tf("File name", "file", {ph: fslug(E.name) + ".txt", help: "Added to the topic prefix from Settings. Type a full topic (with a slash) to override."}));
  add(c4, el("p", {class: "help"}, el("span", {}, "Publishes to "), el("code", {id: "topicshow"}, topicOf(E))));
  const adv = el("details", {style: "margin-top:12px"}, el("summary", {}, "Use a different AI Task for this one"));
  adv.append(picker(["ai_task"], false, () => E.ai ? [E.ai] : [], a => { E.ai = a[0] || ""; changed(); }), el("p", {class: "help"}, "Blank uses " + (S.ai_task_entity || "the AI Task from Announcements") + "."));
  add(c4, adv);
  f.append(c4);

  /* 5. schedule */
  const A = E.auto, c5 = card(5, "Run it automatically", "Optional. Makes a Home Assistant automation that runs this script.");
  const on = el("input", {type: "checkbox", checked: !!A.on}); on.onchange = () => { A.on = on.checked; changed(); drawForm(); };
  add(c5, el("label", {class: "check"}, on, el("span", {}, "Run on a schedule")));
  if (A.on) {
    const ev = el("input", {type: "number", min: 0, step: 1, value: A.every, style: "width:90px"}); ev.oninput = () => { A.every = ev.value === "" ? "" : +ev.value; changed(); };
    const un = el("select", {style: "width:auto"}, el("option", {value: "minutes"}, "minutes"), el("option", {value: "hours"}, "hours")); un.value = A.unit; un.onchange = () => { A.unit = un.value; changed(); };
    add(c5, el("label", {class: "l"}, "Every"), el("div", {class: "inline"}, ev, un), el("p", {class: "help"}, "0 turns the repeat off. Minutes up to 59, hours up to 23."));
    add(c5, el("label", {class: "l"}, "And when this entity changes (optional)"), picker(null, false, () => A.watch ? [A.watch] : [], a => { A.watch = a[0] || ""; changed(); drawForm(); }));
    if (A.watch) {
      const at = el("input", {value: A.watchAttr, placeholder: "attribute (blank = state)", style: "max-width:240px"}); at.oninput = () => { A.watchAttr = at.value.trim(); changed(); };
      const fr = el("input", {type: "number", min: 0, step: 1, value: A.watchFor, style: "width:90px"}); fr.oninput = () => { A.watchFor = fr.value === "" ? 0 : +fr.value; changed(); };
      add(c5, el("div", {class: "inline", style: "margin-top:8px"}, at, el("span", {class: "dim small"}, "after it has held for"), fr, el("span", {class: "dim small"}, "seconds")));
    }
    add(c5, el("label", {class: "l"}, "Only when someone is home (optional)"), picker(null, true, () => A.home || [], a => { A.home = a; changed(); }),
      el("p", {class: "help"}, "Runs only if any of these is on or home. A zone counts when it has someone in it."));
    if ((F.home_entities || []).length && !(A.home || []).length) add(c5, el("button", {class: "btn sm", style: "margin-top:6px", onclick: () => { A.home = [...F.home_entities]; changed(); drawForm(); }}, "Use my default presence list"));
  }
  f.append(c5);
  gen();
}

function applyPreset(p) {
  const have = usable(), keep = {name: E.name};
  const src = (p.types || []).length ? have.filter(x => p.types.includes(x.type)).map(x => x.id) : [];
  const miss = (p.types || []).filter(t => !have.some(x => x.type === t));
  E = full(Object.assign({}, blankState(), p, {src, picks: clone(p.picks || [])}));
  if (!p.name) E.name = keep.name;
  drawForm(); markDirty();
  const n = $("#pnote"); if (n) n.textContent = miss.length ? "No data source set up for: " + miss.map(t => TYPES[t]).join(", ") + " (add it in Announcements > Settings)." : "";
}

/* ---------- editor: open / dirty / save ---------- */
function markDirty() { dirty = true; paintState(); }
function paintState() {
  const p = $("#estate");
  if (dirty) { p.className = "pill acc"; p.textContent = cur.pushed ? "Changed since last push" : "Unsaved changes"; }
  else if (cur.pushed) { p.className = "pill ok"; p.textContent = "In Home Assistant"; }
  else if (cur.saved) { p.className = "pill warn"; p.textContent = "Saved draft"; }
  else { p.className = "pill plain"; p.textContent = "New"; }
  if (!E) return;
  $("#etitle").textContent = (E.name || "").trim() || "New fact";
  const id = cur.id || fslug(E.name), h = $("#idhelp");
  if (h) h.textContent = cur.id ? "Script id: script." + cur.id + ". It stays the same if you rename this, so automations that call it keep working."
    : "It will be created as script." + id + (takenIds().has(id) ? " (a number is added because that name is taken)." : ".");
}
function openEditor(state, c, note) {
  cur = Object.assign({id: null, isNew: true, pushed: false, saved: false}, c);
  E = full(state);
  $("#msg").textContent = ""; $("#tres").replaceChildren();
  const n = $("#enote"); n.hidden = !note; if (note) n.firstElementChild.textContent = note;
  $("#trycard").hidden = rawMode(); $("#ymldet").hidden = rawMode(); $("#autodet").hidden = rawMode();
  drawForm(); dirty = false; paintState(); showView("edit");
}
function openNew(over) { openEditor(Object.assign(blankState(), over || {}), {isNew: true}); }
function openItem(it) {
  const s = Object.assign(blankState(), it.state || {}, {name: (it.state || {}).name || it.name});
  openEditor(s, {id: it.id, isNew: false, pushed: !!(it.pushed_at || it.in_ha), saved: true});
}
function say(text, cls) { const m = $("#msg"); m.className = "msg " + (cls || ""); m.textContent = text; }
function problems() {
  if (rawMode()) return "";
  if (!(E.task || "").trim()) return "Say what the fact should be about first.";
  if (E.auto.on && !hasTrigger(E)) return "The schedule needs a repeat time or an entity to watch.";
  if (!/^[A-Za-z0-9_\-./]+$/.test(topicOf(E))) return "The file name can only use letters, numbers, underscores, dashes, dots and slashes.";
  return "";
}
async function persist(push) {
  if (push) { const p = problems(); if (p) { say(p, "warn"); return; } }
  const s = clone(E);
  if (!cur.id) cur.id = uniqueId(fslug(s.name));
  const btns = [$("#save"), $("#push")]; btns.forEach(b => b.disabled = true);
  say(push ? "Pushing to Home Assistant..." : "Saving...");
  let r;
  if (push) r = await fapi("push", {id: cur.id, yaml: makeYaml(s), auto_yaml: makeAuto(s, cur.id), state: s, new: cur.isNew && !cur.pushed});
  else r = await fapi("library/save", {id: cur.id, name: s.name, state: s});
  btns.forEach(b => b.disabled = false);
  if (!r.ok) { say(r.detail || r.error || "That failed.", "bad"); if (!cur.saved && !cur.pushed && !cur.fixedId) cur.id = null; paintState(); return; }
  cur.saved = true; cur.isNew = false; if (push) cur.pushed = true; dirty = false; paintState();
  const am = push ? (s.raw == null && s.auto.on ? " The schedule (" + autoSummary(s.auto) + ") is on." : r.auto === "removed" ? " The old schedule was removed." : "") : "";
  say(push ? "Done. script." + cur.id + " is up to date in Home Assistant." + am : "Saved. Home Assistant still has the previous version." + (cur.pushed ? " Push to update it." : ""), "ok");
}
$("#save").onclick = () => persist(false);
$("#push").onclick = () => persist(true);
let armedBack = null;
$("#back").onclick = () => {
  const b = $("#back");
  if (dirty && !armedBack) {
    b.textContent = "Leave without saving?"; b.classList.add("danger");
    armedBack = setTimeout(() => { armedBack = null; b.textContent = "← All facts"; b.classList.remove("danger") }, 3500); return;
  }
  clearTimeout(armedBack); armedBack = null; b.textContent = "← All facts"; b.classList.remove("danger");
  dirty = false; showView("lib"); loadLib();
};
$("#newfact").onclick = () => openNew();

function gen() {
  if (!E) return;
  $("#out").textContent = makeYaml(E);
  const a = makeAuto(E, cur.id || fslug(E.name));
  $("#autoout").textContent = a || (rawMode() ? "" : E.auto.on ? "Set a repeat time or an entity to watch to see the schedule." : "No schedule. Turn on \"Run it automatically\" to make one.");
  const t = $("#topicshow"); if (t) t.textContent = topicOf(E);
  paintState();
}
$("#run").onclick = async () => {
  if (!cur.id) { say("Push it to Home Assistant first.", "warn"); return; }
  say("Starting...");
  const r = await fapi("run", {id: cur.id}); say(r.ok ? "Started the saved script." : (r.detail || r.error), r.ok ? "ok" : "bad");
};
$("#copy").onclick = async () => {
  try { await navigator.clipboard.writeText($("#out").textContent); say("Copied.", "ok"); }
  catch (e) { $("#out").closest("details").open = true; const r = document.createRange(); r.selectNodeContents($("#out")); getSelection().removeAllRanges(); getSelection().addRange(r); say("Selected. Press copy on your device."); }
};

/* ---------- test run ---------- */
const pre = t => el("pre", {}, t == null ? "" : typeof t === "string" ? t : JSON.stringify(t));
function showTest(r) {
  const b = $("#tres"); b.replaceChildren();
  if (r.status === "running") { b.append(el("p", {class: "dim small"}, el("span", {class: "spin"}), "Running. The AI usually answers in a few seconds.")); return; }
  if (r.status === "error") { b.append(el("div", {class: "note bad"}, el("div", {}, el("b", {}, "Test failed"), pre(r.error)))); return; }
  const v = r.values || {};
  if (r.mode !== "data") {
    b.append(el("b", {}, r.mode === "full" ? "What it published" : "What it would publish"), pre(v.fact_out != null && v.fact_out !== "" ? v.fact_out : "(nothing: the AI answer could not be read)"));
    if (r.ai_raw != null && String(r.ai_raw) !== String(v.fact_text)) b.append(el("details", {style: "margin-top:10px"}, el("summary", {}, "What the AI answered, raw"), pre(r.ai_raw)));
  }
  const d = el("details", {open: r.mode === "data", style: "margin-top:10px"}, el("summary", {}, "What it picked and what the AI saw"));
  Object.entries(v).filter(([k]) => !k.startsWith("fact_")).forEach(([k, x]) => d.append(el("p", {class: "dim small", style: "margin-top:8px"}, k.replace("src_", "")), pre(x)));
  b.append(d);
}
async function runTest(mode) {
  const p = problems(); if (p) { $("#tres").textContent = p; return; }
  const btns = ["t-data", "t-text", "t-full"].map(i => $("#" + i)); btns.forEach(x => x.disabled = true);
  try {
    const r = await fapi("test", {mode, yaml: makeYaml(E)});
    if (r.ok === false || r.error) { $("#tres").textContent = r.error; return; }
    for (let i = 0; i < 200; i++) { const t = await (await fetch("./api/facts/test")).json(); showTest(t); if (t.status !== "running") break; await sleep(2500); }
  } catch (e) { $("#tres").textContent = "Failed: " + e; } finally { btns.forEach(x => x.disabled = false); }
}
$("#t-data").onclick = () => runTest("data"); $("#t-text").onclick = () => runTest("text"); $("#t-full").onclick = () => runTest("full");

/* ---------- helper ---------- */
function drawHelper() {
  const v = $("#v-help"); v.replaceChildren();
  const hcard = (t, sub) => { const c = el("div", {class: "card"}, el("div", {class: "ch"}, el("h2", {}, t), sub ? el("p", {}, sub) : null)); v.append(c); return c; };
  if (HEL.back) v.append(el("div", {class: "row"}, el("button", {class: "btn quiet sm", onclick: () => { HEL.back = false; $("#tabs").hidden = false; showView("edit"); }}, "← Back to the editor")));
  const a = hcard("Write it for me", "Say what kind of fact you want. The AI writes the instructions, suggests random lists to keep it varied, and picks a format.");
  const idea = el("textarea", {value: HEL.idea, placeholder: "e.g. A weird fact about a random national park every hour, short and funny."});
  idea.oninput = () => { HEL.idea = idea.value };
  const wb = el("button", {class: "btn primary", style: "margin-top:10px"}, "Write it"), wr = el("div", {style: "margin-top:12px"});
  wb.onclick = async () => {
    if (!HEL.idea.trim()) { wr.textContent = "Type what you want first."; return; }
    wr.textContent = "Asking your AI Task..."; wb.disabled = true;
    const r = await fapi("helper", {idea: HEL.idea, ai: aiName(), sources: usable().map(x => ({id: x.id, label: x.label + " (" + x.type + ")"}))});
    wb.disabled = false;
    if (!r.ok) { wr.textContent = r.error; return; }
    wr.replaceChildren();
    const nm = el("input", {value: r.name || ""}), tk = el("textarea", {value: r.task});
    const fmt = {plain: "just the fact", titled: "a title and the fact", list: "a short list"}[r.style];
    const ub = el("button", {class: "btn good", onclick: () => {
      const s = {name: nm.value || "My fact", task: tk.value, picks: r.picks, style: r.style, titleHint: r.title_hint, heading: r.heading, file: r.file, len: r.length, src: r.sources};
      if (HEL.back && E) { Object.assign(E, s); HEL.back = false; $("#tabs").hidden = false; drawForm(); markDirty(); showView("edit"); }
      else openNew(s);
    }}, HEL.back ? "Use in this fact" : "Start a fact with this");
    wr.append(el("label", {class: "l"}, "Script name"), nm, el("label", {class: "l"}, "Instructions (edit if you like)"), tk,
      el("p", {class: "help"}, "Format: " + fmt + ". " + (r.picks.length ? "Random lists: " + r.picks.map(p => p.name + " (" + itemsOf(p).length + ")").join(", ") + "." : "No random lists.") + (r.file ? " File: " + r.file + "." : "")),
      el("div", {class: "row", style: "margin-top:10px"}, ub));
  };
  a.append(idea, wb, wr, el("p", {class: "help"}, "Using AI Task: " + (aiName() || "none set yet")));

  const b = hcard("Add something to talk about", "Pick an entity and say what you want from it. The AI finds the right attribute and adds it as a data source, shared with Announcements.");
  b.append(el("label", {class: "l"}, "Entity"), picker(null, false, () => HEL.entity ? [HEL.entity] : [], x => { HEL.entity = x[0] || "" }), el("label", {class: "l"}, "What do you want from it?"));
  const gt = el("textarea", {placeholder: "e.g. The city each person is in right now", value: HEL.goal, style: "min-height:70px"}); gt.oninput = () => { HEL.goal = gt.value };
  const tb = el("button", {class: "btn primary", style: "margin-top:10px"}, "Check it"), res = el("div", {style: "margin-top:12px"});
  tb.onclick = async () => {
    if (!HEL.entity || !HEL.goal) { res.textContent = "Pick an entity and say what you want."; return; }
    res.textContent = "Asking your AI Task..."; tb.disabled = true;
    const r = await api("ann/helper", {entity: HEL.entity, goal: HEL.goal, ai: aiName()});
    tb.disabled = false;
    if (!r.ok) { res.textContent = r.error; return; }
    res.replaceChildren(el("p", {}, el("b", {}, r.label), r.attribute ? " (attribute: " + r.attribute + ")" : " (whole entity)"), el("p", {class: "dim small"}, r.note), el("p", {class: "dim small"}, "Preview: " + r.preview));
    const ab = el("button", {class: "btn good", style: "margin-top:8px"}, "Add as data source");
    ab.onclick = async () => {
      ab.disabled = true;
      const fresh = await api("ann/options");  /* start from what is saved now, so nothing made in Announcements is lost */
      if (fresh.error) { ab.textContent = fresh.error; return; }
      if (!Array.isArray(fresh.sources)) fresh.sources = migrate(fresh);
      fresh.sources.push(mk(fresh.sources, "entity", {label: r.label, entity: HEL.entity, attribute: r.attribute}));
      const saved = await api("ann/settings", fresh);
      if (saved.error) { ab.textContent = saved.error; return; }
      S = saved; if (!Array.isArray(S.sources)) S.sources = []; ab.textContent = "Added and saved"; if (E) drawForm();
    };
    res.append(ab);
  };
  b.append(gt, tb, res);
}

/* ---------- settings ---------- */
async function saveSettings() {
  const r = await fapi("settings", F);
  if (r.error) { $("#smsg").className = "msg bad"; $("#smsg").textContent = r.error; return false; }
  F = r; setupNote(); drawSettings(); return true;
}
function drawSettings() {
  const v = $("#v-set"); v.replaceChildren();
  const scard = (t, sub) => { const c = el("div", {class: "card"}, el("div", {class: "ch"}, el("h2", {}, t), sub ? el("p", {}, sub) : null)); v.append(c); return c; };
  if (!ENT.length) v.append(el("div", {class: "note warn"}, el("div", {}, "Could not load your entity list from Home Assistant. You can still type entity ids into any field. Check the add-on's Log tab.")));
  const c1 = scard("Where facts are saved", "Every fact publishes to this MQTT topic prefix plus its own file name.");
  const pf = el("input", {value: F.mqtt_prefix || "", placeholder: "file_reader/overwrite/"}); pf.oninput = () => { F.mqtt_prefix = pf.value.trim() };
  add(c1, el("label", {class: "l"}, "MQTT topic prefix"), pf, el("p", {class: "help"}, "For example file_reader/overwrite/ makes file_reader/overwrite/random_fact.txt for a fact whose file name is random_fact.txt."));
  const c2 = scard("Don't repeat the last fact", "Default sensor the AI is shown so it avoids repeating itself. Each fact can use a different one.");
  add(c2, el("label", {class: "l"}, "Sensor that reads your fact file"), picker(null, false, () => F.last_entity ? [F.last_entity] : [], a => { F.last_entity = a[0] || ""; }));
  const la = el("input", {value: F.last_attribute || "", placeholder: "content", style: "max-width:260px"}); la.oninput = () => { F.last_attribute = la.value.trim() };
  add(c2, el("label", {class: "l"}, "Its attribute (blank = state)"), la);
  const c3 = scard("Someone is home", "The default list for \"Only when someone is home\" in a fact's schedule.");
  add(c3, picker(null, true, () => F.home_entities || [], a => { F.home_entities = a; }), el("p", {class: "help"}, "A zone (like zone.home) counts when someone is in it. People and device trackers count when home. Anything else counts when on."));
  const c4 = scard("Defaults");
  const dl = el("input", {type: "number", value: F.default_length ?? 180, style: "max-width:160px"}); dl.oninput = () => { F.default_length = +dl.value };
  const xr = el("textarea", {value: F.extra_rules || "", placeholder: "e.g. Never mention politics.", style: "min-height:80px"}); xr.oninput = () => { F.extra_rules = xr.value };
  add(c4, el("label", {class: "l"}, "Default length (characters)"), dl, el("label", {class: "l"}, "Rules added to every fact"), xr,
    el("p", {class: "help"}, "The AI Task, data sources and entity list are shared with Announcements. Change them in Announcements > Settings. Using AI Task: " + (aiName() || "none set yet") + "."));
  v.append(el("div", {style: "height:60px"}));
}
$("#setsave").onclick = async () => { if (await saveSettings()) { $("#smsg").className = "msg ok"; $("#smsg").textContent = "Settings saved."; } };

/* ---------- start ---------- */
Promise.all([api("ann/options"), api("facts/options"), api("ann/entities").then(r => Array.isArray(r) ? r : [])]).then(async ([o, f, e]) => {
  if (o.error || f.error) { $("#setupnote").append(el("div", {class: "note bad"}, o.error || f.error)); return; }
  S = o; F = f; ENT = e; if (!Array.isArray(S.sources)) S.sources = migrate(S);
  setupNote(); drawHelper(); drawSettings(); await loadLib(); showView("lib");
});
