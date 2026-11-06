/* Announcements page: library of saved announcements, editor, helper and settings. */
let O = {}, S = {}, ENT = [], LIB = [], FOUND = [], mem = {};
let cur = {id: null, isNew: true, pushed: false}, dirty = false, view = "lib", OPEN = "", HEL = {entity: "", goal: "", idea: ""};
let editorReady = false;

const ind = (t, n) => t.split("\n").map(l => l ? " ".repeat(n) + l : l).join("\n");
const slug = s => (s || "announcement").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 60).replace(/_$/, "") || "announcement";
const aiName = () => S.helper_ai_task_entity || S.ai_task_entity || "";
const ann = (path, body) => api("ann/" + path, body);
const ASK = "Made with Announcement Maker";  // marker the server uses to recognise scripts made here

/* ---------- info sources (what the AI is told) ---------- */
const TYPES = {household: "Household info", locations: "Where everyone is", weather: "Weather", news: "News feed", calendar: "Calendar", todo: "To-do list", trash: "Trash reminder", entity: "Entity / attribute", template: "Custom template"};
const DOMS = {weather: ["weather"], news: ["sensor"], calendar: ["calendar"], todo: ["todo"], trash: ["schedule", "binary_sensor", "input_boolean"], locations: ["sensor"], household: null, entity: null};
function uid(L, type) { let n = 1, id = type; while (L.some(x => x.id === id)) { n++; id = type + "_" + n } return id }
function mk(L, type, o) { const base = (type === "entity" && o && o.label) ? slug(o.label) : type; return Object.assign({id: uid(L, base), type, label: TYPES[type], entity: "", entities: [], attribute: "", extra: "", text: "", days: 7, template: ""}, o || {}) }
function migrate(s) {
  const L = [], add = (t, o) => L.push(mk(L, t, o));
  add("household", {text: s.household_context || "", entity: s.combined_info_entity || "", attribute: s.combined_info_attribute || ""});
  add("locations", {entity: s.locations_entity || ""});
  if (s.weather_entity) add("weather", {entity: s.weather_entity, extra: s.inside_temp_entity || ""});
  if (s.news_entity) add("news", {label: "News headlines", entity: s.news_entity});
  if ((s.calendar_entities || []).length) add("calendar", {label: "Calendar (7 days)", entities: s.calendar_entities});
  if (s.todo_entity) add("todo", {entity: s.todo_entity});
  if (s.trash_entity) add("trash", {entity: s.trash_entity});
  (s.custom_sources || []).forEach(c => add("entity", {label: c.label, entity: c.entity, attribute: c.attribute || ""}));
  return L;
}
const usable = () => (S.sources || []).filter(s => {
  if (["weather", "news", "todo", "trash", "entity"].includes(s.type)) return !!s.entity;
  if (s.type === "calendar") return (s.entities || []).length > 0;
  if (s.type === "template") return !!(s.template || "").trim();
  return true;
});
function genPre(s) {
  const lb = JSON.stringify;
  if (s.type === "weather") return `  - alias: ${lb("Get forecast: " + s.label)}\n    action: weather.get_forecasts\n    target:\n      entity_id: ${s.entity}\n    data:\n      type: daily\n    response_variable: fc_${s.id}\n`;
  if (s.type === "calendar") return `  - alias: ${lb("Get events: " + s.label)}\n    action: calendar.get_events\n    target:\n      entity_id:\n${s.entities.map(c => "        - " + c).join("\n")}\n    data:\n      start_date_time: "{{ now().strftime('%Y-%m-%d 00:00:00') }}"\n      duration:\n        days: ${s.days || 7}\n    response_variable: cal_${s.id}\n`;
  if (s.type === "todo") return `  - alias: ${lb("Get items: " + s.label)}\n    action: todo.get_items\n    target:\n      entity_id: ${s.entity}\n    data:\n      status: needs_action\n    response_variable: todo_${s.id}\n`;
  return "";
}
function auto(s) {
  const E = s.entity, A = s.attribute;
  const ent = A ? `{{ state_attr('${E}', '${A}') }}` : `{{ states('${E}') }} {{ states.${E}.attributes | default('', true) }}`;
  if (s.type === "household") return ((s.text || "") + (E ? " " + (A ? ent : `{{ states('${E}') }}`) : "")).trim();
  if (s.type === "locations") return E ? `{% for name, loc in states.${E}.attributes.items() if name != 'friendly_name' %}{{ name }} is at {{ loc }}. {% endfor %}\nA location of Home means they are at our house.` : "{% for p in states.person %}{{ p.name }} is {{ p.state }}. {% endfor %}";
  if (s.type === "weather") return `Right now it is {{ states('${E}') }}, {{ state_attr('${E}', 'temperature') | float(0) | round(0) | int }} degrees, humidity {{ state_attr('${E}', 'humidity') | float(0) | round(0) | int }} percent, wind {{ state_attr('${E}', 'wind_speed') | float(0) | round(0) | int }}.\nDaily forecast:\n{% for d in fc_${s.id}['${E}']['forecast'][:7] %}- {{ d.datetime[:10] }}: {{ d.condition | default('unknown') }}, high {{ d.temperature | default(0) | float(0) | round(0) | int }}, low {{ d.templow | default(0) | float(0) | round(0) | int }}, rain {{ d.precipitation | default(0) | float(0) | round(2) }}\n{% endfor %}` + (s.extra ? `\nInside temp: {{ states('${s.extra}') | float(0) | round(0) | int }} degrees.` : "");
  if (s.type === "news") return `{% for a in (state_attr('${E}', 'entries') or [])[:25] %}- {{ a.title }}: {{ a.summary }}\n{% endfor %}`;
  if (s.type === "calendar") return `{% for cal, d in cal_${s.id}.items() %}[{{ cal }}]\n{% for e in d.events %}- {{ e.summary }}: {{ e.start }}\n{% else %}(no events)\n{% endfor %}{% endfor %}`;
  if (s.type === "todo") return `{% for item in todo_${s.id}.get('${E}', {}).get('items', []) %}- {{ item.summary }}{% if item.get('due') %} (due {{ item.get('due') }}){% endif %}\n{% else %}Nothing on the list.\n{% endfor %}`;
  if (s.type === "trash") return `{{ 'Trash pickup is tomorrow, remind us to take it to the curb.' if is_state('${E}', 'on') else 'No trash pickup tomorrow, do not mention trash.' }}`;
  if (s.type === "entity") return ent;
  return "";
}
const body = s => s.type === "template" ? s.template : (s.template || auto(s));

/* ---------- presets ---------- */
const PRE = {
  "Weather & News": {name: "Weather and News", types: ["household", "locations", "weather", "news"], task: "Give a quick weather rundown for today and the week ahead, then the top news: local first, then US, then world."},
  "Welcome Home": {name: "Welcome Home", types: ["household", "locations", "calendar", "todo", "trash"], notify: 1, task: "Welcome home whoever just arrived. Go over the to-do list, remind us about the trash if it is going out, then run through what is on the calendar this week."},
  "You're Late": {name: "You're Late", types: ["household", "locations"], task: "Call out every person by name. Roast whoever is not home and work in where they are. Be nicer to whoever is home."},
  "Blank": {name: "My announcement", types: ["household"], task: ""}
};

/* ---------- views ---------- */
function showView(v) {
  view = v;
  const editing = v === "edit";
  $("#chrome").hidden = editing;
  ["lib", "help", "set", "edit"].forEach(k => $("#v-" + k).hidden = k !== v);
  $$("#tabs .tab").forEach(b => b.classList.toggle("on", b.dataset.v === v));
  $("#dock").hidden = v !== "set";
  try { window.scrollTo(0, 0) } catch (e) {}
}
$$("#tabs .tab").forEach(b => b.onclick = () => { showView(b.dataset.v); if (b.dataset.v === "lib") loadLib(); });

function setupNote() {
  const names = {ai_task_entity: "an AI Task", tts_entity: "a text-to-speech engine", speaker: "a main speaker"};
  const miss = Object.keys(names).filter(k => !S[k]);
  const box = $("#setupnote"); box.replaceChildren();
  if (!miss.length) return;
  box.append(el("div", {class: "note warn"}, el("div", {}, el("b", {}, "Finish setup to make announcements. "), "Still needed: " + miss.map(k => names[k]).join(", ") + "."),
    el("button", {class: "btn sm", onclick: () => showView("set")}, "Open Settings")));
}

/* ---------- library ---------- */
const outsSummary = st => {
  const o = st.outs || [], p = [];
  if (o.includes("tts")) p.push("Speaker");
  const a = o.filter(x => x.startsWith("a:")).length, n = o.filter(x => x.startsWith("n:")).length;
  if (a) p.push(a + " Alexa");
  if (n) p.push(n + " phone" + (n > 1 ? "s" : ""));
  return p.join(", ") || "No output";
};
function flash(text, cls) { const m = $("#libmsg"); m.className = "msg " + (cls || ""); m.textContent = text || ""; }

async function loadLib() {
  const d = await ann("library");
  if (d.error) { flash(d.error, "bad"); return; }
  LIB = d.items || []; FOUND = d.found || [];
  $("#libcount").textContent = LIB.length + FOUND.length;
  renderLib();
}

function renderLib() {
  const live = LIB.filter(x => x.pushed_at || x.in_ha).length;
  $("#libsub").textContent = LIB.length + FOUND.length ? (LIB.length + FOUND.length) + " announcement" + (LIB.length + FOUND.length === 1 ? "" : "s") + ", " + live + " in Home Assistant" : "";
  $("#updall").hidden = !LIB.some(x => x.pushed_at);

  /* announcements saved in this browser before the library existed */
  const lg = $("#legacy"); lg.replaceChildren();
  try { mem = JSON.parse(localStorage.getItem("ann") || "{}") } catch (e) { mem = {} }
  const old = Object.keys(mem);
  if (old.length) {
    lg.append(el("div", {class: "note", style: "margin-bottom:12px"}, el("div", {}, el("b", {}, old.length + " saved setup" + (old.length > 1 ? "s" : "") + " found in this browser. "), "Move them into My announcements so they are kept with the add-on."),
      el("button", {class: "btn sm", onclick: moveOld}, "Move them")));
  }

  const box = $("#cards"); box.replaceChildren();
  if (!LIB.length && !FOUND.length) {
    box.style.display = "block";
    box.append(el("div", {class: "card empty"}, el("h3", {}, "No announcements yet"),
      el("p", {}, "Pick what the AI should know, say what it should do, and choose where it plays."),
      el("div", {class: "row"}, el("button", {class: "btn primary", onclick: () => openNew()}, "Make your first announcement"))));
  } else box.style.display = "";
  LIB.forEach(it => box.append(libCard(it)));

  const fb = $("#found"); fb.replaceChildren();
  if (FOUND.length) {
    const c = el("div", {class: "card", style: "margin-top:18px"}, el("div", {class: "ch"}, el("h2", {}, "Made earlier, in Home Assistant"),
      el("p", {}, "These scripts were pushed before saving existed. Open one to edit it here.")));
    const l = el("div", {class: "list"});
    FOUND.forEach(f => {
      const msg = el("span", {class: "dim small"});
      const del = el("button", {class: "btn danger sm"}, "Delete");
      confirmTap(del, "Tap again to delete", () => removeAnn(f.id, true, true));
      l.append(el("div", {class: "li srcrow"}, el("div", {class: "t"}, el("b", {}, f.name), el("small", {class: "mono"}, "script." + f.id)), msg,
        el("button", {class: "btn sm", onclick: () => openFound(f, msg)}, "Open"), del));
    });
    c.append(l); fb.append(c);
  }
}

function libCard(it) {
  const st = it.state || {};
  const status = !it.pushed_at && !it.in_ha ? ["warn", "Draft, not in Home Assistant"] : it.in_ha ? ["ok", "In Home Assistant"] : ["bad", "Missing in Home Assistant"];
  const msg = el("div", {class: "msg", style: "margin:0"});
  const del = el("button", {class: "btn danger sm"}, "Delete");
  confirmTap(del, it.in_ha ? "Tap again: removes the script too" : "Tap again to delete", () => removeAnn(it.id, !!it.in_ha));
  const run = el("button", {class: "btn sm", disabled: !it.in_ha, title: it.in_ha ? "Run it now" : "Push it to Home Assistant first", onclick: async () => {
    run.disabled = true; msg.className = "msg"; msg.textContent = "Starting...";
    const r = await ann("run", {id: it.id}); msg.className = "msg " + (r.ok ? "ok" : "bad"); msg.textContent = r.ok ? "Started." : (r.detail || r.error); run.disabled = false;
  }}, "Run now");
  const dup = el("button", {class: "btn sm", onclick: async () => {
    const id = uniqueId(slug((it.name || it.id) + " copy"));
    const r = await ann("library/save", {id, name: (it.name || it.id) + " copy", state: Object.assign({}, st, {name: (it.name || it.id) + " copy"})});
    if (r.ok) { flash("Copied as a draft: " + id, "ok"); loadLib(); } else flash(r.error, "bad");
  }}, "Duplicate");
  return el("div", {class: "card ann"},
    el("div", {class: "top"}, el("div", {style: "min-width:0"}, el("h3", {}, it.name || it.id), el("div", {class: "dim small mono"}, "script." + it.id)), el("span", {class: "pill " + status[0]}, status[1])),
    el("div", {class: "clamp"}, st.task || "No instructions yet."),
    el("div", {class: "meta"}, el("span", {class: "pill plain"}, (st.src || []).length + " data source" + ((st.src || []).length === 1 ? "" : "s")), el("span", {class: "pill plain"}, outsSummary(st)),
      el("span", {class: "pill plain"}, "Edited " + ago(it.updated))),
    el("div", {class: "acts"}, el("button", {class: "btn primary sm", onclick: () => openItem(it)}, "Edit"), run, dup, del), msg);
}

async function removeAnn(id, alsoScript, found) {
  const r = await ann("library/delete", {id, delete_script: !!alsoScript});
  if (r.ok) { flash(r.script_deleted ? "Deleted " + id + " and its script in Home Assistant." : "Deleted " + id + ".", "ok"); loadLib(); } else flash(r.error, "bad");
}

async function moveOld() {
  let n = 0;
  for (const k of Object.keys(mem)) {
    const id = uniqueId(slug(k)), r = await ann("library/save", {id, name: k, state: Object.assign({}, mem[k], {name: mem[k].name || k})});
    if (r.ok) { n++; delete mem[k]; }
  }
  try { localStorage.setItem("ann", JSON.stringify(mem)) } catch (e) {}
  flash("Moved " + n + " saved setup" + (n === 1 ? "" : "s") + " into the library as drafts.", "ok");
  loadLib();
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
    const r = await ann("push", {id: it.id, yaml: makeYaml(Object.assign({src: [], outs: [], pers: {}}, it.state)), state: it.state});
    if (r.ok) ok++; else bad.push(it.name + ": " + (r.detail || r.error));
  }
  flash("Updated " + ok + " of " + todo.length + " with your current settings." + (bad.length ? " Failed: " + bad.join("; ") : ""), bad.length ? "bad" : "ok");
  loadLib();
}

/* ---------- ids ---------- */
function takenIds() {
  const s = new Set([...LIB.map(x => x.id), ...FOUND.map(x => x.id)]);
  ENT.forEach(e => { if (e.id.startsWith("script.")) s.add(e.id.slice(7)); });
  return s;
}
function uniqueId(base) {
  const t = takenIds(); let id = base, n = 2;
  while (t.has(id)) id = base.slice(0, 55) + "_" + (n++);
  return id;
}

/* ---------- editor: form <-> state ---------- */
function pickBox(parent, attr, key, label, on) {
  const i = el("input", {type: "checkbox", checked: !!on}); i.dataset[attr] = key;
  parent.append(el("label", {class: "pick", title: label}, i, el("span", {}, label)));
}
function st() {
  return {name: $("#name").value, src: $$("[data-s]:checked").map(c => c.dataset.s), outs: $$("[data-o]:checked").map(c => c.dataset.o),
    json: $$('[data-o^="n:"]:checked').length > 0, pers: Object.fromEntries($$("[data-p]").map(t => [t.dataset.p, t.value])),
    usePers: $("#usePers").checked && !!O.personality_select, one: $("#one").value, len: +$("#len").value || 1000,
    task: $("#task").value.trim(), vol: +$("#vol").value / 100, pause: $("#pause").checked};
}
function applyState(s) {
  if (s.name != null) $("#name").value = s.name;
  $$("[data-s]").forEach(c => c.checked = (s.src || []).includes(c.dataset.s));
  $$("[data-o]").forEach(c => c.checked = (s.outs || []).includes(c.dataset.o));
  $$("[data-p]").forEach(t => { if (s.pers && s.pers[t.dataset.p] != null) t.value = s.pers[t.dataset.p] });
  if (s.usePers != null) $("#usePers").checked = !!s.usePers && !!O.personality_select;
  if (s.one) $("#one").value = s.one;
  if (s.len) $("#len").value = s.len;
  $("#task").value = s.task ?? s.extra ?? "";
  if (s.vol != null) $("#vol").value = Math.round(s.vol * 100);
  if (s.pause != null) $("#pause").checked = s.pause;
  gen();
}
/* Rebuild the option lists (sources, outputs, personalities) from settings. Keeps what is already ticked. */
function build() {
  const prev = editorReady ? st() : null;
  O = S; if (!Array.isArray(S.sources)) S.sources = migrate(S);
  ["srcs", "persbox", "presets", "outs"].forEach(i => $("#" + i).replaceChildren());
  usable().forEach(s => pickBox($("#srcs"), "s", s.id, s.label, s.type === "household"));
  if (!usable().length) $("#srcs").append(el("p", {class: "dim small"}, "No data sources yet. Add some in Settings."));
  if (O.speaker && O.tts_entity) pickBox($("#outs"), "o", "tts", "Main speaker (TTS)", 1);
  (O.alexa_targets || []).forEach(a => pickBox($("#outs"), "o", "a:" + a, "Alexa: " + a, 1));
  (O.notify_targets || []).forEach(a => pickBox($("#outs"), "o", "n:" + a, "Phone: " + a, 0));
  if (!$("#outs").children.length) $("#outs").append(el("p", {class: "dim small"}, "No speakers or phones yet. Add them in Settings."));
  [["Hype", "hype_style"], ["Roast", "roast_style"], ["Sweetie Pie", "sweet_style"]].forEach(([k, o]) => {
    const t = el("textarea", {value: O[o] || ""}); t.dataset.p = k; $("#persbox").append(el("label", {class: "l"}, k), t);
  });
  const hasSel = !!O.personality_select;
  $("#selwrap").hidden = !hasSel; $("#usePers").checked = hasSel;
  $("#len").value = O.default_length || 1000; $("#vol").value = O.default_volume || 70;
  Object.entries(PRE).forEach(([k, p]) => {
    $("#presets").append(el("button", {class: "chip", onclick: () => {
      const have = usable().map(x => x.type), miss = p.types.filter(t => !have.includes(t));
      $("#pnote").textContent = miss.length ? "No source set up for: " + miss.map(t => TYPES[t]).join(", ") + " (add it in Settings)." : "";
      applyState({name: p.name, src: usable().filter(x => p.types.includes(x.type)).map(x => x.id), task: p.task,
        outs: $$("[data-o]").map(c => c.dataset.o).filter(o => !o.startsWith("n:") || p.notify)});
      markDirty();
    }}, k));
  });
  if (prev) applyState(prev);
  editorReady = true;
}

/* ---------- editor: script text ---------- */
function makeYaml(s0, o) {
  o = o || {}; const s = o.silent ? Object.assign({}, s0, {outs: [], json: false, pause: false}) : s0;
  const chosen = s.src.map(id => usable().find(x => x.id === id)).filter(Boolean), n = JSON.stringify(s.name || "Announcement"), A = O.speaker || "media_player.SET_ME", players = O.music_players || [], flag = O.talking_flag,
    sp_on = s.outs.includes("tts") && !!O.tts_entity && !!O.speaker, al = (O.alexa_targets || []).filter(a => s.outs.includes("a:" + a)), nt = (O.notify_targets || []).filter(a => s.outs.includes("n:" + a)), speak = sp_on || al.length > 0;
  s.json = s.json || nt.length > 0;
  let y = "alias: " + n + "\ndescription: " + ASK + "\nsequence:\n  - variables:\n      current_time: '{{ now().strftime(''%A, %B %-d %Y %-I:%M %p %Z'') }}'\n";
  chosen.forEach(c => { y += genPre(c) });
  if (chosen.length) y += "  - alias: Load data sources\n    variables:\n" + chosen.map(c => { const b = body(c).trim(); return b ? `      src_${c.id}: |-\n` + ind(b, 8) : `      src_${c.id}: ""` }).join("\n") + "\n";
  if (speak && s.pause && players.length) y += "  - alias: Pause music if playing\n    if:\n      - condition: state\n        entity_id:\n" + players.map(p => "          - " + p).join("\n") + "\n        state: playing\n        match: any\n    then:\n      - action: media_player.media_pause\n        target:\n          entity_id: " + players[0] + "\n";
  if (speak && flag) y += `  - action: input_boolean.turn_on\n    target:\n      entity_id: ${flag}\n`;
  if (sp_on) y += `  - delay:\n      seconds: 3\n  - action: media_player.volume_set\n    target:\n      entity_id: ${A}\n    data:\n      volume_level: ${s.vol}\n`;
  const task = r => {
    const L = ["Current time: {{ current_time }}. Use this to understand what 'tonight', 'this morning', 'Friday' etc. mean."];
    chosen.forEach(c => L.push(c.label.toUpperCase() + ":\n{{ src_" + c.id + " }}"));
    L.push("YOUR TASK: " + (s.task || "Give a short, useful rundown of the information above."));
    L.push("STYLE: " + r + "\nNo markdown, bullet points, quotation marks or emojis. Keep it under " + s.len + " characters. One continuous flowing monologue that sounds natural read aloud by text-to-speech.");
    if (s.json) L.push('Output ONLY a JSON object, no code fences, no other text, exactly like this:\n{"speech": "the full monologue", "notification": "one short sentence banner under 100 characters"}');
    return "- action: ai_task.generate_data\n  data:\n    task_name: " + n + "\n    entity_id: " + (O.ai_task_entity || "ai_task.SET_ME") + "\n    instructions: |-\n" + ind(L.join("\n\n"), 6) + "\n  response_variable: announcement";
  };
  if (s.usePers) {
    y += "  - alias: Generate announcement\n    choose:\n";
    Object.keys(s.pers).forEach(k => { y += `      - conditions:\n          - condition: state\n            entity_id: ${O.personality_select}\n            state: ${JSON.stringify(k)}\n        sequence:\n` + ind(task(s.pers[k]), 10) + "\n" });
  } else y += ind(task(s.pers[s.one]), 2) + "\n";
  const sp = s.json ? "{{ (announcement.data | from_json).speech }}" : "{{ announcement.data }}";
  y += `  - variables:\n      speech: '${sp}'\n  - alias: Deliver\n    parallel:\n`;
  if (sp_on) y += `      - action: tts.speak\n        target:\n          entity_id: ${O.tts_entity}\n        data:\n          message: '{{ speech }}'\n          media_player_entity_id: ${A}\n`;
  if (al.length) y += "      - action: notify.alexa_media\n        data:\n          target:\n" + al.map(a => "            - " + a).join("\n") + "\n          message: '{{ speech }}'\n          data:\n            type: tts\n";
  const isSvc = id => { const e = ENT.find(x => x.id === id); return e ? !!e.svc : /^notify\.mobile_app_/.test(id) };
  const ne = nt.filter(i => !isSvc(i)), ns = nt.filter(isSvc), msg = "          title: " + n + "\n          message: '{{ (announcement.data | from_json).notification }}'\n";
  if (ne.length) y += "      - action: notify.send_message\n        target:\n          entity_id:\n" + ne.map(a => "            - " + a).join("\n") + "\n        data:\n" + msg;
  ns.forEach(a => { y += "      - action: " + a + "\n        data:\n" + msg });
  if (!sp_on && !al.length && !nt.length) y += "      - delay:\n          seconds: 1\n";
  if (sp_on) y += `  - delay:\n      seconds: 15\n  - wait_for_trigger:\n      - trigger: state\n        entity_id: ${A}\n        to:\n          - paused\n          - idle\n    timeout:\n      seconds: 120\n    continue_on_timeout: true\n  - delay:\n      seconds: 5\n`;
  else if (al.length) y += "  - delay:\n      seconds: 40\n";
  if (speak && flag) y += `  - action: input_boolean.turn_off\n    target:\n      entity_id: ${flag}\n`;
  if (speak && s.pause && players.length) y += "  - if:\n      - condition: state\n        entity_id: " + players[0] + "\n        state: paused\n    then:\n      - action: media_player.media_play\n        target:\n          entity_id: " + players[0] + "\n";
  return y;
}

/* Read a script made by this tool back into form state. Used for scripts that predate the library. */
function recover(cfg) {
  const s = {name: cfg.alias || "", src: [], outs: [], json: false, pers: {}, usePers: false, one: "Hype", len: O.default_length || 1000, task: "", vol: (O.default_volume || 70) / 100, pause: false};
  const notes = [], acts = [];
  const walk = a => (Array.isArray(a) ? a : [a]).forEach(x => {
    if (!x || typeof x !== "object") return;
    acts.push(x);
    ["sequence", "then", "else", "parallel", "default"].forEach(k => x[k] && walk(x[k]));
    (Array.isArray(x.choose) ? x.choose : []).forEach(c => walk(c.sequence || []));
  });
  walk(cfg.sequence || []);
  const ok = new Set(usable().map(x => x.id)), lost = [];
  acts.forEach(x => { if (x.variables) Object.keys(x.variables).filter(k => k.startsWith("src_")).forEach(k => { const id = k.slice(4); (ok.has(id) ? s.src : lost).push(id) }) });
  if (lost.length) notes.push("These data sources no longer exist in Settings and were dropped: " + lost.join(", ") + ".");
  s.pause = acts.some(x => x.alias === "Pause music if playing");
  acts.forEach(x => {
    const a = x.action || "", d = x.data || {};
    if (a === "media_player.volume_set" && d.volume_level != null) s.vol = +d.volume_level;
    if (a === "tts.speak") s.outs.push("tts");
    if (a === "notify.alexa_media") [].concat(d.target || []).forEach(t => s.outs.push("a:" + t));
    if (a === "notify.send_message") [].concat((x.target || {}).entity_id || []).forEach(t => s.outs.push("n:" + t));
    else if (a.startsWith("notify.") && a !== "notify.alexa_media") s.outs.push("n:" + a);
  });
  const ai = acts.filter(x => x.action === "ai_task.generate_data");
  const text = ai.length ? String((ai[0].data || {}).instructions || "") : "";
  const m = text.match(/YOUR TASK: ([\s\S]*?)\n\nSTYLE: /); if (m) s.task = m[1].trim();
  const l = text.match(/under (\d+) characters/); if (l) s.len = +l[1];
  s.json = text.includes("Output ONLY a JSON object");
  const styleOf = t => { const z = String(t || "").match(/STYLE: ([\s\S]*?)\nNo markdown/); return z ? z[1] : null };
  const ps = acts.find(x => Array.isArray(x.choose) && x.choose.some(c => JSON.stringify(c).includes("ai_task.generate_data")));
  if (ps && O.personality_select) {
    s.usePers = true;
    ps.choose.forEach(c => {
      const cond = (c.conditions || [])[0] || {}, a = (c.sequence || []).find(z => z.action === "ai_task.generate_data");
      if (cond.state && a) { const sy = styleOf((a.data || {}).instructions); if (sy != null) s.pers[cond.state] = sy; }
    });
  } else if (text) {
    const sy = styleOf(text), keys = {Hype: O.hype_style, Roast: O.roast_style, "Sweetie Pie": O.sweet_style};
    const hit = Object.keys(keys).find(k => keys[k] === sy);
    if (hit) s.one = hit; else if (sy != null) { s.pers = {Hype: sy}; s.one = "Hype"; notes.push("It used a custom personality style, which is now filed under Hype."); }
  }
  s.outs = [...new Set(s.outs)];
  return {state: s, notes};
}

/* ---------- editor: open / dirty / save ---------- */
function markDirty() { dirty = true; paintState(); }
function paintState() {
  const p = $("#estate");
  if (dirty) { p.className = "pill acc"; p.textContent = cur.pushed ? "Changed since last push" : "Unsaved changes"; }
  else if (cur.pushed) { p.className = "pill ok"; p.textContent = "In Home Assistant"; }
  else if (cur.saved) { p.className = "pill warn"; p.textContent = "Saved draft"; }
  else { p.className = "pill plain"; p.textContent = "New"; }
  $("#etitle").textContent = $("#name").value.trim() || "New announcement";
  const id = cur.id || slug($("#name").value);
  $("#idhelp").textContent = cur.id ? "Script id: script." + cur.id + ". It stays the same if you rename this, so automations that call it keep working."
    : "It will be created as script." + id + (takenIds().has(id) ? " (a number is added because that name is taken)." : ".");
  $("#presetwrap").hidden = !cur.isNew;
}
function openEditor(state, c, note) {
  cur = Object.assign({id: null, isNew: true, pushed: false, saved: false}, c);
  $("#msg").textContent = ""; $("#tres").replaceChildren(); $("#pnote").textContent = "";
  const lg = $("#elegacy"); lg.hidden = !note; if (note) lg.firstElementChild.textContent = note;
  applyState(state); dirty = false; paintState(); showView("edit");
}
const blankState = () => ({name: "My announcement", src: usable().filter(x => x.type === "household").map(x => x.id),
  outs: $$("[data-o]").map(c => c.dataset.o).filter(o => !o.startsWith("n:")), task: "", len: O.default_length || 1000, vol: (O.default_volume || 70) / 100, pause: true,
  usePers: !!O.personality_select, one: "Hype", pers: Object.fromEntries([["Hype", O.hype_style], ["Roast", O.roast_style], ["Sweetie Pie", O.sweet_style]])});
function openNew(over) { openEditor(Object.assign(blankState(), over || {}), {isNew: true}); }
function openItem(it) {
  const s = Object.assign(blankState(), it.state || {}, {name: (it.state || {}).name || it.name});
  openEditor(s, {id: it.id, isNew: false, pushed: !!(it.pushed_at || it.in_ha), saved: true});
}
async function openFound(f, msgEl) {
  msgEl.textContent = "Loading...";
  const r = await ann("script?id=" + encodeURIComponent(f.id));
  if (!r.ok) { msgEl.textContent = r.error; return; }
  msgEl.textContent = "";
  const {state, notes} = recover(r.config);
  openEditor(Object.assign(blankState(), state), {id: f.id, isNew: false, pushed: true, saved: false},
    "Opened from Home Assistant. Pushing rebuilds the script from this form, so anything you changed by hand in the script will be replaced." + (notes.length ? " " + notes.join(" ") : ""));
}

function say(text, cls) { const m = $("#msg"); m.className = "msg " + (cls || ""); m.textContent = text; }
async function persist(push) {
  const s = st();
  if (!cur.id) cur.id = uniqueId(slug(s.name));
  const btns = [$("#save"), $("#push")]; btns.forEach(b => b.disabled = true);
  say(push ? "Pushing to Home Assistant..." : "Saving...");
  let r;
  if (push) r = await ann("push", {id: cur.id, yaml: makeYaml(s), state: s, new: cur.isNew && !cur.pushed});
  else r = await ann("library/save", {id: cur.id, name: s.name, state: s});
  btns.forEach(b => b.disabled = false);
  if (!(r.ok)) { say(r.detail || r.error || "That failed.", "bad"); if (!cur.saved && !cur.pushed) cur.id = null; paintState(); return; }
  cur.saved = true; cur.isNew = false; if (push) cur.pushed = true; dirty = false; paintState();
  say(push ? "Done. script." + cur.id + " is up to date in Home Assistant." : "Saved. Home Assistant still has the previous version." + (cur.pushed ? " Push to update it." : ""), "ok");
}
$("#save").onclick = () => persist(false);
$("#push").onclick = () => persist(true);

let armedBack = null;
$("#back").onclick = () => {
  const b = $("#back");
  if (dirty && !armedBack) {
    b.textContent = "Leave without saving?"; b.classList.add("danger");
    armedBack = setTimeout(() => { armedBack = null; b.textContent = "← All announcements"; b.classList.remove("danger") }, 3500); return;
  }
  clearTimeout(armedBack); armedBack = null; b.textContent = "← All announcements"; b.classList.remove("danger");
  dirty = false; showView("lib"); loadLib();
};
$("#newann").onclick = () => openNew();
$("#gohelp").onclick = () => { showView("help"); $("#tabs").hidden = true; HEL.back = true; drawHelper(); };  /* the helper hands its text back to this editor */

function gen() {
  const s = st(); $("#out").textContent = makeYaml(s);
  $("#onewrap").hidden = s.usePers; $("#volv").textContent = Math.round(s.vol * 100); paintState();
}
document.addEventListener("input", e => { if (e.target.closest("#v-edit")) { gen(); markDirty(); } });
document.addEventListener("change", e => { if (e.target.closest("#v-edit")) { gen(); markDirty(); } });

$("#run").onclick = async () => {
  if (!cur.id) { say("Push it to Home Assistant first.", "warn"); return; }
  say("Starting...");
  const r = await ann("run", {id: cur.id}); say(r.ok ? "Started the saved script." : (r.detail || r.error), r.ok ? "ok" : "bad");
};
$("#copy").onclick = async () => {
  try { await navigator.clipboard.writeText($("#out").textContent); say("Copied.", "ok"); }
  catch (e) { $("#out").closest("details").open = true; const r = document.createRange(); r.selectNodeContents($("#out")); getSelection().removeAllRanges(); getSelection().addRange(r); say("Selected. Press copy on your device."); }
};

/* ---------- test run ---------- */
const pre = t => el("pre", {}, t == null ? "" : String(t));
function showTest(r) {
  const b = $("#tres"); b.replaceChildren();
  if (r.status === "running") { b.append(el("p", {class: "dim small"}, el("span", {class: "spin"}), "Running. With sound this can take a couple of minutes.")); return; }
  if (r.status === "error") { b.append(el("div", {class: "note bad"}, el("div", {}, el("b", {}, "Test failed"), pre(r.error)))); return; }
  if (r.speech != null) b.append(el("b", {}, "What it said"), pre(r.speech));
  const d = el("details", {open: r.speech == null, style: "margin-top:10px"}, el("summary", {}, "What the AI saw"));
  Object.entries(r.sources || {}).forEach(([k, v]) => d.append(el("p", {class: "dim small", style: "margin-top:8px"}, k.replace("src_", "")), pre(v)));
  b.append(d);
}
async function runTest(mode) {
  const s = st(); if (!s.src.length) { $("#tres").textContent = "Tick at least one data source first."; return; }
  const btns = ["t-data", "t-text", "t-full"].map(i => $("#" + i)); btns.forEach(x => x.disabled = true);
  try {
    const r = await ann("test", {mode, yaml: makeYaml(s, {silent: mode !== "full"})});
    if (r.ok === false || r.error) { $("#tres").textContent = r.error; return; }
    for (let i = 0; i < 200; i++) { const t = await (await fetch("./api/ann/test")).json(); showTest(t); if (t.status !== "running") break; await sleep(2500); }
  } catch (e) { $("#tres").textContent = "Failed: " + e; } finally { btns.forEach(x => x.disabled = false); }
}
$("#t-data").onclick = () => runTest("data"); $("#t-text").onclick = () => runTest("text"); $("#t-full").onclick = () => runTest("full");

/* ---------- entity picker ---------- */
function picker(doms, multi, get, set) {
  const w = el("div", {class: "picker"}), chips = el("div", {class: "chips"}), inp = el("input", {}), list = el("div", {class: "plist"});
  inp.placeholder = "Search or type an entity id" + (doms ? " (" + doms.map(d => d + ".*").join(", ") + ")" : "");
  const draw = () => { chips.replaceChildren(); get().forEach(v => chips.append(el("button", {class: "chip on x", onclick: () => { set(get().filter(x => x !== v)); draw() }}, v))); inp.hidden = !multi && get().length > 0 };
  const pick = id => { set(multi ? [...new Set([...get(), id])] : [id]); inp.value = ""; list.replaceChildren(); draw() };
  const show = () => {
    const t = inp.value.trim().toLowerCase(); list.replaceChildren();
    const add = (txt, sub, id) => list.append(el("div", {class: "pi", onpointerdown: ev => { ev.preventDefault(); pick(id) }}, txt, sub ? el("small", {}, sub) : null));
    if (/^[a-z_]+\.[a-z0-9_]+$/.test(t) && !ENT.some(e => e.id === t) && (!doms || doms.includes(t.split(".")[0]))) add("Use typed value: " + t, "", t);
    ENT.filter(e => !doms || doms.includes(e.id.split(".")[0])).filter(e => !t || e.id.includes(t) || e.name.toLowerCase().includes(t)).slice(0, 30).forEach(e => add(e.name, e.id, e.id));
  };
  inp.oninput = show; inp.onfocus = show; inp.onblur = () => setTimeout(() => list.replaceChildren(), 200);
  draw(); w.append(chips, inp, list); return w;
}

/* ---------- helper ---------- */
function drawHelper() {
  const v = $("#v-help"); v.replaceChildren();
  const card = (t, sub) => { const c = el("div", {class: "card"}, el("div", {class: "ch"}, el("h2", {}, t), sub ? el("p", {}, sub) : null)); v.append(c); return c; };
  if (HEL.back) v.append(el("div", {class: "row"}, el("button", {class: "btn quiet sm", onclick: () => { HEL.back = false; $("#tabs").hidden = false; showView("edit"); }}, "← Back to the editor")));
  const info = "Using AI Task: " + (aiName() || "none set yet (see Settings)");
  const a = card("Write the instructions for me", "Say it your way. The AI writes clear instructions and picks the data to include.");
  const idea = el("textarea", {value: HEL.idea, placeholder: "e.g. Look at the weather for the week and tell me about it, but only if my work calendar has something on."});
  idea.oninput = () => { HEL.idea = idea.value };
  const wb = el("button", {class: "btn primary", style: "margin-top:10px"}, "Write it"), wr = el("div", {style: "margin-top:12px"});
  wb.onclick = async () => {
    if (!HEL.idea.trim()) { wr.textContent = "Type what you want first."; return; }
    wr.textContent = "Asking your AI Task..."; wb.disabled = true;
    const r = await ann("helper", {mode: "instructions", idea: HEL.idea, ai: aiName(), sources: usable().map(x => ({id: x.id, label: x.label + " (" + x.type + ")"})), calendars: (S.sources || []).filter(x => x.type === "calendar").flatMap(x => x.entities)});
    wb.disabled = false;
    if (!r.ok) { wr.textContent = r.error; return; }
    wr.replaceChildren(); const nm = el("input", {value: r.name || ""}), tk = el("textarea", {value: r.task});
    const labels = usable().filter(x => r.sources.includes(x.id)).map(x => x.label);
    const ub = el("button", {class: "btn good", onclick: () => {
      const s = {name: nm.value || "My announcement", src: r.sources.length ? r.sources : blankState().src, task: tk.value};
      if (HEL.back) { applyState(Object.assign(st(), s)); markDirty(); HEL.back = false; $("#tabs").hidden = false; showView("edit"); }
      else openNew(s);
    }}, HEL.back ? "Use in this announcement" : "Start an announcement with this");
    wr.append(el("label", {class: "l"}, "Script name"), nm, el("label", {class: "l"}, "Instructions (edit if you like)"), tk, el("p", {class: "help"}, "Will tick: " + (labels.join(", ") || "nothing extra")), el("div", {class: "row", style: "margin-top:10px"}, ub));
  };
  a.append(idea, wb, wr, el("p", {class: "help"}, info));
  const b = card("Add something to talk about", "Pick an entity and say what you want from it. The AI finds the right attribute and adds it as a data source.");
  b.append(el("label", {class: "l"}, "Entity"), picker(null, false, () => HEL.entity ? [HEL.entity] : [], x => { HEL.entity = x[0] || "" }), el("label", {class: "l"}, "What do you want from it?"));
  const gt = el("textarea", {placeholder: "e.g. Days left until the concert and where it is", value: HEL.goal, style: "min-height:70px"}); gt.oninput = () => { HEL.goal = gt.value };
  const tb = el("button", {class: "btn primary", style: "margin-top:10px"}, "Check it"), res = el("div", {style: "margin-top:12px"});
  tb.onclick = async () => {
    if (!HEL.entity || !HEL.goal) { res.textContent = "Pick an entity and say what you want."; return; }
    res.textContent = "Asking your AI Task..."; tb.disabled = true;
    const r = await ann("helper", {entity: HEL.entity, goal: HEL.goal, ai: aiName()});
    tb.disabled = false;
    if (!r.ok) { res.textContent = r.error; return; }
    res.replaceChildren(el("p", {}, el("b", {}, r.label), r.attribute ? " (attribute: " + r.attribute + ")" : " (whole entity)"), el("p", {class: "dim small"}, r.note), el("p", {class: "dim small"}, "Preview: " + r.preview));
    const ab = el("button", {class: "btn good", style: "margin-top:8px"}, "Add as data source");
    ab.onclick = async () => { S.sources.push(mk(S.sources, "entity", {label: r.label, entity: HEL.entity, attribute: r.attribute})); await saveSettings(); ab.textContent = "Added and saved"; ab.disabled = true; };
    res.append(ab);
  };
  b.append(gt, tb, res);
}

/* ---------- settings ---------- */
const FIELDS = {
  core: [["ai_task_entity", "AI Task", ["ai_task"], 0, "Writes the announcement text"], ["tts_entity", "Text-to-speech engine", ["tts"], 0, "Turns the text into speech"], ["speaker", "Main speaker", ["media_player"], 0, "Where speech plays"]],
  more: [["alexa_targets", "Extra Alexa speakers", ["media_player"], 1, "Spoken through the alexa_media integration"], ["music_players", "Music players to pause", ["media_player"], 1, "Paused while it talks, resumed after"], ["talking_flag", "Talking flag", ["input_boolean"], 0, "Optional. Turned on while it talks"], ["personality_select", "Personality dropdown", ["input_select"], 0, "Optional. An input_select with Hype, Roast, Sweetie Pie"]],
  phones: [["notify_targets", "Phone notifications", ["notify"], 1, 'Type or pick. Phones show as "service"']]
};
async function saveSettings() { const r = await ann("settings", S); if (r.error) { $("#smsg").className = "msg bad"; $("#smsg").textContent = r.error; return; } S = r; if (!Array.isArray(S.sources)) S.sources = []; build(); setupNote(); drawHelper(); drawSettings(); }
const varNames = s => ({weather: "fc_" + s.id + " (forecast response)", calendar: "cal_" + s.id + " (events response)", todo: "todo_" + s.id + " (items response)"}[s.type] || "");

function editor(s) {
  const box = el("div", {class: "card sub"}), f = (l, node) => box.append(el("label", {class: "l"}, l), node);
  const tpl = el("textarea", {class: "code"});
  const sync = () => { if (!s.template) tpl.value = auto(s) };
  const txt = (k, ph) => { const i = el("input", {placeholder: ph || "", value: s[k] || ""}); i.oninput = () => { s[k] = i.value; sync() }; return i };
  const one = (k, d, l) => f(l, picker(d, false, () => s[k] ? [s[k]] : [], a => { s[k] = a[0] || ""; sync() }));
  f("Name (shown in the editor and told to the AI)", (() => { const i = el("input", {value: s.label}); i.oninput = () => { s.label = i.value }; return i })());
  if (s.type === "household") { const t = el("textarea", {value: s.text || "", placeholder: "Who lives here, pets, friends, running jokes..."}); t.oninput = () => { s.text = t.value; sync() }; f("Text", t); one("entity", null, "Extra entity to append (optional)"); f("Its attribute (blank = state)", txt("attribute")); }
  if (s.type === "locations") one("entity", DOMS.locations, "Sensor whose attributes are name: place (blank = use people)");
  if (s.type === "weather") { one("entity", DOMS.weather, "Weather entity"); one("extra", ["sensor"], "Inside temperature sensor (optional)"); }
  if (s.type === "news") one("entity", DOMS.news, 'News feed sensor (needs an "entries" attribute)');
  if (s.type === "calendar") { f("Calendars", picker(DOMS.calendar, true, () => s.entities || [], a => { s.entities = a; sync() })); const d = el("input", {type: "number", value: s.days || 7}); d.oninput = () => { s.days = +d.value || 7; sync() }; f("Days ahead", d); }
  if (s.type === "todo") one("entity", DOMS.todo, "To-do list");
  if (s.type === "trash") one("entity", DOMS.trash, "Entity that is on when pickup is tomorrow");
  if (s.type === "entity") { one("entity", null, "Entity"); f("Attribute (blank = state + all attributes)", txt("attribute")); }
  tpl.value = body(s); tpl.oninput = () => { if (s.type === "template") s.template = tpl.value; else s.template = tpl.value === auto(s) ? "" : tpl.value };
  const hint = varNames(s);
  box.append(el("label", {class: "l"}, s.type === "template" ? "Template (Home Assistant Jinja)" : "Template the script uses (edit to fix it)"), tpl,
    el("p", {class: "help"}, (hint ? "Available variable: " + hint + ". " : "") + "This text becomes variable src_" + s.id + ". Use Preview the data in the editor to see what it renders."));
  if (s.type !== "template") box.append(el("button", {class: "btn sm", style: "margin-top:8px", onclick: () => { s.template = ""; tpl.value = auto(s) }}, "Reset template to auto"));
  return box;
}

function drawSettings() {
  const v = $("#v-set"); v.replaceChildren();
  const card = (t, sub) => { const c = el("div", {class: "card"}, el("div", {class: "ch"}, el("h2", {}, t), sub ? el("p", {}, sub) : null)); v.append(c); return c; };
  if (!ENT.length) v.append(el("div", {class: "note warn"}, el("div", {}, "Could not load your entity list from Home Assistant. You can still type entity ids into any field. Check the add-on's Log tab.")));
  const fields = (c, list) => list.forEach(([k, l, d, m, h]) => {
    c.append(el("label", {class: "l"}, l), picker(d, !!m, () => m ? (S[k] || []) : (S[k] ? [S[k]] : []), a => { S[k] = m ? a : (a[0] || "") }));
    if (h) c.append(el("p", {class: "help"}, h));
  });
  fields(card("Voice and speakers", "The AI Task, text-to-speech engine and main speaker are required. The rest is optional."), [...FIELDS.core, ...FIELDS.more]);
  fields(card("Phones"), FIELDS.phones);

  const si = card("Data sources", "These feed the data list in the editor. Edit one to fix it, remove ones you don't want, or add more.");
  const okIds = new Set(usable().map(x => x.id)), L = el("div", {class: "stack"});
  (S.sources || []).forEach((s, i) => {
    const row = el("div", {}), top = el("div", {class: "li srcrow", style: "display:flex;align-items:center;gap:10px"});
    const eb = el("button", {class: "btn sm", onclick: () => { OPEN = OPEN === s.id ? "" : s.id; drawSettings() }}, OPEN === s.id ? "Close" : "Edit");
    const db = el("button", {class: "btn danger sm"}, "Remove");
    confirmTap(db, "Tap again", () => { S.sources.splice(i, 1); if (OPEN === s.id) OPEN = ""; drawSettings() });
    top.append(el("div", {class: "t"}, el("b", {}, s.label), el("small", {}, TYPES[s.type] + (s.template && s.type !== "template" ? " · custom template" : "") + (okIds.has(s.id) ? "" : " · needs an entity before it shows up"))), eb, db);
    row.append(top); if (OPEN === s.id) row.append(el("div", {style: "margin-top:8px"}, editor(s)));
    L.append(row);
  });
  if (!(S.sources || []).length) L.append(el("p", {class: "dim small"}, "No sources yet."));
  si.append(L);
  const sel = el("select", {style: "width:auto"}); Object.entries(TYPES).forEach(([k, l]) => sel.append(el("option", {value: k}, l)));
  si.append(el("div", {class: "row", style: "margin-top:12px"}, sel, el("button", {class: "btn", onclick: () => { const n = mk(S.sources, sel.value); S.sources.push(n); OPEN = n.id; drawSettings() }}, "Add source")));

  const s2 = card("Personalities and defaults");
  [["hype_style", "Hype style", "t"], ["roast_style", "Roast style", "t"], ["sweet_style", "Sweetie Pie style", "t"], ["default_volume", "Default volume %", "n"], ["default_length", "Default length (characters)", "n"]].forEach(([k, l, t]) => {
    const f = el(t === "t" ? "textarea" : "input", t === "n" ? {type: "number", value: S[k] ?? "", style: "max-width:160px"} : {value: S[k] ?? ""});
    f.oninput = () => { S[k] = t === "n" ? +f.value : f.value };
    s2.append(el("label", {class: "l"}, l), f);
  });

  const s4 = card("Move settings to another install");
  const io = el("textarea", {class: "code", placeholder: "Export puts your settings here as JSON. Paste settings here and press Import."});
  s4.append(el("div", {class: "row"},
    el("button", {class: "btn sm", onclick: () => { io.value = JSON.stringify(S, null, 1) }}, "Export"),
    el("button", {class: "btn sm", onclick: () => { try { const j = JSON.parse(io.value); S = Object.assign({}, S, j); if (!Array.isArray(j.sources)) S.sources = migrate(S); drawSettings(); $("#smsg").textContent = "Imported. Review, then save."; } catch (e) { $("#smsg").textContent = "That is not valid JSON." } }}, "Import")), io,
    el("p", {class: "help"}, "Your saved announcements are included when you use the Backup tab."));
  v.append(el("div", {style: "height:60px"}));
}
$("#setsave").onclick = async () => { await saveSettings(); $("#smsg").className = "msg ok"; $("#smsg").textContent = "Settings saved."; };
$("#setfill").onclick = () => {
  let n = 0; Object.values(FIELDS).flat().forEach(([k, , d, m]) => { if (m || S[k]) return; const c = ENT.filter(e => d.includes(e.id.split(".")[0])); if (c.length === 1) { S[k] = c[0].id; n++ } });
  drawSettings(); $("#smsg").className = "msg"; $("#smsg").textContent = "Filled " + n + " (only where there was one match). Save to keep.";
};

/* ---------- start ---------- */
Promise.all([api("ann/options"), api("ann/entities").then(r => Array.isArray(r) ? r : [])]).then(async ([o, e]) => {
  if (o.error) { $("#setupnote").append(el("div", {class: "note bad"}, o.error)); return; }
  S = o; ENT = e; build(); setupNote(); drawHelper(); drawSettings(); await loadLib(); showView("lib");
});
