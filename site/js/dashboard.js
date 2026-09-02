// Dashboard (index.html): alertas do dia, watchlist e performance do backtest.
// O "Executar" registra a compra na carteira do homebroker, que é 100% local
// (localStorage, via js/hb_engine.js) — sem token, sem workflow. A carteira
// completa (posições, caixa, trades, P&L, curva de patrimônio) fica em
// homebroker.html.
//
// Helpers compartilhados em js/common.js; motor da carteira em js/hb_engine.js.

let PARAMS = HB_FALLBACK_PARAMS;
let QUOTES = {};
let LAST_ALERTS = [];
const ALERTS_BY_ID = {};

function pendingEntryAlerts(alerts) {
  const state = hbGetState(PARAMS);
  const held = new Set(state.positions.map(p => p.ticker));
  return (alerts || []).filter(a =>
    a.status === "novo" &&
    a.alert_type === "ENTRADA" &&
    !state.executed_alert_ids.includes(a.id) &&
    !state.dismissed_alert_ids.includes(a.id) &&
    !held.has(a.ticker)
  );
}

function renderAlerts(alerts) {
  LAST_ALERTS = alerts || LAST_ALERTS;
  const container = document.getElementById("alerts-container");
  const pending = pendingEntryAlerts(LAST_ALERTS);
  for (const a of pending) ALERTS_BY_ID[a.id] = a;

  if (!pending.length) {
    container.innerHTML = '<div class="empty-state">Nenhum alerta pendente.</div>';
    return;
  }
  container.innerHTML = pending.map(a => {
    const extra = a.extra_json ? JSON.parse(a.extra_json) : {};
    return `
      <div class="card" style="margin-bottom:8px;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
          <div>
            <span class="badge ${alertBadgeClass(a.alert_type)}">${alertLabel(a.alert_type)}</span>
            <strong style="margin-left:8px;">${a.ticker}</strong>
            <span style="color:var(--text-muted); margin-left:8px;">ref. R$ ${a.reference_price?.toFixed(2)}</span>
          </div>
          <div style="display:flex; align-items:center; gap:8px;">
            <strong>Limite: R$ ${a.limit_price?.toFixed(2)}</strong>
            <span id="alert-actions-${a.id}" style="display:flex; align-items:center; gap:8px;">
              <button class="ghost-btn" onclick="ignoreAlert(${a.id})">Ignorar</button>
              <button class="confirm-btn" onclick="openExecForm(${a.id})">Executar</button>
            </span>
          </div>
        </div>
        ${extra.recomendacao ? `<div class="rec-text">${extra.recomendacao}</div>` : ""}
        <div class="rec-text" style="opacity:.7;">Criado em ${parseUtcTimestamp(a.created_at)?.toLocaleString("pt-BR") ?? a.created_at} · expira sozinho se ficar sem resposta por alguns dias.</div>
      </div>`;
  }).join("");
}

function ignoreAlert(alertId) {
  const state = hbGetState(PARAMS);
  if (!state.dismissed_alert_ids.includes(alertId)) state.dismissed_alert_ids.push(alertId);
  hbSaveState(state);
  renderAlerts();
  renderLiveSummary();
}

function openExecForm(alertId) {
  const a = ALERTS_BY_ID[alertId];
  const slot = document.getElementById(`alert-actions-${alertId}`);
  if (!a || !slot) return;
  const state = hbGetState(PARAMS);
  const suggestedQty = hbSharesToBuy(
    hbEquity(state, QUOTES), state.cash, a.limit_price, a.stop_price, PARAMS.position_sizing,
  );
  slot.innerHTML = `
    <label style="font-size:12px; color:var(--text-secondary);">Preço
      <input id="exec-price-${alertId}" type="number" step="0.01" value="${a.limit_price.toFixed(2)}"
        style="width:78px; font-size:12px; padding:4px 6px; border:1px solid var(--border); border-radius:6px; background:var(--surface-2); color:var(--text-primary);" />
    </label>
    <label style="font-size:12px; color:var(--text-secondary);">Qtd
      <input id="exec-qty-${alertId}" type="number" step="1" min="1" value="${suggestedQty}"
        style="width:66px; font-size:12px; padding:4px 6px; border:1px solid var(--border); border-radius:6px; background:var(--surface-2); color:var(--text-primary);" />
    </label>
    <button class="confirm-btn" onclick="submitExec(${alertId})">Confirmar</button>
    <button class="ghost-btn" onclick="renderAlerts()">Cancelar</button>`;
}

function submitExec(alertId) {
  const a = ALERTS_BY_ID[alertId];
  if (!a) return;
  const price = parseFloat(document.getElementById(`exec-price-${alertId}`).value);
  const qty = parseInt(document.getElementById(`exec-qty-${alertId}`).value, 10);
  const state = hbGetState(PARAMS);
  const res = hbOpenPosition(state, a, PARAMS, { entryPrice: price, qty, quotes: QUOTES });
  if (!res.ok) { window.alert(res.error); return; }
  renderAlerts();
  renderLiveSummary();
}

function renderWatchlist(universeTickers, alerts) {
  const tbody = document.querySelector("#watchlist-table tbody");
  const held = new Set(hbGetState(PARAMS).positions.map(p => p.ticker));
  const alertTickers = new Map(pendingEntryAlerts(alerts).map(a => [a.ticker, a.alert_type]));

  const rows = (universeTickers || []).map(t => {
    let status = "monitorando";
    let cls = "";
    if (held.has(t)) { status = "EM POSICAO"; cls = "badge-take"; }
    else if (alertTickers.has(t)) { status = `ALERTA: ${alertLabel(alertTickers.get(t))}`; cls = "badge-entrada"; }
    return { t, status, cls };
  });
  rows.sort((a, b) => (b.cls ? 1 : 0) - (a.cls ? 1 : 0) || a.t.localeCompare(b.t));
  tbody.innerHTML = rows.map(r => `<tr><td>${r.t}</td><td>${r.cls ? `<span class="badge ${r.cls}">${r.status}</span>` : r.status}</td></tr>`).join("");
}

function renderLiveSummary() {
  const row = document.getElementById("stat-row");
  const state = hbGetState(PARAMS);
  const m = hbComputeMetrics(state, PARAMS, QUOTES);
  const nPending = pendingEntryAlerts(LAST_ALERTS).length;
  const retornoCls = m.retorno_total_pct >= 0 ? "good" : "bad";
  row.innerHTML = [
    statTile("Posicoes abertas", `<a href="homebroker.html" style="color:inherit;">${m.n_open_positions}</a>`, "detalhe no homebroker"),
    statTile("Alertas pendentes", nPending),
    statTile("Retorno total (ao vivo)", fmtPct(m.retorno_total_pct), "carteira ficticia local", retornoCls),
  ].join("");
}

function renderBacktestStats(backtestReport, walkForward) {
  const row = document.getElementById("backtest-stat-row");
  if (!backtestReport) {
    row.innerHTML = '<div class="empty-state">Ainda sem relatorio de backtest publicado.</div>';
    return;
  }
  const c = backtestReport.ciclos_rolantes_30d;
  const tiles = [
    statTile("Retorno medio/ciclo", fmtPct(c.retorno_medio_pct)),
    statTile("% de ciclos ≥ meta", fmtPct(c.pct_janelas_atingiu_meta), `meta: ${backtestReport.meta_por_ciclo_pct}%`),
    statTile("% de ciclos negativos", fmtPct(c.pct_janelas_negativas), "", "bad"),
    statTile("Drawdown maximo", fmtPct(backtestReport.risco.drawdown_maximo_pct), "", "bad"),
    statTile("Taxa de acerto", fmtPct(backtestReport.operacoes.taxa_de_acerto_pct)),
  ];
  if (walkForward && walkForward.holdout) {
    const hc = walkForward.holdout.report.ciclos_rolantes_30d;
    tiles.push(statTile("% ciclos ≥ meta (holdout OOS)", fmtPct(hc.pct_janelas_atingiu_meta), "nunca tocado na calibracao"));
  }
  row.innerHTML = tiles.join("");
}

async function main() {
  const [alertsData, backtestData, universeData, paramsData, quotesData] = await Promise.all([
    fetchJson("alerts.json"),
    fetchJson("backtest.json"),
    fetchJson("universe.json"),
    fetchJson("params.json"),
    fetchJson("quotes.json"),
  ]);

  PARAMS = paramsData || HB_FALLBACK_PARAMS;
  QUOTES = quotesData?.quotes || {};
  LAST_ALERTS = alertsData?.alerts || [];

  // roda a simulação local (saídas por stop/take/tempo, IR, ponto de patrimônio)
  // com as cotações atuais — assim ela avança mesmo se você só abrir o dashboard
  hbMarkToMarket(hbGetState(PARAMS), QUOTES, PARAMS);

  const genAt = quotesData?.generated_at || alertsData?.generated_at;
  document.getElementById("last-updated").textContent = genAt
    ? `ultima atualizacao: ${new Date(genAt).toLocaleString("pt-BR")}`
    : "sem dados publicados ainda";

  renderLiveSummary();
  renderAlerts();
  renderWatchlist(universeData?.tickers, LAST_ALERTS);

  const backtestReport = backtestData?.backtest;
  renderBacktestStats(backtestReport, backtestData?.walk_forward);
  if (backtestReport?.series) {
    renderEquityChart("equity-chart", backtestReport.series.equity_curve);
    renderCyclesChart("cycles-chart", backtestReport.series.cycle_returns_pct, backtestReport.meta_por_ciclo_pct);
  }
}

main().catch(err => {
  console.error(err);
  document.getElementById("last-updated").textContent = "erro ao carregar dados";
});
