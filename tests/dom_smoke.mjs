/* DOM smoke test — boots the real SPA in jsdom (scripts executed like a
   browser) against a live server, renders every page, exercises modals.
   Run:  node tests/dom_smoke.mjs http://127.0.0.1:43991 */
import pkg from 'jsdom';
const { JSDOM } = pkg;

const BASE = process.argv[2] || 'http://127.0.0.1:43991';

let fails = [];
const check = (label, cond, detail) => {
  if (cond) console.log('  ok    ' + label);
  else { fails.push(label); console.log('  FAIL  ' + label + '  ' + (detail || '')); }
};
const sleep = ms => new Promise(r => setTimeout(r, ms));

const ctx2dStub = () => new Proxy({ canvas: {} }, {
  get: (t, p) => (p in t ? t[p] : () => ctxNest(p)),
  set: (t, p, v) => { t[p] = v; return true; },
});
const ctxNest = () => undefined;

const dom = await JSDOM.fromURL(BASE + '/', {
  runScripts: 'dangerously',
  resources: 'usable',
  pretendToBeVisual: true,
  beforeParse(window) {
    window.fetch = (input, init) =>
      globalThis.fetch(new URL(String(input), BASE).href, init);
    window.EventSource = class {
      constructor() { this.onerror = null; }
      addEventListener() {} close() {}
    };
    window.AudioContext = class {
      get currentTime() { return 0; }
      createOscillator() { return { type: '', frequency: { value: 0 }, connect() {}, start() {}, stop() {} }; }
      createGain() { return { gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {} }; }
      get destination() { return {}; }
    };
    window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
    window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }));
    window.HTMLCanvasElement.prototype.getContext = function () { return ctx2dStub(); };
    window.HTMLCanvasElement.prototype.toDataURL = () => 'data:,';
    window.confirm = () => true;
    window.prompt = () => null;
    window.scrollTo = () => {};
  },
});
const { window } = dom;

await new Promise(res => {
  if (window.document.readyState === 'complete') res();
  else window.addEventListener('load', () => res());
});
await sleep(400); // boot: settings fetch + initial route render

const G = expr => window.eval(expr);
const main = () => window.document.querySelector('main');

/* replace Chart.js with a config-validating stub for page renders */
window.Chart = class {
  constructor(ctx, cfg) {
    if (!cfg || !cfg.data || !Array.isArray(cfg.data.datasets))
      throw new Error('bad chart config');
  }
  destroy() {}
};
window.Chart.defaults = {
  font: {}, color: '', borderColor: '',
  plugins: { legend: { labels: {} }, tooltip: {} }, animation: {},
};

check('boot rendered overview', main().textContent.includes('Leaderboard'),
  main().textContent.slice(0, 120));

async function renderPage(label, expr, expectText) {
  try {
    await G(expr);
    await sleep(180);
    const txt = main().textContent;
    check(label, txt.includes(expectText), 'missing: ' + expectText);
  } catch (e) {
    check(label, false, (e && e.stack ? e.stack.split('\n').slice(0, 2).join(' @ ') : String(e)));
  }
}

const ov = await (await fetch(BASE + '/api/overview')).json();
check('overview has 3 apes', ov.leaderboard.length === 3, ov.leaderboard.length);
check('best ape is Marko (skill ordering)', ov.leaderboard[0].employee === 'Marko',
  ov.leaderboard[0].employee);

await renderPage('apes renders', 'pageApes()', 'The troop');
await renderPage('ape profile renders', "pageApe('Marko')", 'Ape skills');
await renderPage('compare renders', "pageCompare('Marko','Ana')", 'Head to head');
await renderPage('places renders', 'pagePlaces()', 'Hunting grounds');
await renderPage('patterns renders', 'pagePatterns()', 'Warm shoots per hour');

const days = await (await fetch(BASE + '/api/days')).json();
check('days listed', days.days.length >= 25, days.days.length);
await renderPage('day detail renders', `pageDay(${days.days[0].id})`, 'Field notes');
check('day timeline has blocks', main().querySelectorAll('.tlblock').length > 2,
  main().querySelectorAll('.tlblock').length);

await renderPage('settings renders', 'pageSettings()', 'Engagement rules');
await renderPage('live page renders', 'pageLive()', 'Field camera');

/* live frame rendering */
G(`Live.lastFrame = { img: 'AAAA', filename: 'DSC0001.JPG', time: '10:00:00',
  kind: 'cold', i: 5, n: 100, counts: { cold_persons: 3, warm_persons: 1,
  cold_events: 3, breaks: 0 }, eta_s: 120, rate: 4.1, new: [2], warm_started: [] };
Live.frames = [Live.lastFrame];
renderLiveDynamic();`);
check('live HUD shows kind badge', main().textContent.includes('cold'));
check('vine fill moves',
  window.document.getElementById('vinefill').style.width === '5%' ||
  window.document.getElementById('vinefill').style.width === '5.0%',
  window.document.getElementById('vinefill').style.width);

/* prompt modals — every type must render with buttons */
const types = [
  ['new_name', { value: 'Goran', known: ['Marko', 'Ana'] }],
  ['new_place', { value: 'Mall', known: ['CityPark'] }],
  ['duplicate_day', { date: '2026-06-01', place: 'CityPark', employee: 'Marko' }],
  ['money', { summary: { photos: 100, cold_persons: 10, warm_persons: 5, conversion: 0.5, shoot_s: 7200, suspected_deletions: 1 } }],
  ['commit', { summary: { photos: 100, cold_persons: 10, warm_persons: 5, conversion: 0.5, shoot_s: 7200 }, cash: 100, card: 50 }],
];
for (const [t, payload] of types) {
  try {
    G(`renderModal(${JSON.stringify({ id: 'x1', type: t, payload, job_name: 'test.folder' })})`);
    const visible = window.document.getElementById('modalback').classList.contains('show');
    const hasBtn = window.document.querySelectorAll('#modal .btn').length > 0;
    check(`modal ${t} renders`, visible && hasBtn);
  } catch (e) { check(`modal ${t} renders`, false, String(e)); }
}
G('renderModal(null)');
check('modal hides', !window.document.getElementById('modalback').classList.contains('show'));

check('pixel icon URL', G("pixURL('banana', 4)").startsWith('data:'));

console.log(fails.length ? `${fails.length} FAILURES: ${fails.join(', ')}` : 'ALL GREEN');
window.close();
process.exit(fails.length ? 1 : 0);
