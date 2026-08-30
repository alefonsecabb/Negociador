// Logica principal do dashboard: busca os JSONs publicados pelo GitHub Actions
// e renderiza carteira, alertas, posicoes, watchlist e os graficos de backtest.

const DATA_BASE = "data";

async function fetchJson(path) {
  const resp = await fetch(`${DATA_BASE}/${path}?_=${Date.now()}`);
  if (!resp.ok) return null;
  return resp.json();
}

function fmtBRL(v) {
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}
function fmtPct(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toFixed(digits)}%`;
}

// O sqlite grava created_at como "YYYY-MM-DD HH:MM:SS" (UTC, sem sufixo) via
// datetime('now') - alguns navegadores (Safari) nao parseiam esse formato
// corretamente com `new Date()`, entao normalizamos para ISO 8601 explicito.
function parseUtcTimestamp(s) {
  if (!s) return null;
  const iso = s.includes("T") ? s : s.replace(" ", "T") + "Z";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

function statTile(label, value, sub = "", cls = "") {
  return `<div class="stat-tile"><div class="label">${label}</div>
    <div class="value ${cls}">${value}</div>
    ${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
}

function alertBadgeClass(type) {
  if (type === "ENTRADA") return "badge-entrada";
  if (type === "STOP_LOSS") return "badge-stop";
  if (type === "TAKE_PROFIT") return "badge-take";
  return "badge-tempo";
}
function alertLabel(type) {
  return { ENTRADA: "ENTRADA", STOP_LOSS: "STOP-LOSS", TAKE_PROFIT: "TAKE-PROFIT", SAIDA_POR_TEMPO: "SAIDA POR TEMPO" }[type] || type;
}

async function confirmAlert(alertId, btn) {
  btn.disabled = true;
  btn.textContent = "Confirmando...";
  try {
    await ghAppendEvent(alertId, null, "confirm");
    btn.textContent = "Confirmado! (aguarde o workflow reconciliar)";
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Marquei como executado";
    alert(`Nao foi possivel confirmar pelo navegador:\n${err.message}\n\nAlternativa: rode localmente\npython -m negociador.cli.confirm_execution --alert-id ${alertId}`);
  }
}

async function ignoreAlert(alertId, btn) {
  if (!confirm(`Ignorar o alerta #${alertId}? Ele some da lista e o ticker fica livre para um sinal novo no proximo ciclo.`)) return;
  btn.disabled = true;
  btn.textContent = "Ignorando...";
  try {
    await ghAppendEvent(alertId, null, "ignore");
    btn.textContent = "Ignorado! (aguarde o workflow reconciliar)";
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Ignorar";
    alert(`Nao foi possivel ignorar pelo navegador:\n${err.message}\n\nAlternativa: rode localmente\npython -m negociador.cli.confirm_execution --alert-id ${alertId} --ignore`);
  }
}

function renderAlerts(alerts) {
  const container = document.getElementById("alerts-container");
  const pending = (alerts || []).filter(a => a.status === "novo");
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
            <button class="ghost-btn" onclick="ignoreAlert(${a.id}, this)">Ignorar</button>
            <button class="confirm-btn" onclick="confirmAlert(${a.id}, this)">Marquei como executado</button>
          </div>
        </div>
        ${extra.recomendacao ? `<div class="rec-text">${extra.recomendacao}</div>` : ""}
        <div class="rec-text" style="opacity:.7;">Criado em ${parseUtcTimestamp(a.created_at)?.toLocaleString("pt-BR") ?? a.created_at} · expira sozinho se ficar sem resposta por alguns dias.</div>
      </div>`;
  }).join("");
}

function renderPositions(positions) {
  const tbody = document.querySelector("#positions-table tbody");
  const emptyEl = document.getElementById("positions-empty");
  if (!positions || !positions.length) {
    tbody.innerHTML = "";
    emptyEl.hidden = false;
    return;
  }
  emptyEl.hidden = true;
  tbody.innerHTML = positions.map(p => {
    const pnlCls = p.unrealized_pnl >= 0 ? "pnl-pos" : "pnl-neg";
    return `<tr>
      <td><strong>${p.ticker}</strong></td>
      <td>${p.entry_date}</td>
      <td class="num">R$ ${p.entry_price.toFixed(2)}</td>
      <td class="num">R$ ${(p.current_price ?? p.entry_price).toFixed(2)}</td>
      <td class="num">R$ ${p.stop_price.toFixed(2)}</td>
      <td class="num">R$ ${p.take_price.toFixed(2)}</td>
      <td class="num">${p.holding_days}</td>
      <td class="num ${pnlCls}">${fmtBRL(p.unrealized_pnl ?? 0)} (${fmtPct(p.unrealized_pnl_pct ?? 0)})</td>
    </tr>`;
  }).join("");
}

function renderWatchlist(universeTickers, alerts, positions) {
  const tbody = document.querySelector("#watchlist-table tbody");
  const positionTickers = new Set((positions || []).map(p => p.ticker));
  const alertTickers = new Map((alerts || []).filter(a => a.status === "novo").map(a => [a.ticker, a.alert_type]));

  const rows = (universeTickers || []).map(t => {
    let status = "monitorando";
    let cls = "";
    if (positionTickers.has(t)) { status = "EM POSICAO"; cls = "badge-take"; }
    else if (alertTickers.has(t)) { status = `ALERTA: ${alertLabel(alertTickers.get(t))}`; cls = "badge-entrada"; }
    return { t, status, cls };
  });
  // prioriza quem tem posicao/alerta no topo
  rows.sort((a, b) => (b.cls ? 1 : 0) - (a.cls ? 1 : 0) || a.t.localeCompare(b.t));

  tbody.innerHTML = rows.map(r => `<tr><td>${r.t}</td><td>${r.cls ? `<span class="badge ${r.cls}">${r.status}</span>` : r.status}</td></tr>`).join("");
}

function renderPortfolioStats(portfolio) {
  const row = document.getElementById("stat-row");
  const retornoCls = portfolio.retorno_total_pct >= 0 ? "good" : "bad";
  row.innerHTML = [
    statTile("Patrimonio", fmtBRL(portfolio.equity), `Capital inicial: ${fmtBRL(portfolio.capital_inicial)}`),
    statTile("Caixa disponivel", fmtBRL(portfolio.cash)),
    statTile("Retorno total", fmtPct(portfolio.retorno_total_pct), "", retornoCls),
    statTile("Posicoes abertas", (portfolio.positions || []).length),
    statTile("Trades fechados", portfolio.n_trades_fechados ?? 0),
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
  const [portfolio, alertsData, backtestData, universeData] = await Promise.all([
    fetchJson("portfolio.json"),
    fetchJson("alerts.json"),
    fetchJson("backtest.json"),
    fetchJson("universe.json"),
  ]);

  const genAt = portfolio?.generated_at || alertsData?.generated_at;
  document.getElementById("last-updated").textContent = genAt
    ? `ultima atualizacao: ${new Date(genAt).toLocaleString("pt-BR")}`
    : "sem dados publicados ainda";

  if (portfolio) renderPortfolioStats(portfolio);
  const alerts = alertsData?.alerts || [];
  renderAlerts(alerts);
  renderPositions(portfolio?.positions);
  renderWatchlist(universeData?.tickers, alerts, portfolio?.positions);

  const backtestReport = backtestData?.backtest;
  renderBacktestStats(backtestReport, backtestData?.walk_forward);
  if (backtestReport?.series) {
    renderEquityChart("equity-chart", backtestReport.series.equity_curve);
    renderCyclesChart("cycles-chart", backtestReport.series.cycle_returns_pct, backtestReport.meta_por_ciclo_pct);
  }

  // configuracao do token do GitHub (confirmar execucao pelo navegador)
  const tokenInput = document.getElementById("gh-token-input");
  const tokenStatus = document.getElementById("gh-token-status");
  const existing = ghGetToken();
  if (existing) tokenStatus.textContent = "token salvo neste navegador.";
  document.getElementById("gh-token-save").onclick = () => {
    ghSetToken(tokenInput.value.trim());
    tokenInput.value = "";
    tokenStatus.textContent = "token salvo neste navegador.";
  };
  document.getElementById("gh-token-clear").onclick = () => {
    ghSetToken("");
    tokenStatus.textContent = "token removido.";
  };
}

main().catch(err => {
  console.error(err);
  document.getElementById("last-updated").textContent = "erro ao carregar dados";
});
