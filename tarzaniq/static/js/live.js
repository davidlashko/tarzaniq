/* TarzanIQ live.js — SSE stream, live viewer, prompts, queue */
'use strict';

const Live = {
  es: null,
  queue: [],
  prompt: null,
  paused: false,
  frames: [],          // ring buffer of {img, filename, time, kind, counts,...}
  viewIdx: -1,         // -1 = follow live
  lastFrame: null,
  lastCounts: null,
  connected: false,

  connect() {
    if (this.es) return;
    const es = new EventSource('/api/process/stream');
    this.es = es;
    es.addEventListener('hello', e => {
      const d = JSON.parse(e.data);
      this.queue = d.queue || [];
      this.paused = !!d.paused;
      this.setPrompt(d.prompt);
      this.connected = true;
      this.refresh();
    });
    es.addEventListener('frame', e => {
      const d = JSON.parse(e.data);
      this.lastFrame = d;
      this.lastCounts = d.counts;
      this.frames.push(d);
      if (this.frames.length > 250) this.frames.shift();
      this.refresh(true);
    });
    es.addEventListener('status', e => {
      const d = JSON.parse(e.data);
      if (d.counts) this.lastCounts = d.counts;
      this.refresh();
    });
    es.addEventListener('queue', e => {
      this.queue = JSON.parse(e.data) || [];
      this.refreshQueue();
      updateNavDot();
    });
    es.addEventListener('prompt', e => {
      this.setPrompt(e.data && e.data !== 'null' ? JSON.parse(e.data) : null);
    });
    es.addEventListener('paused', e => {
      this.paused = !!JSON.parse(e.data).paused;
      this.refresh();
    });
    es.addEventListener('committed', e => {
      const d = JSON.parse(e.data);
      bananaRain(30); Sfx.tada();
      toast(`${d.job.name} — saved to the dataset!`);
      updateNavDot();
    });
    es.addEventListener('job_done', e => {
      const d = JSON.parse(e.data);
      if (d.status === 'error') { toast(`${d.name}: ${d.message}`, true); Sfx.thud(); }
      else if (d.status === 'discarded' || d.status === 'skipped') {
        toast(`${d.name}: ${d.message || d.status}`);
      }
      updateNavDot();
    });
    es.onerror = () => { /* EventSource auto-reconnects */ };
  },

  setPrompt(p) {
    const had = !!this.prompt;
    this.prompt = p;
    renderModal(p);
    if (p && !had) Sfx.ask();
    updateNavDot();
  },

  busy() {
    return this.queue.some(j =>
      ['queued', 'scanning', 'processing', 'waiting', 'committing'].includes(j.status));
  },

  refresh(frameOnly) {
    if (location.hash.replace(/^#/, '') === '/live' || location.hash === '') {
      if (typeof renderLiveDynamic === 'function') renderLiveDynamic(frameOnly);
    }
  },
  refreshQueue() {
    const q = document.getElementById('qstrip');
    if (q) { q.innerHTML = ''; q.append(...queueChips()); }
    this.refresh();
  },

  async togglePause() {
    try {
      const r = await API.post('/api/process/pause', { paused: !this.paused });
      this.paused = r.paused; Sfx.blip(); this.refresh();
    } catch (e) { toast('Could not reach TarzanIQ', true); }
  },
  nav(delta) {
    if (!this.frames.length) return;
    if (this.viewIdx === -1) this.viewIdx = this.frames.length - 1;
    this.viewIdx = Math.max(0, Math.min(this.frames.length - 1, this.viewIdx + delta));
    Sfx.blip();
    this.refresh();
  },
  goLive() { this.viewIdx = -1; this.refresh(); },
};

function updateNavDot() {
  const dot = document.getElementById('navdot');
  if (dot) dot.style.display = (Live.busy() || Live.prompt) ? 'inline-block' : 'none';
}

/* ---------------------------------------------------- add day flow */
async function addDayFlow() {
  Sfx.blip();
  try {
    const r = await API.post('/api/pickfolder', {});
    if (r.error && !r.folders.length) {
      toast(r.error, true); return;
    }
    if (!r.folders || !r.folders.length) return;
    await enqueueFolders(r.folders);
  } catch (e) { toast('Folder picker failed: ' + e.message, true); }
}

async function enqueueFolders(folders) {
  const r = await API.post('/api/enqueue', { folders });
  (r.errors || []).forEach(j =>
    toast(`${j.name}: ${j.message}`, true));
  if ((r.added || []).length) {
    toast(`${r.added.length} folder${r.added.length > 1 ? 's' : ''} queued for the expedition`);
    location.hash = '#/live';
  }
}

/* ---------------------------------------------------- queue chips */
function queueChips() {
  if (!Live.queue.length)
    return [el('span', { class: 'dim' }, 'Queue is empty.')];
  return Live.queue.slice().reverse().map(j => {
    const chip = el('span', { class: 'qjob' },
      j.name + ' ',
      el('span', { class: 'st ' + j.status }, j.status));
    if (['queued', 'scanning', 'processing', 'waiting'].includes(j.status)) {
      chip.append(' ', el('a', { href: '#', onclick: ev => {
        ev.preventDefault();
        API.post('/api/process/cancel', { job_id: j.id });
        toast('Cancelling ' + j.name);
      }, title: 'Cancel this job' }, '✕'));
    }
    if (j.status === 'done' && j.day_id) {
      chip.append(' ', el('a', { href: '#/day/' + j.day_id }, '→ view'));
    }
    return chip;
  });
}

/* ---------------------------------------------------- live page */
function pageLive() {
  Live.viewIdx = -1;
  const queuePanel = el('div', { class: 'panel' },
    el('div', { class: 'spread' },
      el('h2', null, 'Expedition queue'),
      el('div', { class: 'btnrow' },
        el('button', { class: 'btn', onclick: addDayFlow }, '+ Add day folder'))),
    el('div', { class: 'qstrip', id: 'qstrip' }, queueChips()));

  const frame = el('div', { id: 'liveframe' },
    el('div', { id: 'liveimgbox' }),
    el('div', { class: 'scan' }), el('div', { class: 'crt' }),
    el('div', { id: 'pausedflag' }),
    el('div', { id: 'livehud' }));

  const vine = el('div', null,
    el('div', { class: 'vinewrap' },
      el('div', { class: 'vinefill', id: 'vinefill' }),
      el('img', { class: 'vineape', id: 'vineape', src: '/static/img/logo.png' }),
      el('img', { class: 'vinegoal', src: pixURL('banana', 4) })),
    el('div', { class: 'vinetext' },
      el('span', { id: 'vineleft' }, ''), el('span', { id: 'vineright' }, '')));

  const counts = el('div', { class: 'hudcounts', id: 'hudcounts' });

  const controls = el('div', { class: 'btnrow mt' },
    el('button', { class: 'btn bark', id: 'pausebtn', onclick: () => Live.togglePause() }, 'Pause'),
    el('button', { class: 'btn bark', onclick: () => Live.nav(-1), title: 'Previous frame' }, '◀'),
    el('button', { class: 'btn bark', onclick: () => Live.nav(1), title: 'Next frame' }, '▶'),
    el('button', { class: 'btn green', onclick: () => Live.goLive() }, 'Live'),
    el('span', { class: 'small dim' },
      ' ', el('span', { class: 'kbd' }, 'SPACE'), ' pause   ',
      el('span', { class: 'kbd' }, '◀ ▶'), ' browse   ',
      el('span', { class: 'kbd' }, 'ESC'), ' live'));

  const viewer = el('div', { class: 'panel', id: 'viewerpanel' },
    el('h2', null, 'Field camera'), frame, vine, counts, controls);

  setMain(queuePanel, viewer);
  renderLiveDynamic();
}

function renderLiveDynamic(frameOnly) {
  const imgbox = document.getElementById('liveimgbox');
  if (!imgbox) return;
  const hud = document.getElementById('livehud');
  const pausedflag = document.getElementById('pausedflag');
  const fill = document.getElementById('vinefill');
  const ape = document.getElementById('vineape');
  const countsBox = document.getElementById('hudcounts');
  const pbtn = document.getElementById('pausebtn');

  const f = Live.viewIdx === -1
    ? Live.lastFrame
    : Live.frames[Live.viewIdx];

  if (pbtn) pbtn.textContent = Live.paused ? 'Resume' : 'Pause';
  if (pausedflag) {
    let label = '';
    if (Live.paused) label = '⏸ PAUSED';
    else if (Live.viewIdx !== -1) label = '⏪ BROWSING';
    pausedflag.className = label ? 'pausedflag' : '';
    pausedflag.textContent = label;
    pausedflag.style.display = label ? 'block' : 'none';
  }

  if (!f) {
    imgbox.innerHTML = '';
    imgbox.append(el('div', { class: 'idleape' },
      el('img', { src: '/static/img/logo.png' }),
      el('div', { class: 'mt' }, Live.busy()
        ? 'Reading photo times… the show starts in a moment.'
        : 'No expedition running.'),
      el('div', { class: 'dim small mt' }, Live.busy() ? '' :
        'Right-click a day folder in Finder → Analyze with TarzanIQ, drop it on the app, or click Add Day.')));
    if (hud) hud.style.display = 'none';
    if (fill) fill.style.width = '0%';
    if (ape) ape.style.left = '0%';
    setText('vineleft', ''); setText('vineright', '');
    if (countsBox && Live.lastCounts) renderCounts(countsBox, Live.lastCounts);
    return;
  }

  imgbox.innerHTML = '';
  const img = el('img', { src: 'data:image/jpeg;base64,' + f.img });
  imgbox.append(img);

  if (hud) {
    hud.style.display = 'flex';
    hud.innerHTML = '';
    const kindCls = { cold: 'cold', warm: 'warm', mixed: 'mixed', air: 'air' }[f.kind] || 'air';
    hud.append(
      el('span', { class: 'badge ' + kindCls }, f.kind),
      el('span', { class: 'fn' }, f.filename),
      el('span', null, f.time),
      el('span', { class: 'dim' },
        Live.viewIdx === -1 ? `photo ${f.i} / ${f.n}` :
          `frame ${Live.viewIdx + 1} / ${Live.frames.length} (buffer)`),
      f.new && f.new.length ? el('span', { class: 'gold' }, `+${f.new.length} new mark`) : '',
      f.warm_started && f.warm_started.length ? el('span', { style: 'color:var(--warm)' }, '🔥 warm shoot!') : '');
  }

  const pctv = f.n ? (f.i / f.n) * 100 : 0;
  if (fill) fill.style.width = pctv.toFixed(1) + '%';
  if (ape) ape.style.left = pctv.toFixed(1) + '%';
  setText('vineleft', `${f.i} / ${f.n} photos`);
  setText('vineright',
    f.eta_s !== undefined && Live.viewIdx === -1
      ? `~${fmt.dur(f.eta_s)} to the banana  ·  ${f.rate}/s` : '');

  if (countsBox && (f.counts || Live.lastCounts))
    renderCounts(countsBox, f.counts || Live.lastCounts);
}

function setText(id, s) {
  const n = document.getElementById(id); if (n) n.textContent = s;
}

function renderCounts(box, c) {
  box.innerHTML = '';
  const conv = c.cold_persons ? c.warm_persons / c.cold_persons : null;
  box.append(
    el('span', { class: 'hudpill cold' }, 'Cold marks', el('b', null, String(c.cold_persons))),
    el('span', { class: 'hudpill warm' }, 'Warm', el('b', null, String(c.warm_persons))),
    el('span', { class: 'hudpill conv' }, 'Conversion', el('b', null, fmt.pct(conv))),
    el('span', { class: 'hudpill' }, 'Approaches', el('b', null, String(c.cold_events))),
    el('span', { class: 'hudpill' }, 'Breaks', el('b', null, String(c.breaks))));
}

/* ---------------------------------------------------- prompt modals */
function modalShell() {
  let back = document.getElementById('modalback');
  if (!back) {
    back = el('div', { id: 'modalback' }, el('div', { id: 'modal' }));
    document.body.append(back);
  }
  return back;
}

function renderModal(p) {
  const back = modalShell();
  const modal = back.querySelector('#modal');
  if (!p) { back.classList.remove('show'); modal.innerHTML = ''; return; }
  modal.innerHTML = '';
  const send = data => {
    API.post('/api/prompt/answer', Object.assign({ id: p.id }, data))
      .catch(() => toast('Could not send the answer', true));
    back.classList.remove('show');
  };
  const T = p.type, pl = p.payload || {};

  if (T === 'new_name' || T === 'new_place') {
    const what = T === 'new_name' ? 'photographer' : 'place';
    const sel = el('select', null,
      (pl.known || []).map(k => el('option', { value: k }, k)));
    modal.append(
      el('h2', null, `New ${what} spotted`),
      el('p', null, `"${pl.value}" isn't in the troop yet (from folder `,
        el('span', { class: 'gold' }, p.job_name), ').'),
      el('div', { class: 'mrow btnrow' },
        el('button', { class: 'btn green', onclick: () => send({ action: 'add' }) },
          `Add "${pl.value}"`)),
      (pl.known || []).length ? el('div', { class: 'mrow' },
        el('label', null, `…or was it a typo? Map it to:`),
        el('div', { class: 'btnrow' }, sel,
          el('button', { class: 'btn bark', onclick: () => send({ action: 'map', map_to: sel.value }) }, 'Map'))) : '',
      el('div', { class: 'mrow btnrow' },
        el('button', { class: 'btn red', onclick: () => send({ action: 'cancel' }) }, 'Cancel this folder')));
  } else if (T === 'duplicate_day') {
    modal.append(
      el('h2', null, 'Already in the dataset'),
      el('p', null, `${pl.date} · ${pl.place} · ${pl.employee} has been analyzed before.`),
      el('p', { class: 'dim small mt' }, 'Replace re-runs everything and overwrites the old day (its money entry is cleared).'),
      el('div', { class: 'mrow btnrow' },
        el('button', { class: 'btn red', onclick: () => send({ action: 'replace' }) }, 'Replace it'),
        el('button', { class: 'btn bark', onclick: () => send({ action: 'skip' }) }, 'Skip this folder')));
  } else if (T === 'money') {
    const cash = el('input', { type: 'text', inputmode: 'decimal', placeholder: 'e.g. 4500' });
    const card = el('input', { type: 'text', inputmode: 'decimal', placeholder: 'e.g. 1200' });
    modal.append(
      el('h2', null, 'Day finished — count the bananas'),
      summaryCard(pl.summary),
      el('p', { class: 'dim small' }, 'Optional. One number for the whole day — sales can\'t be tied to specific shoots.'),
      el('div', { class: 'mrow' }, el('label', null, 'Cash collected'), cash),
      el('div', { class: 'mrow' }, el('label', null, 'Card collected'), card),
      el('div', { class: 'mrow btnrow' },
        el('button', { class: 'btn green', onclick: () => send({ cash: cash.value, card: card.value }) }, 'Save'),
        el('button', { class: 'btn bark', onclick: () => send({}) }, 'Skip')));
    setTimeout(() => cash.focus(), 60);
  } else if (T === 'commit') {
    modal.append(
      el('h2', null, 'Add this day to the dataset?'),
      summaryCard(pl.summary),
      pl.cash || pl.card ? el('p', null, 'Money: ',
        el('b', { class: 'gold' },
          `${fmt.money(pl.cash)} cash + ${fmt.money(pl.card)} card`)) : '',
      el('div', { class: 'mrow btnrow' },
        el('button', { class: 'btn big green', onclick: () => send({ commit: true }) }, 'Yes — add it'),
        el('button', { class: 'btn red', onclick: () => send({ commit: false }) }, 'Discard')));
  } else {
    modal.append(el('h2', null, p.type),
      el('pre', null, JSON.stringify(pl, null, 2)),
      el('button', { class: 'btn', onclick: () => send({}) }, 'OK'));
  }
  back.classList.add('show');
}

function summaryCard(s) {
  if (!s) return el('div');
  const sc = (v, lab) => el('div', { class: 'sc' }, el('b', null, v), el('span', null, lab));
  return el('div', { class: 'summarycard' },
    sc(fmt.int(s.photos), 'photos'),
    sc(fmt.int(s.cold_persons), 'cold marks'),
    sc(fmt.int(s.warm_persons), 'warm'),
    sc(fmt.pct(s.conversion), 'conversion'),
    sc(fmt.dur(s.shoot_s), 'shooting'),
    s.suspected_deletions ? sc(fmt.int(s.suspected_deletions), 'deleted?') : '');
}

/* ---------------------------------------------------- keyboard */
document.addEventListener('keydown', ev => {
  const onLive = location.hash.replace(/^#/, '') === '/live';
  if (!onLive) return;
  if (ev.target.tagName === 'INPUT' || ev.target.tagName === 'SELECT') return;
  if (ev.code === 'Space') { ev.preventDefault(); Live.togglePause(); }
  else if (ev.key === 'ArrowLeft') { ev.preventDefault(); Live.nav(-1); }
  else if (ev.key === 'ArrowRight') { ev.preventDefault(); Live.nav(1); }
  else if (ev.key === 'Escape') { Live.goLive(); }
});
