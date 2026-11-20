/* Personalized Info: more linked entities.
 * Adds a "More entities" list to each person's Home Assistant section, and a "House entities" panel at the top.
 * run.py puts this script after the page's own script, so it can use the page's globals (D, LIVE, h, touch, draw, status).
 */
(function () {
  const css = document.createElement('style');
  css.textContent =
    '#house-panel{max-width:820px;margin:0 auto;padding:10px 10px 0}' +
    '.xrow{border:1px solid var(--line);border-radius:8px;padding:8px;margin-top:10px}' +
    '.xrow .xtop{display:flex;gap:8px;align-items:center}' +
    '.xrow .xtop input{flex:1}' +
    '.xrow input[type=text]{margin-top:6px}' +
    '.xrow .pickrow{margin-bottom:0}' +
    '.xtext{white-space:pre-wrap;font-size:13px;color:var(--ok);margin-top:8px}';
  document.head.append(css);

  const clean = v => String(v == null ? '' : v);

  /* A list of entity rows. items is edited in place. */
  function rows(items, opts) {
    const wrap = h('div');
    items.forEach((it, i) => {
      const ent = h('input', {
        type: 'text', value: clean(it.entity_id), placeholder: 'entity id, e.g. sensor.alex_heart_rate',
        oninput: e => { it.entity_id = e.target.value.trim(); opts.onChange(); }
      });
      ent.setAttribute('list', 'ents');
      const lab = h('input', {
        type: 'text', value: clean(it.label), placeholder: 'Label (optional): how it is named in the status',
        oninput: e => { const v = e.target.value; if (v.trim()) it.label = v; else delete it.label; opts.onChange(); }
      });
      const att = h('input', {
        type: 'text', value: Array.isArray(it.attributes) ? it.attributes.join(', ') : clean(it.attributes),
        placeholder: 'Attributes to include too (optional), comma separated',
        oninput: e => { const v = e.target.value; if (v.trim()) it.attributes = v; else delete it.attributes; opts.onChange(); }
      });
      const say = h('label', {className: 'pickrow'},
        h('input', {type: 'checkbox', checked: it.say !== false, onchange: e => { it.say = e.target.checked; opts.onChange(); }}),
        h('span', {textContent: opts.sayText}));
      wrap.append(h('div', {className: 'xrow'},
        h('div', {className: 'xtop'}, ent,
          h('button', {className: 'del', textContent: '✕', title: 'Remove', onclick: () => { items.splice(i, 1); opts.onRemove(); }})),
        lab, att, say));
    });
    return wrap;
  }

  /* ---------- each person ---------- */
  function moreEntities(g, k, p) {
    const box = h('div', {className: 'ha'});
    const items = () => (p.links && Array.isArray(p.links.more)) ? p.links.more : [];
    const write = arr => {
      if (!p.links || typeof p.links !== 'object') p.links = {};
      if (arr.length) p.links.more = arr; else delete p.links.more;
      if (!Object.keys(p.links).length) delete p.links;
    };
    const cur = items();
    const msg = h('div', {className: 'meta'}), out = h('div');
    box.append(h('label', {textContent: 'More entities'}),
      h('div', {className: 'hint', textContent: 'Link anything else that tells the AI more about them: heart rate, steps, which room they are in, their car, a smart lock, a fitness or health sensor. Their current values go in the info sensor, and into the one-line status when "Say it" is ticked.'}),
      rows(cur, {
        sayText: 'Say it in their one-line status',
        onChange: () => touch(),
        onRemove: () => { write(cur); touch(); draw(); }
      }));
    box.append(h('div', {className: 'add'},
      h('button', {textContent: '+ Add entity', onclick: () => {
        const arr = items(); arr.push({entity_id: '', say: true}); write(arr); touch(); draw();
      }}),
      h('button', {textContent: 'Find more', onclick: async () => {
        if (dirty) { msg.textContent = 'Save first, then find.'; return; }
        msg.textContent = 'Looking...'; out.replaceChildren();
        let r;
        try { r = await (await fetch('api/suggest_more?person=' + encodeURIComponent(k))).json(); }
        catch (e) { msg.textContent = 'That failed. Check the app log.'; return; }
        if (!r.ok) { msg.textContent = r.error; return; }
        if (!r.items.length) { msg.textContent = 'Nothing new found. Add entities by hand.'; return; }
        msg.textContent = 'Tick the ones you want, then Add. (Phone battery, charging, activity, Wi-Fi and steps are already picked up from the phone.)';
        const pick = {};
        out.replaceChildren(...r.items.map(x => h('label', {className: 'pickrow'},
          h('input', {type: 'checkbox', onchange: e => { pick[x.entity_id] = e.target.checked; }}),
          h('span', {textContent: x.name + ' (' + x.entity_id + ') is ' + x.state + '  · ' + x.group}))),
          h('div', {className: 'add'}, h('button', {className: 'pri', textContent: 'Add selected', onclick: () => {
            const arr = items(); let n = 0;
            for (const x of r.items) {
              if (!pick[x.entity_id] || arr.some(a => a.entity_id === x.entity_id)) continue;
              const it = {entity_id: x.entity_id, say: true};
              if (x.label && x.label !== x.name) it.label = x.label;
              arr.push(it); n++;
            }
            if (!n) { msg.textContent = 'Nothing ticked.'; return; }
            write(arr); touch(); draw();
            status('Added ' + n + ' entit' + (n === 1 ? 'y' : 'ies') + '. Check them, then Save.', 'warn');
          }})));
      }})), msg, out);
    const now = (LIVE.status[k] || {}).extra;
    if (now && Object.keys(now).length) {
      box.append(h('div', {className: 'hint', textContent: 'Right now: ' + Object.entries(now).map(([a, b]) => a + ': ' + (typeof b === 'object' ? JSON.stringify(b) : b)).join(' · ')}));
    }
    return box;
  }

  const baseHaLinks = haLinks;
  haLinks = function (g, k, p) {
    const box = baseHaLinks(g, k, p);
    box.append(moreEntities(g, k, p));
    return box;
  };

  /* ---------- the house ---------- */
  let HOUSE = null, houseOpen = false;
  const section = document.createElement('section');
  section.id = 'house-panel';
  const anchor = document.getElementById('shuffle-panel');
  if (anchor) anchor.after(section); else document.body.prepend(section);

  async function loadHouse() {
    try { HOUSE = await (await fetch('api/house')).json(); } catch (e) { HOUSE = null; }
    housePanel();
  }
  function housePanel() {
    if (!HOUSE) { section.replaceChildren(); return; }
    const msg = h('div', {className: 'meta'});
    const items = HOUSE.items;
    section.replaceChildren(h('details', {open: houseOpen, ontoggle: e => { houseOpen = e.target.open; }},
      h('summary', {}, '🏠 House entities', h('span', {className: 'now', textContent: '  ' + items.length + ' linked'})),
      h('div', {},
        h('p', {className: 'note', textContent: 'Link things about the house itself (weather, alarm, house mode, garage door, a lock, energy use). Their current values go in the info sensor as house and house_text, so the AI and your announcements know what is going on at home.'}),
        rows(items, {
          sayText: 'Include it in the house text',
          onChange: () => {},
          onRemove: housePanel
        }),
        h('div', {className: 'add'},
          h('button', {textContent: '+ Add entity', onclick: () => { items.push({entity_id: '', say: true}); housePanel(); }}),
          h('button', {className: 'pri', textContent: 'Save house entities', onclick: async () => {
            msg.textContent = 'Saving...';
            try {
              HOUSE = await (await fetch('api/house', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({items})})).json();
              houseOpen = true; housePanel(); status('House entities saved', 'ok');
            } catch (e) { msg.textContent = 'Saving failed. Check the app log.'; }
          }})),
        msg,
        HOUSE.text ? h('div', {className: 'xtext', textContent: HOUSE.text}) : null)));
  }
  loadHouse();
})();
