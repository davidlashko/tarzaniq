/* TarzanIQ charts.js — Chart.js theming + builders + heatmap */
'use strict';

const C = {
  night: '#0B1A10', moss: '#142B1A', vine: '#1F6F43', leaf: '#3FA34D',
  banana: '#FFD23F', bark: '#6B4A2F', bone: '#EDE6D0', dim: '#B9C4AD',
  ink: '#0E1311', cold: '#7FC8E8', warm: '#F4A23C', danger: '#E2603F',
};

function chartDefaults() {
  if (!window.Chart) return;
  Chart.defaults.font.family = "'VT323', monospace";
  Chart.defaults.font.size = 16;
  Chart.defaults.color = C.dim;
  Chart.defaults.borderColor = 'rgba(237,230,208,.14)';
  Chart.defaults.plugins.legend.labels.boxWidth = 14;
  Chart.defaults.plugins.legend.labels.boxHeight = 14;
  Chart.defaults.plugins.tooltip.backgroundColor = C.moss;
  Chart.defaults.plugins.tooltip.borderColor = C.banana;
  Chart.defaults.plugins.tooltip.borderWidth = 2;
  Chart.defaults.plugins.tooltip.titleColor = C.banana;
  Chart.defaults.plugins.tooltip.bodyColor = C.bone;
  Chart.defaults.plugins.tooltip.cornerRadius = 0;
  Chart.defaults.animation.duration = 350;
}

const _charts = [];
function killCharts() { while (_charts.length) { try { _charts.pop().destroy(); } catch (e) {} } }
function mkChart(canvas, cfg) {
  const ch = new Chart(canvas.getContext('2d'), cfg);
  _charts.push(ch);
  return ch;
}
function chartBox(tall) {
  const cv = document.createElement('canvas');
  const box = el('div', { class: 'chartbox' + (tall ? ' tall' : '') }, cv);
  return { box, cv };
}

/* percent tick helper */
const pctTicks = { callback: v => Math.round(v * 100) + '%' };

/* ----------------------------------------------- builders */
function radarChart(cv, labels, datasets) {
  return mkChart(cv, {
    type: 'radar',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        r: {
          min: 0, max: 1,
          angleLines: { color: 'rgba(237,230,208,.18)' },
          grid: { color: 'rgba(237,230,208,.14)' },
          pointLabels: { color: C.bone, font: { family: "'Press Start 2P'", size: 8 } },
          ticks: { display: false },
        },
      },
      plugins: { legend: { position: 'bottom' } },
    },
  });
}

function lineChart(cv, labels, datasets, opts) {
  opts = opts || {};
  return mkChart(cv, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      scales: {
        y: Object.assign({ beginAtZero: true,
          ticks: opts.pct ? pctTicks : {} }, opts.y || {}),
        y2: opts.y2 ? { position: 'right', beginAtZero: true,
          grid: { drawOnChartArea: false } } : { display: false },
        x: { ticks: { maxRotation: 60, autoSkip: true } },
      },
      plugins: { legend: { position: 'bottom' } },
    },
  });
}

function barChart(cv, labels, datasets, opts) {
  opts = opts || {};
  return mkChart(cv, {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      indexAxis: opts.horizontal ? 'y' : 'x',
      scales: {
        [opts.horizontal ? 'x' : 'y']: { beginAtZero: true,
          ticks: opts.pct ? pctTicks : {} },
      },
      plugins: { legend: { display: !!opts.legend, position: 'bottom' } },
    },
  });
}

function donutChart(cv, labels, values, colors) {
  return mkChart(cv, {
    type: 'doughnut',
    data: { labels, datasets: [{ data: values, backgroundColor: colors,
      borderColor: C.ink, borderWidth: 3 }] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom' } }, cutout: '55%' },
  });
}

function ds(label, data, color, extra) {
  return Object.assign({
    label, data, borderColor: color, backgroundColor: color + 'cc',
    borderWidth: 3, pointRadius: 3, pointBackgroundColor: color,
    pointBorderColor: C.ink, pointBorderWidth: 1, tension: 0.25,
    fill: false,
  }, extra || {});
}
function radarDs(label, data, color, fillAlpha) {
  return { label, data, borderColor: color,
    backgroundColor: color + (fillAlpha || '33'),
    borderWidth: 3, pointRadius: 3, pointBackgroundColor: color,
    pointBorderColor: C.ink };
}

/* ----------------------------------------------- heatmap (CSS grid) */
function heatColor(v, max) {
  if (v === null || v === undefined || max <= 0) return C.moss;
  const t = Math.max(0, Math.min(1, v / max));
  // night -> vine -> leaf -> banana
  const stops = [
    [11, 26, 16], [31, 111, 67], [63, 163, 77], [255, 210, 63]];
  const f = t * (stops.length - 1);
  const i = Math.min(Math.floor(f), stops.length - 2);
  const u = f - i;
  const c = stops[i].map((a, k) => Math.round(a + (stops[i + 1][k] - a) * u));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

function heatmap(rows, cols, getVal, fmtVal) {
  // rows: labels (weekdays), cols: labels (hours)
  let max = 0;
  rows.forEach(r => cols.forEach(c => {
    const v = getVal(r, c);
    if (v !== null && v !== undefined && v > max) max = v;
  }));
  const grid = el('div', { class: 'heat' });
  grid.style.gridTemplateColumns = `90px repeat(${cols.length}, 1fr)`;
  grid.append(el('div', { class: 'hcell hlab top' }, ''));
  cols.forEach(c => grid.append(
    el('div', { class: 'hcell hlab top' }, String(c).padStart(2, '0'))));
  rows.forEach(r => {
    grid.append(el('div', { class: 'hcell hlab' }, r.slice(0, 3)));
    cols.forEach(c => {
      const v = getVal(r, c);
      const cell = el('div', { class: 'hcell',
        title: `${r} ${String(c).padStart(2, '0')}:00 — ${v === null || v === undefined ? 'no data' : fmtVal(v)}` },
        v === null || v === undefined ? '' : fmtVal(v));
      cell.style.background = heatColor(v, max);
      if (v !== null && v !== undefined && max > 0 && v / max > 0.55)
        cell.style.color = C.ink;
      else cell.style.color = 'rgba(237,230,208,.85)';
      grid.append(cell);
    });
  });
  return grid;
}
