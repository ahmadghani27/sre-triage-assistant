/* Chart.js rendering logic untuk dasbor operasional.
   Mengonsumsi GET /api/analytics/charts (JSON) — tidak ada akses DB langsung
   dari sisi browser (lihat ARCHITECTURE.md §2: static/js/charts.js). */

(function () {
  'use strict';

  const CHARTS_URL = '/api/analytics/charts';

  const GRID = 'rgba(148, 163, 184, 0.10)';
  const TICK = 'rgba(148, 163, 184, 0.85)';
  const TOOLTIP_BG = '#151f29';
  const FONT_FAMILY = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";

  Chart.defaults.font.family = FONT_FAMILY;
  Chart.defaults.font.size = 10;
  Chart.defaults.color = TICK;
  Chart.defaults.borderColor = GRID;

  const CATEGORY_COLORS = ['#38bdf8', '#34d399', '#facc15', '#f43f5e', '#a78bfa', '#fb923c'];
  const SEVERITY_COLORS = {
    SEV1: '#f43f5e',
    SEV2: '#fb923c',
    SEV3: '#facc15',
    SEV4: '#38bdf8',
  };

  const state = {
    category: null,
    severity: null,
    trend: null,
  };

  /* ---------- KPI + helper render ---------- */

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function renderKpis(data) {
    setText('kpi-total', data.summary ? Number(data.summary.total_triages || 0).toLocaleString('id-ID') : '0');
    setText('kpi-runbooks', data.summary ? Number(data.summary.runbook_total || 0).toLocaleString('id-ID') : '0');

    const rate = data.summary && typeof data.summary.fallback_rate === 'number' ? data.summary.fallback_rate : 0;
    setText('kpi-fallback', (rate * 100).toFixed(1) + '%');

    const cats = data.category_distribution || {};
    const topKey = Object.keys(cats)[0];
    setText('kpi-top-cat', topKey ? topKey.toUpperCase() : '—');

    const now = new Date();
    setText('last-updated', now.toLocaleTimeString('id-ID', { hour12: false }));
  }

  /* ---------- Grafik 1: Distribusi Kategori (bar horizontal) ---------- */

  function renderCategoryChart(data) {
    const ctx = document.getElementById('chart-category');
    if (!ctx) return;
    if (state.category) state.category.destroy();

    const entries = Object.entries(data.category_distribution || {});
    const labels = entries.map(([k]) => k);
    const values = entries.map(([, v]) => v);

    state.category = new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Jumlah',
          data: values,
          backgroundColor: labels.map((_, i) => CATEGORY_COLORS[i % CATEGORY_COLORS.length] + 'cc'),
          borderColor: labels.map((_, i) => CATEGORY_COLORS[i % CATEGORY_COLORS.length]),
          borderWidth: 1,
          borderRadius: 4,
          barThickness: 22,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: TOOLTIP_BG,
            borderColor: GRID,
            borderWidth: 1,
            padding: 10,
            displayColors: false,
          },
        },
        scales: {
          x: {
            grid: { color: GRID },
            ticks: { precision: 0 },
            title: { display: true, text: 'jumlah insiden', font: { size: 9 } },
          },
          y: {
            grid: { display: false },
            ticks: { font: { size: 11 } },
          },
        },
      },
    });
  }

  /* ---------- Grafik 2: Proporsi Severitas (doughnut) ---------- */

  function renderSeverityChart(data) {
    const ctx = document.getElementById('chart-severity');
    if (!ctx) return;
    if (state.severity) state.severity.destroy();

    const raw = data.severity_distribution || {};
    const labels = Object.keys(raw);
    const values = Object.values(raw);

    state.severity = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: labels.map((l) => (SEVERITY_COLORS[l] || '#64748b') + 'dd'),
          borderColor: '#111820',
          borderWidth: 2,
          hoverOffset: 6,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '62%',
        plugins: {
          legend: {
            position: 'right',
            labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: 'rectRounded' },
          },
          tooltip: {
            backgroundColor: TOOLTIP_BG,
            borderColor: GRID,
            borderWidth: 1,
            padding: 10,
            callbacks: {
              label(ctx) {
                const total = ctx.dataset.data.reduce((a, b) => a + Number(b || 0), 0);
                const pct = total ? ((Number(ctx.raw || 0) / total) * 100).toFixed(1) : '0.0';
                return ` ${ctx.label}: ${ctx.raw} (${pct}%)`;
              },
            },
          },
        },
      },
    });
  }

  /* ---------- Grafik 3: Tren Frekuensi (line) ---------- */

  function renderTrendChart(data) {
    const ctx = document.getElementById('chart-trend');
    if (!ctx) return;
    if (state.trend) state.trend.destroy();

    const trend = Array.isArray(data.incident_trend) ? data.incident_trend : [];
    const labels = trend.map((r) => r.day || '');
    const values = trend.map((r) => Number(r.total || 0));

    state.trend = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Insiden',
          data: values,
          borderColor: '#38bdf8',
          backgroundColor: 'rgba(56, 189, 248, 0.12)',
          fill: true,
          tension: 0.35,
          pointRadius: 2.5,
          pointHoverRadius: 5,
          pointBackgroundColor: '#0b0f14',
          pointBorderColor: '#38bdf8',
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: TOOLTIP_BG,
            borderColor: GRID,
            borderWidth: 1,
            padding: 10,
            displayColors: false,
          },
        },
        scales: {
          x: {
            grid: { color: GRID },
            ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10, font: { size: 9 } },
          },
          y: {
            beginAtZero: true,
            grid: { color: GRID },
            ticks: { precision: 0 },
            title: { display: true, text: 'jumlah insiden / hari', font: { size: 9 } },
          },
        },
      },
    });
  }

  /* ---------- Orchestration ---------- */

  async function loadCharts() {
    try {
      const res = await fetch(CHARTS_URL, {
        headers: { 'Accept': 'application/json' },
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();

      renderKpis(data);
      renderCategoryChart(data);
      renderSeverityChart(data);
      renderTrendChart(data);
    } catch (err) {
      console.error('[charts] gagal memuat data analitik:', err);
      setText('last-updated', 'gagal memuat');
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (!document.getElementById('chart-category')) return;
    loadCharts();

    const btn = document.getElementById('refresh-charts');
    if (btn) btn.addEventListener('click', loadCharts);
  });
})();