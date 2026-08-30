// Graficos do dashboard (Chart.js). Paleta e tokens conforme a skill de dataviz:
// serie-1 azul para o patrimonio, verde/vermelho (status) para ciclos que bateram/nao
// bateram a meta, laranja para a linha de meta.

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function renderEquityChart(canvasId, equityCurve) {
  const ctx = document.getElementById(canvasId);
  if (!ctx || !equityCurve || !equityCurve.length) return;
  const labels = equityCurve.map(p => p[0]);
  const values = equityCurve.map(p => p[1]);

  new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Patrimonio (R$)",
        data: values,
        borderColor: cssVar("--series-1"),
        backgroundColor: cssVar("--series-1") + "22",
        borderWidth: 2,
        pointRadius: 0,
        fill: true,
        tension: 0.1,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (item) => `R$ ${item.parsed.y.toLocaleString("pt-BR", {minimumFractionDigits: 2})}`,
          },
        },
      },
      scales: {
        x: { ticks: { color: cssVar("--text-muted"), maxTicksLimit: 8 }, grid: { color: cssVar("--gridline") } },
        y: { ticks: { color: cssVar("--text-muted") }, grid: { color: cssVar("--gridline") } },
      },
    },
  });
}

function renderCyclesChart(canvasId, cycleReturnsPct, targetPct) {
  const ctx = document.getElementById(canvasId);
  if (!ctx || !cycleReturnsPct || !cycleReturnsPct.length) return;
  const good = cssVar("--good");
  const critical = cssVar("--critical");
  const colors = cycleReturnsPct.map(v => (v >= targetPct ? good : (v < 0 ? critical : cssVar("--series-1"))));

  new Chart(ctx, {
    type: "bar",
    data: {
      labels: cycleReturnsPct.map((_, i) => i),
      datasets: [
        {
          label: "Retorno do ciclo (30d)",
          data: cycleReturnsPct,
          backgroundColor: colors,
          borderRadius: 3,
          barPercentage: 1.0,
          categoryPercentage: 1.0,
        },
        {
          label: `Meta (${targetPct}%)`,
          data: cycleReturnsPct.map(() => targetPct),
          type: "line",
          borderColor: cssVar("--series-2"),
          borderWidth: 1.5,
          borderDash: [5, 4],
          pointRadius: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: { color: cssVar("--text-secondary"), boxWidth: 12 },
        },
        tooltip: {
          callbacks: { label: (item) => `${item.dataset.label}: ${item.parsed.y.toFixed(2)}%` },
        },
      },
      scales: {
        x: { display: false },
        y: {
          ticks: { color: cssVar("--text-muted"), callback: (v) => v + "%" },
          grid: { color: cssVar("--gridline") },
        },
      },
    },
  });
}
