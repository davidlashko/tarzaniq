/* TarzanIQ pages.js — Overview, Apes, Compare, Places, Patterns, Day, Settings */
'use strict';

const AXES = [
  ['hunting', 'HUNTING', 'cold marks per shooting hour'],
  ['closing', 'CLOSING', 'cold → warm conversion'],
  ['holding', 'HOLDING', 'average warm shoot length'],
  ['hustle', 'HUSTLE', 'shooting time vs time on street'],
  ['volume', 'VOLUME', 'photos per shooting hour'],
];
const COACH_TIPS = {
  hunting: 'finding new marks is the slow part. Keep moving — claim a busier corner, rotate spots every 30–45 minutes.',
  closing: 'plenty of marks, fewer yeses. Pitch sooner and warmer — the first ten seconds after the candid decide it.',
  holding: 'warm shoots end too fast. Keep three go-to poses ready and chain them — longer shoots sell bigger packs.',
  hustle: 'a lot of street time isn\u2019t shooting time. Trim the drifting between marks; real breaks are fine.',
  volume: 'the shutter is quiet. Shoot more frames per mark — more keepers, more to pitch with.',
};
const COACH_PRAISE = {
  hunting: 'a natural hunter — finds marks faster than anyone',
  closing: 'a closer — turns candids into customers',
  holding: 'keeps people posing — warm shoots run long and happy',
  hustle: 'pure hustle — almost no dead time on the street',
  volume: 'a shutter machine — huge frame counts',
};

/* ================================================== OVERVIEW */
async function pageOverview() {
  let d;
  try { d = await API.get('/api/overview'); }
  catch (e) { return setMain(errPanel(e)); }

  if (!d.total.days) {
    return setMain(el('div', { class: 'panel' },
      el('div', { class: 'empty' },
        el('img', { src: '/static/img/logo.png' }),
        el('h2', null, 'The jungle is quiet'),
        el('p', null, 'No days analyzed yet. Process your first folder to wake it up.'),
        el('div', { class: 'btnrow mt', style: 'justify-content:center' },
          el('button', { class: 'btn big', onclick: addDayFlow }, '+ Add day folder')))));
  }

  /* comparability banner — fetch in parallel, non-blocking */
  let cmpBanner = '';
  try {
    const cmp = await API.get('/api/comparability');
    const parts = [];
    if (cmp.stale > 0) {
      const br = cmp.by_route || {};
      const detail = [br.reprocess > 0 ? `${br.reprocess} reprocessing` : '',
                      br.recompute > 0 ? `${br.recompute} recomputing`  : '']
        .filter(Boolean).join(', ');
      parts.push(el('span', null,
        el('span', { class: 'cmp-icon' }, '⏳ '),
        `${cmp.stale} day${cmp.stale > 1 ? 's' : ''} catching up…`,
        detail ? el('span', { class: 'cmp-note' }, ` (${detail})`) : ''));
    }
    if ((cmp.by_route || {}).legacy > 0) {
      parts.push(el('span', { class: 'cmp-note' },
        `${cmp.by_route.legacy} legacy day${cmp.by_route.legacy > 1 ? 's' : ''} excluded from comparisons`));
    }
    if (parts.length) {
      cmpBanner = el('div', { class: 'cmp-banner' }, ...parts);
    }
  } catch (_) { /* banner is non-critical — ignore */ }

  const t = d.total;
  const totems = el('div', { class: 'totems' },
    totem(pixImg('target', 26), fmt.pct(t.conversion), 'Team conversion', 'good'),
    totem(pixImg('foot', 26), fmt.int(t.cold_persons), 'Cold marks', 'cold'),
    totem(pixImg('fire', 26), fmt.int(t.warm_persons), 'Warm shoots', 'warm'),
    totem(pixImg('camera', 26), fmt.int(t.photos), 'Photos'),
    totem(pixImg('clock', 26), fmt.num(t.shoot_h, 0) + 'h', 'Shooting time'),
    totem(pixImg('leaf', 26), fmt.int(t.days), 'Days logged'));

  const lb = el('table', null,
    el('tr', null, el('th', null, '#'), el('th', null, 'Ape'),
      el('th', { class: 'r' }, 'Days'), el('th', { class: 'r' }, 'Conversion'),
      el('th', { class: 'r' }, 'Warm/hr'), el('th', { class: 'r' }, 'Cold/hr'),
      el('th', { class: 'r' }, 'Photos')),
    d.leaderboard.map((s, i) => el('tr', {
      class: 'click' + (i === 0 ? ' rank1' : ''),
      onclick: () => location.hash = '#/ape/' + encodeURIComponent(s.employee) },
      el('td', { class: 'c' }, i === 0 ? pixImg('crown', 16) : String(i + 1)),
      el('td', null, s.employee),
      el('td', { class: 'r' }, fmt.int(s.days)),
      el('td', { class: 'r gold' }, fmt.pct(s.conversion)),
      el('td', { class: 'r' }, fmt.num(s.warm_per_hr)),
      el('td', { class: 'r' }, fmt.num(s.cold_per_hr)),
      el('td', { class: 'r' }, fmt.int(s.photos)))));

  const recent = el('div', { class: 'grid', style: 'grid-template-columns:repeat(auto-fill,minmax(240px,1fr))' },
    d.recent.map(r => el('div', { class: 'chip', onclick: () => location.hash = '#/day/' + r.id },
      el('span', null, `${r.date}`),
      el('span', { class: 'dim' }, r.place),
      el('span', null, r.employee),
      el('b', null, fmt.pct(r.conversion)))));

  const records = el('div', { class: 'grid', style: 'grid-template-columns:repeat(auto-fit,minmax(190px,1fr))' },
    (d.records || []).map(r => el('div', { class: 'totem' },
      el('div', { class: 'num small' }, r.value),
      el('div', { class: 'lab' }, r.label),
      el('div', { class: 'small dim mt' }, `${r.who} · ${r.date}`))));

  setMain(
    cmpBanner,
    el('div', { class: 'panel' },
      el('div', { class: 'spread' },
        el('h2', null, 'The whole jungle'),
        el('button', { class: 'btn', onclick: addDayFlow }, '+ Add day folder')),
      totems),
    el('div', { class: 'panel' }, el('h2', null, 'Leaderboard — ranked by conversion'), lb,
      el('p', { class: 'small dim mt' }, 'Conversion (cold marks turned into warm shoots) is the honest score — money totals can\u2019t be tied to shoots or trusted per pocket.')),
    el('div', { class: 'panel' }, el('h2', null, 'Recent expeditions'), recent),
    (d.records || []).length ? el('div', { class: 'panel bark' }, el('h2', null, 'Jungle records'), records) : '');
}

function totem(icon, num, lab, cls) {
  return el('div', { class: 'totem ' + (cls || '') },
    el('div', { class: 'ico' }, icon),
    el('div', { class: 'num' }, num),
    el('div', { class: 'lab' }, lab));
}
function errPanel(e) {
  return el('div', { class: 'panel' }, el('h2', null, 'Hmm'),
    el('p', null, 'Could not load data: ' + e.message));
}

/* ================================================== APES LIST */
async function pageApes() {
  let d;
  try { d = await API.get('/api/overview'); }
  catch (e) { return setMain(errPanel(e)); }
  const apes = d.leaderboard;
  if (!apes.length) {
    return setMain(el('div', { class: 'panel' },
      el('div', { class: 'empty' }, el('img', { src: '/static/img/logo.png' }),
        el('p', null, 'No apes in the troop yet — process a day first.'))));
  }
  let pickA = null;
  const cards = el('div', { class: 'grid', style: 'grid-template-columns:repeat(auto-fill,minmax(250px,1fr))' },
    apes.map((s, i) => {
      const card = el('div', { class: 'panel', style: 'margin:0;cursor:pointer' },
        el('div', { class: 'spread' },
          el('h2', { style: 'margin:0' }, s.employee), i === 0 ? pixImg('crown', 18) : ''),
        el('div', { class: 'totems mt', style: 'grid-template-columns:1fr 1fr' },
          totem('', fmt.pct(s.conversion), 'Conversion', 'good'),
          totem('', fmt.num(s.warm_per_hr), 'Warm/hr', 'warm')),
        el('p', { class: 'small dim mt' },
          `${s.days} day${s.days > 1 ? 's' : ''} · ${fmt.int(s.photos)} photos · last out ${s.last_date}`),
        el('div', { class: 'btnrow mt' },
          el('button', { class: 'btn green', onclick: ev => { ev.stopPropagation();
            location.hash = '#/ape/' + encodeURIComponent(s.employee); } }, 'Profile'),
          el('button', { class: 'btn bark', onclick: ev => {
            ev.stopPropagation();
            if (!pickA) { pickA = s.employee; toast(`${s.employee} steps into the ring — pick the opponent`); }
            else if (pickA !== s.employee) {
              location.hash = `#/compare/${encodeURIComponent(pickA)}/${encodeURIComponent(s.employee)}`;
            }
          } }, 'Compare')));
      card.addEventListener('click', () => location.hash = '#/ape/' + encodeURIComponent(s.employee));
      return card;
    }));
  setMain(el('div', { class: 'panel', style: 'background:transparent;border:none;box-shadow:none;padding:0' },
    el('h2', null, 'The troop'), cards));
}

/* ================================================== APE PROFILE */
async function pageApe(name) {
  let d;
  try { d = await API.get('/api/employee/' + encodeURIComponent(name)); }
  catch (e) { return setMain(errPanel(e)); }
  const s = d.summary, pct = d.percentiles || {};

  const totems = el('div', { class: 'totems' },
    totem(pixImg('target', 24), fmt.pct(s.conversion), 'Conversion', 'good'),
    totem(pixImg('fire', 24), fmt.num(s.warm_per_hr), 'Warm/hr', 'warm'),
    totem(pixImg('foot', 24), fmt.num(s.cold_per_hr), 'Cold/hr', 'cold'),
    totem(pixImg('clock', 24), fmt.dur(s.warm_dur_avg_s), 'Avg warm shoot'),
    totem(pixImg('camera', 24), fmt.int(s.photos), 'Photos'),
    s.money !== null ? totem(pixImg('money', 24), fmt.money(s.money),
      `Money (${s.money_days}d)`) : totem(pixImg('leaf', 24), fmt.int(s.days), 'Days'));

  /* radar */
  const { box: rbox, cv: rcv } = chartBox(true);
  /* coach note */
  const axesWithPct = AXES.map(([k, lab]) => [k, lab, pct[k]]).filter(a => a[2] !== null && a[2] !== undefined);
  let coach = '';
  if (axesWithPct.length >= 2) {
    const sorted = axesWithPct.slice().sort((a, b) => a[2] - b[2]);
    const worst = sorted[0], best = sorted[sorted.length - 1];
    coach = el('div', { class: 'coach mt' },
      el('img', { src: '/static/img/logo.png' }),
      el('div', { class: 'speech' },
        el('b', null, `Coach\u2019s note: `),
        `${name} is ${COACH_PRAISE[best[0]]}. `,
        best[0] !== worst[0] && worst[2] < 0.45
          ? `Weakest vine is ${worst[1]} — ${COACH_TIPS[worst[0]]}` : 'Keep swinging.'));
  }

  /* trend */
  const { box: tbox, cv: tcv } = chartBox();
  /* dow + hours */
  const { box: dowbox, cv: dowcv } = chartBox();
  const { box: hrbox, cv: hrcv } = chartBox();
  /* demographics */
  const { box: gbox, cv: gcv } = chartBox();
  const { box: abox, cv: acv } = chartBox();

  const bests = el('div', { class: 'grid', style: 'grid-template-columns:repeat(auto-fit,minmax(170px,1fr))' },
    (d.bests || []).map(b => el('div', { class: 'totem' },
      el('div', { class: 'num small' }, b.value),
      el('div', { class: 'lab' }, b.label),
      el('div', { class: 'small dim mt' }, b.date))));

  const daysTable = el('table', null,
    el('tr', null, el('th', null, 'Date'), el('th', null, 'Place'),
      el('th', { class: 'r' }, 'Cold'), el('th', { class: 'r' }, 'Warm'),
      el('th', { class: 'r' }, 'Conv'), el('th', { class: 'r' }, 'Photos'),
      el('th', { class: 'r' }, 'Money')),
    d.series.slice().reverse().map((r, i, arr) => {
      const prev = arr[i + 1];
      return el('tr', { class: 'click', onclick: () => location.hash = '#/day/' + r.id },
        el('td', null, r.date), el('td', null, r.place),
        el('td', { class: 'r' }, fmt.int(r.cold)),
        el('td', { class: 'r' }, fmt.int(r.warm)),
        el('td', { class: 'r gold' }, fmt.pct(r.conversion),
          prev ? trendArrow(r.conversion, prev.conversion) : ''),
        el('td', { class: 'r' }, fmt.int(r.photos)),
        el('td', { class: 'r' }, fmt.money(r.money)));
    }));

  setMain(
    el('div', { class: 'panel' },
      el('div', { class: 'spread' },
        el('h2', null, name),
        el('span', { class: 'dim' }, `${s.days} days · last out ${s.last_date}`)),
      totems, coach),
    el('div', { class: 'row' },
      el('div', { class: 'panel' }, el('h2', null, 'Ape skills'), rbox,
        el('p', { class: 'small dim mt' }, 'Each axis is this ape\u2019s percentile inside the troop. The dotted ring is the troop middle.')),
      el('div', { class: 'panel' }, el('h2', null, 'Form over time'), tbox)),
    el('div', { class: 'row' },
      el('div', { class: 'panel' }, el('h2', null, 'By weekday'), dowbox),
      el('div', { class: 'panel' }, el('h2', null, 'By hour of day'), hrbox)),
    el('div', { class: 'row' },
      el('div', { class: 'panel' }, el('h2', null, 'Who gets approached'), gbox),
      el('div', { class: 'panel' }, el('h2', null, 'Ages · approach vs convert'), abox)),
    (d.bests || []).length ? el('div', { class: 'panel bark' }, el('h2', null, 'Personal bests'), bests) : '',
    el('div', { class: 'panel' }, el('h2', null, 'All days'), daysTable));

  /* charts after mount */
  radarChart(rcv, AXES.map(a => a[1]), [
    radarDs(name, AXES.map(a => pct[a[0]] ?? 0), C.banana, '44'),
    Object.assign(radarDs('troop middle', AXES.map(() => 0.5), C.cold, '00'),
      { borderDash: [6, 6], pointRadius: 0 }),
  ]);
  lineChart(tcv, d.series.map(r => r.date), [
    Object.assign(ds('Conversion', d.series.map(r => r.conversion), C.banana), { yAxisID: 'y' }),
    Object.assign(ds('Warm/hr', d.series.map(r => r.warm_per_hr), C.warm), { yAxisID: 'y2' }),
  ], { pct: true, y2: true });
  barChart(dowcv, d.dow.filter(r => r.days).map(r => r.weekday.slice(0, 3)), [
    { label: 'Warm/hr', data: d.dow.filter(r => r.days).map(r => r.warm_per_hr),
      backgroundColor: C.warm, borderColor: C.ink, borderWidth: 2 },
    { label: 'Cold/hr', data: d.dow.filter(r => r.days).map(r => r.cold_per_hr),
      backgroundColor: C.cold, borderColor: C.ink, borderWidth: 2 },
  ], { legend: true });
  lineChart(hrcv, d.hours.map(h => String(h.hour).padStart(2, '0') + ':00'), [
    ds('Warm/hr', d.hours.map(h => h.warm_per_hr), C.warm),
    ds('Cold/hr', d.hours.map(h => h.cold_per_hr), C.cold),
  ]);
  demoCharts(gcv, acv, d.demographics.demo);
}

function demoCharts(gcv, acv, demo) {
  const g = demo.gender || {}, gw = demo.gender_warm || {};
  const glabels = Object.keys(g).sort();
  if (glabels.length) {
    donutChart(gcv, glabels.map(k => ({ M: 'Men', F: 'Women', unknown: 'Unknown' }[k] || k)),
      glabels.map(k => g[k]),
      glabels.map(k => ({ M: C.cold, F: C.warm, unknown: C.bark }[k] || C.leaf)));
  }
  const a = demo.age || {}, aw = demo.age_warm || {};
  const alabels = Object.keys(a).sort((x, y) => parseInt(x) - parseInt(y));
  if (alabels.length) {
    barChart(acv, alabels, [
      { label: 'Approached', data: alabels.map(k => a[k]),
        backgroundColor: C.cold, borderColor: C.ink, borderWidth: 2 },
      { label: 'Converted', data: alabels.map(k => aw[k] || 0),
        backgroundColor: C.warm, borderColor: C.ink, borderWidth: 2 },
    ], { legend: true });
  }
}

/* ================================================== COMPARE */
function sigLine(sig, a, b) {
  if (!sig || !sig.test) return '';
  const pct = v => (v == null ? '—' : Math.round(v * 100) + '%');
  const ci = c => c ? ` (${Math.round(c[0]*100)}–${Math.round(c[1]*100)}%)` : '';
  const t = sig.test;
  const leader = t.diff >= 0 ? a : b;
  let verdict, cls;
  if (!t.enough_data) { verdict = 'Not enough data yet to call it (need ≥30 approaches each)'; cls = 'air'; }
  else if (t.significant) { verdict = `${leader} is ahead — statistically significant (p = ${t.p_value.toFixed(2)})`; cls = 'warm'; }
  else { verdict = `Not statistically significant (p = ${t.p_value.toFixed(2)})`; cls = 'air'; }
  return el('div', { class: 'sig' },
    el('div', { class: 'sigrates' },
      `${a} ${pct(sig.a_conv)}${ci(sig.a_ci)}  ·  ${b} ${pct(sig.b_conv)}${ci(sig.b_ci)}`),
    el('span', { class: 'badge badge-' + cls }, verdict));
}

async function pageCompare(a, b) {
  let A, B, sig;
  try {
    [A, B] = await Promise.all([
      API.get('/api/employee/' + encodeURIComponent(a)),
      API.get('/api/employee/' + encodeURIComponent(b))]);
  } catch (e) { return setMain(errPanel(e)); }
  sig = await API.get('/api/compare/' + encodeURIComponent(a) + '/' + encodeURIComponent(b)).catch(() => null);

  const { box: rbox, cv: rcv } = chartBox(true);
  const { box: mbox, cv: mcv } = chartBox(true);

  const head = el('div', { class: 'panel' },
    el('div', { class: 'spread' },
      el('h2', { style: 'margin:0' }, a),
      pixImg('vs', 28),
      el('h2', { style: 'margin:0;color:var(--warm)' }, b)));

  setMain(head,
    el('div', { class: 'row' },
      el('div', { class: 'panel' }, el('h2', null, 'Skills face-off'), rbox),
      el('div', { class: 'panel' }, el('h2', null, 'Head to head'), mbox,
        el('div', { class: 'legend' },
          el('span', null, el('span', { class: 'key', style: 'background:' + C.banana }), a),
          el('span', null, el('span', { class: 'key', style: 'background:' + C.warm }), b)),
        sigLine(sig, a, b))));

  radarChart(rcv, AXES.map(x => x[1]), [
    radarDs(a, AXES.map(x => (A.percentiles || {})[x[0]] ?? 0), C.banana, '38'),
    radarDs(b, AXES.map(x => (B.percentiles || {})[x[0]] ?? 0), C.warm, '38'),
  ]);

  const rows = [
    ['Conversion', s => s.conversion, v => fmt.pct(v), true],
    ['Warm/hr', s => s.warm_per_hr, v => fmt.num(v)],
    ['Cold/hr', s => s.cold_per_hr, v => fmt.num(v)],
    ['Photos/hr', s => s.photos_per_hr, v => fmt.num(v, 0)],
    ['Avg warm shoot (s)', s => s.warm_dur_avg_s, v => fmt.dur(v)],
    ['Hustle', s => s.hustle, v => fmt.pct(v), true],
  ];
  // normalize each metric to max of pair for mirrored look
  const av = rows.map(r => r[1](A.summary) ?? 0);
  const bv = rows.map(r => r[1](B.summary) ?? 0);
  const norm = rows.map((r, i) => Math.max(av[i], bv[i]) || 1);
  mkChart(mcv.getContext ? mcv : mcv, {
    type: 'bar',
    data: {
      labels: rows.map(r => r[0]),
      datasets: [
        { label: a, data: av.map((v, i) => -(v / norm[i])),
          backgroundColor: C.banana, borderColor: C.ink, borderWidth: 2 },
        { label: b, data: bv.map((v, i) => v / norm[i]),
          backgroundColor: C.warm, borderColor: C.ink, borderWidth: 2 },
      ],
    },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      scales: { x: { min: -1.05, max: 1.05, ticks: { display: false },
        grid: { color: 'rgba(237,230,208,.1)' } } },
      plugins: { legend: { display: false }, tooltip: { callbacks: {
        label: ctx => {
          const i = ctx.dataIndex;
          const raw = ctx.datasetIndex === 0 ? av[i] : bv[i];
          return `${ctx.dataset.label}: ${rows[i][2](raw)}`;
        } } } },
    },
  });
}

/* ================================================== PLACES */
async function pagePlaces() {
  let d;
  try { d = await API.get('/api/places'); }
  catch (e) { return setMain(errPanel(e)); }
  if (!d.places.length) {
    return setMain(el('div', { class: 'panel' },
      el('div', { class: 'empty' }, el('img', { src: '/static/img/logo.png' }),
        el('p', null, 'No hunting grounds mapped yet.'))));
  }
  const cards = d.places.map((p, i) => el('div', { class: 'panel', style: 'margin:0' },
    el('div', { class: 'spread' },
      el('h2', { style: 'margin:0' }, (i === 0 ? '🏆 ' : '') + p.place),
      el('span', { class: 'dim small' }, `${p.days} days · ${p.employees} ape${p.employees > 1 ? 's' : ''}`)),
    el('div', { class: 'totems mt', style: 'grid-template-columns:repeat(3,1fr)' },
      totem('', fmt.pct(p.conversion), 'Conversion', 'good'),
      totem('', fmt.num(p.warm_per_hr), 'Warm/hr', 'warm'),
      totem('', p.best_hour && p.best_hour.hour !== null
        ? String(p.best_hour.hour).padStart(2, '0') + ':00' : '–', 'Hottest hour'))));

  const emps = Object.keys(d.matrix).sort();
  const placesList = d.places.map(p => p.place);
  const mtable = el('table', null,
    el('tr', null, el('th', null, 'Ape \\ Ground'),
      placesList.map(pl => el('th', { class: 'c' }, pl))),
    emps.map(emp => el('tr', null,
      el('td', null, emp),
      placesList.map(pl => {
        const v = d.matrix[emp][pl];
        const td = el('td', { class: 'c' }, v === null || v === undefined ? '–' : fmt.pct(v));
        if (v !== null && v !== undefined) {
          td.style.background = heatColor(v, Math.max(...emps.flatMap(e2 =>
            placesList.map(p2 => d.matrix[e2][p2] || 0))));
          td.style.color = '#0E1311';
        }
        return td;
      }))));

  setMain(
    el('div', { class: 'panel', style: 'background:transparent;border:none;box-shadow:none;padding:0' },
      el('h2', null, 'Hunting grounds — ranked by conversion'),
      el('div', { class: 'grid', style: 'grid-template-columns:repeat(auto-fill,minmax(290px,1fr))' }, cards),
      el('p', { class: 'small dim mt' }, 'Ranked by conversion, not by cash — cash numbers lie between pockets, bananas don\u2019t.')),
    el('div', { class: 'panel' }, el('h2', null, 'Who hunts best where'), mtable));
}

/* ================================================== PATTERNS */
async function pagePatterns() {
  let reg;
  try { reg = await API.get('/api/registry'); }
  catch (e) { return setMain(errPanel(e)); }
  const selEmp = el('select', null, el('option', { value: '' }, 'All apes'),
    reg.names.map(n => el('option', { value: n }, n)));
  const selPl = el('select', null, el('option', { value: '' }, 'All grounds'),
    reg.places.map(n => el('option', { value: n }, n)));
  const content = el('div');
  async function load() {
    killCharts();
    content.innerHTML = '';
    let d;
    const q = new URLSearchParams();
    if (selEmp.value) q.set('employee', selEmp.value);
    if (selPl.value) q.set('place', selPl.value);
    try { d = await API.get('/api/patterns?' + q.toString()); }
    catch (e) { content.append(errPanel(e)); return; }
    if (!d.n_days) {
      content.append(el('div', { class: 'panel' },
        el('div', { class: 'empty' }, el('p', null, 'No data for this filter.'))));
      return;
    }
    /* heatmap weekday x hour */
    const hmap = {};
    (d.heat || []).forEach(h => { hmap[h.weekday + '|' + h.hour] = h; });
    const hoursWith = [...new Set((d.heat || []).map(h => h.hour))].sort((a, b) => a - b);
    const WD = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    const wdWith = WD.filter(w => (d.heat || []).some(h => h.weekday === w));
    const heatEl = hoursWith.length ? heatmap(wdWith, hoursWith,
      (w, h) => { const c = hmap[w + '|' + h];
        return c && c.shoot_h > 0.15 ? c.warm_per_hr : null; },
      v => fmt.num(v)) : el('p', { class: 'dim' }, 'Not enough hourly data yet.');

    const { box: hrbox, cv: hrcv } = chartBox();
    const { box: dowbox, cv: dowcv } = chartBox();
    const { box: gbox, cv: gcv } = chartBox();
    const { box: abox, cv: acv } = chartBox();
    const { box: cbox, cv: ccv } = chartBox();

    content.append(
      el('div', { class: 'panel' },
        el('h2', null, 'Warm shoots per hour — when the jungle bites'),
        heatEl,
        el('p', { class: 'small dim mt' }, 'Greener → banana = better. Cells need at least ~10 min of shooting data to show.')),
      el('div', { class: 'row' },
        el('div', { class: 'panel' }, el('h2', null, 'Hour of day'), hrbox),
        el('div', { class: 'panel' }, el('h2', null, 'Weekday'), dowbox)),
      el('div', { class: 'row' },
        el('div', { class: 'panel' }, el('h2', null, 'Who gets approached'), gbox),
        el('div', { class: 'panel' }, el('h2', null, 'Ages · approach vs convert'), abox)),
      el('div', { class: 'panel' }, el('h2', null, 'Conversion by demographic'), cbox,
        el('p', { class: 'small dim mt' }, 'Small samples wobble — trust this once a group has 20+ approaches.')));

    lineChart(hrcv, d.hours.map(h => String(h.hour).padStart(2, '0') + ':00'), [
      ds('Warm/hr', d.hours.map(h => h.warm_per_hr), C.warm),
      ds('Cold/hr', d.hours.map(h => h.cold_per_hr), C.cold),
    ]);
    const dows = d.dow.filter(r => r.days);
    barChart(dowcv, dows.map(r => r.weekday.slice(0, 3)), [
      { label: 'Warm/hr', data: dows.map(r => r.warm_per_hr),
        backgroundColor: C.warm, borderColor: C.ink, borderWidth: 2 },
      { label: 'Conversion', data: dows.map(r => r.conversion),
        backgroundColor: C.banana, borderColor: C.ink, borderWidth: 2, hidden: true },
    ], { legend: true });
    demoCharts(gcv, acv, d.demographics);

    const dm = d.demographics;
    const convRows = [];
    Object.keys(dm.gender || {}).forEach(k => {
      const n = dm.gender[k];
      if (n >= 1) convRows.push([({ M: 'Men', F: 'Women', unknown: '?' }[k] || k),
        (dm.gender_warm[k] || 0) / n, n]);
    });
    Object.keys(dm.age || {}).sort((x, y) => parseInt(x) - parseInt(y)).forEach(k => {
      const n = dm.age[k];
      if (n >= 1) convRows.push([k, (dm.age_warm[k] || 0) / n, n]);
    });
    if (convRows.length) {
      barChart(ccv, convRows.map(r => `${r[0]} (${r[2]})`),
        [{ label: 'Conversion', data: convRows.map(r => r[1]),
          backgroundColor: convRows.map(r => heatColor(r[1], Math.max(...convRows.map(x => x[1])) || 1)),
          borderColor: C.ink, borderWidth: 2 }], { pct: true });
    }
  }
  selEmp.addEventListener('change', load);
  selPl.addEventListener('change', load);
  setMain(
    el('div', { class: 'panel' },
      el('div', { class: 'spread' }, el('h2', null, 'Patterns'),
        el('div', { class: 'btnrow' }, selEmp, selPl))),
    content);
  load();
}

/* ================================================== DAY DETAIL */
async function pageDay(id) {
  let d, cmp;
  try {
    [d, cmp] = await Promise.all([
      API.get('/api/day/' + id),
      API.get('/api/comparability').catch(() => null),
    ]);
  }
  catch (e) { return setMain(errPanel(e)); }
  const st = d.stats, day = d.day;

  /* comparability pills */
  const dayFp = day.processing_fingerprint;
  const curFp = cmp && cmp.current_fingerprint;
  const isBehind = dayFp && curFp && dayFp !== curFp;
  const isLegacy = isBehind && !day.has_archive;
  const dayPills = [];
  if (isLegacy) {
    dayPills.push(el('span', { class: 'badge badge-legacy', title: 'No archive — cannot be reprocessed; excluded from comparisons' }, 'legacy'));
  } else if (isBehind) {
    dayPills.push(el('span', { class: 'badge badge-catchup', title: 'Queued to catch up to the current processing fingerprint' }, 'catching up'));
  }

  const totems = el('div', { class: 'totems' },
    totem('', fmt.pct(st.conversion), 'Conversion', 'good'),
    totem('', fmt.int(st.cold_persons), 'Cold marks', 'cold'),
    totem('', fmt.int(st.warm_persons), 'Warm shoots', 'warm'),
    totem('', fmt.dur(st.shoot_s), 'Shooting'),
    totem('', fmt.dur(st.warm_dur_avg_s), 'Avg warm shoot'),
    totem('', fmt.int(st.photos_total), 'Photos'));

  /* timeline */
  const tl = el('div', { class: 'timeline' });
  const t0 = st.first_shot ? new Date(st.first_shot).getTime() : 0;
  const t1 = st.last_shot ? new Date(st.last_shot).getTime() : 1;
  const span = Math.max(t1 - t0, 1);
  const pos = iso => ((new Date(iso).getTime() - t0) / span) * 100;
  (st.breaks || []).forEach(b => {
    tl.append(blockEl('brk', pos(b.start), pos(b.end),
      `Break — ${fmt.dur(b.duration_s)}`));
  });
  (d.blocks || []).forEach(b => {
    if (b.kind === 'cold') {
      tl.append(blockEl('cold', pos(b.start), pos(b.end),
        `Cold shoot — ${b.n_members} mark${b.n_members > 1 ? 's' : ''}, ${b.photos} photos` +
        (b.n_converted ? `, ${b.n_converted} converted` : '')));
    } else {
      tl.append(blockEl('warm', pos(b.start), pos(b.end),
        `Warm shoot S${(Array.isArray(b.members) ? b.members[0] : b.members) + 1} — ${b.photos} photos, ~${b.poses} poses`));
    }
  });
  tl.append(el('div', { class: 'tlaxis' },
    el('span', null, st.first_shot ? st.first_shot.slice(11, 16) : ''),
    el('span', null, st.last_shot ? st.last_shot.slice(11, 16) : '')));

  /* facts */
  const facts = el('div', { class: 'grid', style: 'grid-template-columns:repeat(auto-fit,minmax(220px,1fr));font-size:18px' },
    fact('Hours on street', fmt.dur(st.span_s)),
    fact('Breaks', `${st.breaks_n} (${fmt.dur(st.break_s)})`),
    fact('Avg hunt between marks', fmt.dur(st.hunting_avg_s)),
    fact('Longest dry spell', fmt.dur(st.dry_spell_s)),
    fact('Avg pitch time', fmt.dur(st.pitch_avg_s)),
    fact('Hot streak', st.hot_streak + ' in a row'),
    fact('Group approaches', fmt.pct(st.pct_group_approaches)),
    fact('Solo / group conversion', `${fmt.pct(st.solo_conv)} / ${fmt.pct(st.group_conv)}`),
    fact('Re-approaches', fmt.int(st.reapproaches)),
    fact('Air shots', fmt.int(st.photos_air)),
    fact('Suspected deletions', fmt.int(st.suspected_deletions)),
    fact('Missing camera time', fmt.int(st.missing_exif) + ' photos'));

  /* money editor */
  const cash = el('input', { type: 'text', value: day.money_cash ?? '', placeholder: 'cash' });
  const card = el('input', { type: 'text', value: day.money_card ?? '', placeholder: 'card' });
  const moneyRow = el('div', { class: 'btnrow' },
    el('label', { class: 'dim' }, 'Money:'), cash, card,
    el('button', { class: 'btn green', onclick: async () => {
      await API.post(`/api/day/${id}/money`, { cash: cash.value, card: card.value });
      toast('Money updated'); Sfx.blip();
    } }, 'Save'));

  /* subjects table */
  const subT = el('table', null,
    el('tr', null, el('th', null, 'Mark'), el('th', null, 'Gender'),
      el('th', null, 'Age'), el('th', { class: 'r' }, 'Photos'),
      el('th', { class: 'c' }, 'Warm?'), el('th', { class: 'r' }, 'Pitch'),
      el('th', { class: 'r' }, 'Warm time'), el('th', { class: 'r' }, 'Poses')),
    d.subjects.map(s2 => el('tr', null,
      el('td', null, 'S' + (s2.local_id + 1)),
      el('td', null, s2.gender || '–'),
      el('td', null, s2.age_bucket || '–'),
      el('td', { class: 'r' }, fmt.int(s2.photo_count)),
      el('td', { class: 'c' }, s2.did_warm ? el('span', { class: 'badge warm' }, 'yes') : el('span', { class: 'dim' }, '–')),
      el('td', { class: 'r' }, fmt.dur(s2.pitch_s)),
      el('td', { class: 'r' }, s2.did_warm ? fmt.dur(s2.warm_duration_s) : '–'),
      el('td', { class: 'r' }, s2.did_warm ? fmt.int(s2.poses_est) : '–'))));

  const actions = el('div', { class: 'btnrow' },
    el('a', { class: 'btn', href: `/api/export/${id}` }, '⬇ Excel'),
    el('button', { class: 'btn bark', onclick: async () => {
      toast('Recomputing with current settings…');
      const r = await API.post('/api/recompute', { day_id: id });
      toast(`Recomputed ${r.recomputed} day`); pageDay(id);
    } }, 'Recompute'),
    el('button', { class: 'btn bark', onclick: async () => {
      // reprocess this day from the permanent photo archive (Feature A)
      toast('Reprocessing from archive…');
      await API.post('/api/reprocess', { day_id: id });
    } }, 'Reprocess from archive'),
    el('button', { class: 'btn red', onclick: async () => {
      if (!confirm(`Delete ${day.date} · ${day.place} · ${day.employee} from the dataset? The Excel file stays on disk.`)) return;
      await API.del('/api/day/' + id);
      toast('Day deleted'); location.hash = '#/';
    } }, 'Delete day'));

  setMain(
    el('div', { class: 'panel' },
      el('div', { class: 'spread' },
        el('h2', null, `${day.date} · ${day.place} · `,
          el('a', { href: '#/ape/' + encodeURIComponent(day.employee) }, day.employee)),
        el('div', { class: 'btnrow' }, ...dayPills,
          el('span', { class: 'dim small' }, day.weekday))),
      totems),
    el('div', { class: 'panel' }, el('h2', null, 'The day, on one vine'), tl,
      el('div', { class: 'legend mt' },
        el('span', null, el('span', { class: 'key', style: 'background:' + C.cold }), 'cold shoot'),
        el('span', null, el('span', { class: 'key', style: 'background:' + C.warm }), 'warm shoot'),
        el('span', null, el('span', { class: 'key', style: 'background:' + C.bark }), 'break'))),
    el('div', { class: 'panel' }, el('h2', null, 'Field notes'), facts,
      el('hr', { class: 'vinehr' }), moneyRow),
    el('div', { class: 'panel' }, el('h2', null, `Marks of the day (${d.subjects.length})`), subT),
    el('div', { class: 'panel' }, el('h2', null, 'Actions'), actions,
      el('p', { class: 'small dim mt' },
        `Folder: ${day.source_folder || '–'} · analyzed ${day.committed_at ? day.committed_at.slice(0, 16).replace('T', ' ') : ''} · v${day.app_version || '?'}`)));
}

function blockEl(cls, a, b, title) {
  const e = el('div', { class: 'tlblock ' + cls, title });
  e.style.left = Math.max(0, a) + '%';
  e.style.width = Math.max(b - a, 0.5) + '%';
  return e;
}
function fact(lab, val) {
  return el('div', null, el('span', { class: 'dim' }, lab + ': '), el('b', null, val));
}

/* ================================================== SETTINGS */
const SETTING_DEFS = [
  ['warm_gap_s', 'Warm gap (seconds)', 'Quiet time after a candid before the same person coming back counts as a warm shoot.'],
  ['max_pitch_minutes', 'Max pitch (minutes)', 'If they come back later than this, it\u2019s a re-approach (new cold shoot), not a warm one.'],
  ['break_minutes', 'Break (minutes)', 'A gap between photos this long counts as a break, not shooting time.'],
  ['warm_session_gap_minutes', 'Warm session gap (minutes)', 'Pause inside a warm shoot longer than this splits it into two sessions.'],
  ['pose_gap_s', 'Pose gap (seconds)', 'Pause between warm frames that signals a new pose.'],
  ['min_face_frac', 'Minimum face size', 'Face height as a fraction of the frame for someone to count as the subject (not a passerby).'],
  ['min_face_blur', 'Sharpness gate', 'Below this focus score a face is treated as background blur.'],
  ['det_score_threshold', 'Detector confidence', 'How sure the face detector must be. Raise if junk gets detected.'],
  ['face_match_threshold', 'Same-person strictness', 'Lower = stricter matching (may split one person in two), higher = looser (may merge two people).'],
  ['preview_max_width', 'Preview width (px)', 'Size of live preview frames sent to the dashboard.'],
];

async function pageSettings() {
  let cfg, reg, cmp;
  try {
    [cfg, reg, cmp] = await Promise.all([
      API.get('/api/settings'),
      API.get('/api/registry'),
      API.get('/api/comparability').catch(() => null),
    ]);
  } catch (e) { return setMain(errPanel(e)); }

  const inputs = {};
  const rows = SETTING_DEFS.map(([k, lab, help]) => {
    const inp = el('input', { type: 'text', inputmode: 'decimal', value: cfg[k] });
    inputs[k] = inp;
    return el('div', { class: 'setrow' },
      el('div', { class: 'lab' }, lab, el('small', null, help)), inp);
  });
  const checks = ['preview_enabled', 'decode_reduced', 'sounds_enabled'].map(k => {
    const inp = el('input', { type: 'checkbox' });
    inp.checked = !!cfg[k];
    inputs[k] = inp;
    const labels = {
      preview_enabled: ['Live preview', 'Stream annotated frames to the dashboard while processing.'],
      decode_reduced: ['Fast decode', 'Read photos at half resolution — much faster, plenty for face work. Turn off only if faces are tiny.'],
      sounds_enabled: ['Sounds', 'Retro bleeps for prompts and the commit fanfare.'],
    };
    return el('div', { class: 'setrow' },
      el('div', { class: 'lab' }, labels[k][0], el('small', null, labels[k][1])),
      el('div', null, inp));
  });

  const saveBtn = el('button', { class: 'btn green', onclick: async () => {
    const body = {};
    for (const [k, inp] of Object.entries(inputs))
      body[k] = inp.type === 'checkbox' ? inp.checked : inp.value;
    const r = await API.post('/api/settings', body);
    Sfx.enabled = !!r.sounds_enabled;
    toast('Settings saved. Stale days are brought up to date automatically in the background.');
    Sfx.blip();
  } }, 'Save settings');

  const recomputeBtn = el('button', { class: 'btn bark', onclick: async () => {
    if (!confirm('Re-run engagement math on ALL stored days with the current settings? Photos are not needed — this uses stored data. Excel exports get refreshed.')) return;
    toast('Recomputing the whole jungle…');
    const r = await API.post('/api/recompute', {});
    toast(`Recomputed ${r.recomputed} days`); Sfx.tada();
  } }, 'Recompute all days');

  /* registry */
  function regList(kind, items) {
    return el('div', null,
      el('h3', { class: 'mb' }, kind === 'name' ? 'Apes' : 'Hunting grounds'),
      items.length ? items.map(n => el('div', { class: 'spread', style: 'padding:6px 0;border-bottom:2px dashed rgba(237,230,208,.1)' },
        el('span', null, n),
        el('button', { class: 'btn bark', style: 'font-size:7px;padding:7px 10px 6px', onclick: async () => {
          const nu = prompt(`Rename "${n}" to:`, n);
          if (!nu || nu === n) return;
          await API.post('/api/registry/rename', { kind, old: n, new: nu });
          toast(`Renamed across all days: ${n} → ${nu}`);
          pageSettings();
        } }, 'Rename'))) : el('p', { class: 'dim' }, 'None yet.'));
  }

  /* import */
  const impPath = el('input', { type: 'text', placeholder: cfg._data_dir + '/exports', style: 'flex:1;min-width:220px' });
  const impBtn = el('button', { class: 'btn bark', onclick: async () => {
    const path = impPath.value || (cfg._data_dir + '/exports');
    toast('Importing…');
    const r = await API.post('/api/import', { path });
    const ok = r.results.filter(x => x.ok).length;
    const bad = r.results.filter(x => !x.ok);
    toast(`Imported ${ok} day${ok === 1 ? '' : 's'}` + (bad.length ? `, ${bad.length} failed` : ''));
    bad.slice(0, 3).forEach(x => toast(`${x.file}: ${x.error}`, true));
  } }, 'Import');

  /* comparability section */
  const cmpSection = el('div', { class: 'panel' },
    el('h2', null, 'Comparability'),
    el('div', { class: 'setrow' },
      el('div', { class: 'lab' }, 'Processing fingerprint',
        el('small', null, 'Encodes the model + algorithm versions in use. Days with a matching fingerprint are directly comparable.')),
      el('span', { class: 'gold small' }, (cmp && cmp.current_fingerprint) || '–')),
    el('div', { class: 'setrow' },
      el('div', { class: 'lab' }, 'Days catching up',
        el('small', null, 'Days whose fingerprint differs from the current one. TarzanIQ auto-recomputes cheap changes; expensive reprocessing is queued when you confirm.')),
      el('span', { class: 'gold small' }, cmp ? String(cmp.stale) : '–')),
    (cmp && (cmp.by_route || {}).legacy > 0)
      ? el('p', { class: 'small dim mt' },
          `${cmp.by_route.legacy} legacy day${cmp.by_route.legacy > 1 ? 's' : ''} have no archive and are excluded from comparisons until reprocessed from original photos.`)
      : '',
    el('div', { class: 'btnrow mt' },
      el('button', { class: 'btn bark', onclick: async () => {
        toast('Enqueuing all stale days…');
        const r = await API.post('/api/bring-current', {});
        toast(`Recomputed ${r.recomputed || 0}, queued ${r.reprocess_queued || 0} for reprocessing, ${r.legacy || 0} legacy`);
        Sfx.blip();
        pageSettings();
      } }, 'Bring everything up to date')));

  setMain(
    el('div', { class: 'panel' },
      el('h2', null, 'Engagement rules'), rows,
      el('h2', { class: 'mt' }, 'App'), checks,
      el('div', { class: 'btnrow mt' }, saveBtn, recomputeBtn)),
    el('div', { class: 'row' },
      el('div', { class: 'panel' }, regList('name', reg.names)),
      el('div', { class: 'panel' }, regList('place', reg.places))),
    el('div', { class: 'panel' },
      el('h2', null, 'Rebuild from Excel exports'),
      el('p', { class: 'small dim' }, 'Lost the database? Every export carries the full day inside it. Point at a folder of TarzanIQ .xlsx files (or one file) to re-import.'),
      el('div', { class: 'btnrow mt' }, impPath, impBtn)),
    cmpSection,
    el('div', { class: 'panel bark' },
      el('h2', null, 'Where things live'),
      el('p', null, 'Data folder: ', el('b', { class: 'gold' }, cfg._data_dir)),
      el('p', { class: 'small dim mt' },
        'Holds the database, Excel exports, models, logs and weekly backups. It survives reinstalls — photos are never stored, only the numbers mined from them.')));
}
