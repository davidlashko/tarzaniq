/* TarzanIQ util.js — helpers, pixel icons, toasts, confetti, bleeps */
'use strict';

const API = {
  async get(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${path} -> ${r.status}`);
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) throw new Error(`${path} -> ${r.status}`);
    return r.json();
  },
  async del(path) {
    const r = await fetch(path, { method: 'DELETE' });
    return r.json();
  },
};

/* ---------------------------------------------------- formatters */
const fmt = {
  pct(x, dash) {
    if (x === null || x === undefined || isNaN(x)) return dash || '–';
    return (x * 100).toFixed(x >= 0.995 ? 0 : 0) + '%';
  },
  pct1(x) {
    if (x === null || x === undefined || isNaN(x)) return '–';
    return (x * 100).toFixed(1) + '%';
  },
  num(x, d) {
    if (x === null || x === undefined || isNaN(x)) return '–';
    return Number(x).toLocaleString('en-US', {
      maximumFractionDigits: d === undefined ? 1 : d,
      minimumFractionDigits: 0,
    });
  },
  int(x) {
    if (x === null || x === undefined || isNaN(x)) return '–';
    return Math.round(x).toLocaleString('en-US');
  },
  dur(s) {
    if (s === null || s === undefined || isNaN(s)) return '–';
    s = Math.round(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    if (h) return `${h}h ${String(m).padStart(2, '0')}m`;
    if (m) return `${m}m ${String(sec).padStart(2, '0')}s`;
    return `${sec}s`;
  },
  money(x) {
    if (x === null || x === undefined || isNaN(x)) return '–';
    return Number(x).toLocaleString('en-US', { maximumFractionDigits: 2 });
  },
  date(d) { return d; },
};

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k === 'html') e.innerHTML = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) e.setAttribute(k, v);
  }
  for (const k of kids.flat()) {
    if (k === null || k === undefined) continue;
    e.append(k.nodeType ? k : document.createTextNode(k));
  }
  return e;
}
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ---------------------------------------------------- pixel icons */
const PIX_PAL = {
  K: '#0E1311', D: '#343A40', T: '#7D6553', t: '#5C4937',
  G: '#3FA34D', g: '#1F6F43', Y: '#FFD23F', y: '#E0A91C',
  B: '#6B4A2F', W: '#EDE6D0', C: '#7FC8E8', O: '#F4A23C',
  R: '#E2603F', S: '#868E96', P: '#15181B',
};
const PIX = {
  banana: ['......BK', '.....KYK', '....KYYK', '...KYYyK',
           '..KYYyK.', '.KYYyK..', 'KYYyK...', '.KKK....'],
  camera: ['........', 'KKKKKKKK', 'KSSKKSSK', 'KSKWWKSK',
           'KSKWPKSK', 'KSKKKKSK', 'KSSSSSSK', 'KKKKKKKK'],
  foot:   ['.KK..KK.', 'KTTKKTTK', '.KK..KK.', '..KKKK..',
           '.KTTTTK.', '.KTTTTK.', '..KTTK..', '...KK...'],
  fire:   ['...K....', '..KOK...', '..KOK.K.', '.KOYOKOK',
           '.KOYYOOK', 'KOYYYYOK', 'KOYYYYOK', '.KKKKKK.'],
  crown:  ['........', 'K..K..K.', 'KK.KK.KK', 'KYKYYKYK',
           'KYYYYYYK', 'KYYYYYYK', 'KKKKKKKK', '........'],
  leaf:   ['....KK..', '...KGGK.', '..KGGGK.', '.KGGGGK.',
           '.KGGGK..', 'KGGGK...', 'KGGK....', '.KK.....'],
  money:  ['.KKKKKK.', 'KYYYYYYK', 'KYKYYKYK', 'KYYKKYYK',
           'KYYKKYYK', 'KYKYYKYK', 'KYYYYYYK', '.KKKKKK.'],
  clock:  ['..KKKK..', '.KWWWWK.', 'KWWKWWWK', 'KWWKWWWK',
           'KWWKKWWK', 'KWWWWWWK', '.KWWWWK.', '..KKKK..'],
  target: ['..KKKK..', '.KCCCCK.', 'KCKKKKCK', 'KCKOOKCK',
           'KCKOOKCK', 'KCKKKKCK', '.KCCCCK.', '..KKKK..'],
  pin:    ['..KKKK..', '.KGGGGK.', 'KGGKKGGK', 'KGGKKGGK',
           '.KGGGGK.', '.KGGGK..', '..KGK...', '...K....'],
  gear:   ['.K.KK.K.', 'KSKSSKSK', '.KSSSSK.', 'KSSKKSSK',
           'KSSKKSSK', '.KSSSSK.', 'KSKSSKSK', '.K.KK.K.'],
  skull:  ['.KKKKKK.', 'KWWWWWWK', 'KWKWWKWK', 'KWWWWWWK',
           '.KWKKWK.', '.KWWWWK.', '..K..K..', '........'],
  vs:     ['K.....K.', 'K.....K.', 'K..K..K.', '.K.K.K..',
           '..KKK...', '...K....', '...K....', '........'],
};
const _pixCache = {};
function pixURL(name, scale) {
  scale = scale || 4;
  const key = name + ':' + scale;
  if (_pixCache[key]) return _pixCache[key];
  const grid = PIX[name];
  if (!grid) return '';
  const h = grid.length, w = Math.max(...grid.map(r => r.length));
  const c = document.createElement('canvas');
  c.width = w * scale; c.height = h * scale;
  const ctx = c.getContext('2d');
  grid.forEach((row, y) => {
    [...row].forEach((ch, x) => {
      const col = PIX_PAL[ch];
      if (!col) return;
      ctx.fillStyle = col;
      ctx.fillRect(x * scale, y * scale, scale, scale);
    });
  });
  _pixCache[key] = c.toDataURL();
  return _pixCache[key];
}
function pixImg(name, h, cls) {
  const i = el('img', { src: pixURL(name, 6), class: cls || '' });
  i.style.height = (h || 24) + 'px';
  i.style.imageRendering = 'pixelated';
  return i;
}

/* ---------------------------------------------------- toasts */
function toast(msg, err) {
  let box = document.getElementById('toasts');
  if (!box) { box = el('div', { id: 'toasts' }); document.body.append(box); }
  const t = el('div', { class: 'toast' + (err ? ' err' : '') }, msg);
  box.append(t);
  setTimeout(() => t.remove(), 4200);
}

/* ---------------------------------------------------- confetti */
function bananaRain(n) {
  const url = pixURL('banana', 4);
  for (let i = 0; i < (n || 26); i++) {
    const b = el('img', { src: url, class: 'confetti' });
    b.style.left = Math.random() * 100 + 'vw';
    b.style.width = (18 + Math.random() * 22) + 'px';
    b.style.animationDuration = (1.6 + Math.random() * 1.6) + 's';
    b.style.animationDelay = (Math.random() * 0.5) + 's';
    document.body.append(b);
    setTimeout(() => b.remove(), 4200);
  }
}

/* ---------------------------------------------------- bleeps */
const Sfx = {
  ctx: null, enabled: true,
  _ctx() {
    if (!this.ctx) {
      try { this.ctx = new (window.AudioContext || window.webkitAudioContext)(); }
      catch (e) { this.ctx = null; }
    }
    return this.ctx;
  },
  tone(freq, dur, when, type) {
    const ctx = this._ctx();
    if (!ctx || !this.enabled) return;
    const t = ctx.currentTime + (when || 0);
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type || 'square'; o.frequency.value = freq;
    g.gain.setValueAtTime(0.06, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    o.connect(g); g.connect(ctx.destination);
    o.start(t); o.stop(t + dur + 0.02);
  },
  blip() { this.tone(660, 0.09); },
  ask()  { this.tone(520, 0.1); this.tone(780, 0.12, 0.11); },
  tada() { [523, 659, 784, 1047].forEach((f, i) => this.tone(f, 0.16, i * 0.09)); },
  thud() { this.tone(160, 0.18, 0, 'sawtooth'); },
};

/* ---------------------------------------------------- misc */
function crownIfTop(i) { return i === 0 ? pixImg('crown', 16) : ''; }
function qs(sel, root) { return (root || document).querySelector(sel); }
function setMain(...kids) {
  const m = qs('main'); m.innerHTML = ''; m.append(...kids.flat());
  window.scrollTo(0, 0);
}
function trendArrow(cur, prev) {
  if (cur === null || prev === null || cur === undefined || prev === undefined) return '';
  if (cur > prev * 1.03) return el('span', { class: 'up' }, ' ▲');
  if (cur < prev * 0.97) return el('span', { class: 'down' }, ' ▼');
  return el('span', { class: 'flat' }, ' ▬');
}
