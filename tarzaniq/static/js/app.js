/* TarzanIQ app.js — router + boot */
'use strict';

const ROUTES = [
  [/^\/$/, () => pageOverview()],
  [/^\/live$/, () => pageLive()],
  [/^\/apes$/, () => pageApes()],
  [/^\/ape\/(.+)$/, m => pageApe(decodeURIComponent(m[1]))],
  [/^\/compare\/([^/]+)\/([^/]+)$/, m => pageCompare(decodeURIComponent(m[1]), decodeURIComponent(m[2]))],
  [/^\/places$/, () => pagePlaces()],
  [/^\/patterns$/, () => pagePatterns()],
  [/^\/day\/(\d+)$/, m => pageDay(parseInt(m[1], 10))],
  [/^\/settings$/, () => pageSettings()],
];

function route() {
  killCharts();
  const h = location.hash.replace(/^#/, '') || '/';
  document.querySelectorAll('nav a').forEach(a => {
    const target = a.getAttribute('href').replace(/^#/, '');
    const on = target === '/' ? h === '/' : h.startsWith(target);
    a.classList.toggle('on', on);
  });
  for (const [re, fn] of ROUTES) {
    const m = h.match(re);
    if (m) { fn(m); return; }
  }
  location.hash = '#/';
}

window.addEventListener('hashchange', route);

window.addEventListener('DOMContentLoaded', async () => {
  chartDefaults();
  modalShell();
  Live.connect();
  try {
    const cfg = await API.get('/api/settings');
    Sfx.enabled = !!cfg.sounds_enabled;
  } catch (e) { /* fine */ }
  route();
});
