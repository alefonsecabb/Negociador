// Homebroker fictício (homebroker.html): renderiza a carteira 100% local
// (localStorage, via js/hb_engine.js) — resumo, posições com ordem bracket ativa,
// ledger de trades fechados, curva de patrimônio e ciclos rolantes de 30d.
// Nada aqui fala com servidor; só lê params.json e quotes.json (publicados pelo
// GitHub Actions, sem autenticação) para marcar a mercado e simular as saídas.

let PARAMS = HB_FALLBACK_PARAMS;
let QUOTES = {};

function pnlCell(value, text) {
  const cls = (value ?? 0) >= 0 ? "pnl-pos" : "pnl-neg";
  return `<span class="${cls}">${text}</span>`;
}

function renderHbStats(m) {
  const row = document.getElementById("hb-stat-row");
  const hasCycles = m.cycles.n > 0;
  row.innerHTML = [
    statTile("Patrimonio", fmtBRL(m.equity), `Capital inicial: ${fmtBRL(m.capital_inicial)}`),
    statTile("Caixa disponivel", fmtBRL(m.cash)),
    statTile("Retorno total", fmtPct(m.retorno_total_pct), "", m.retorno_total_pct >= 0 ? "good" : "bad"),
    statTile("P&L realizado", fmtBRL(m.realized_pnl), "", m.realized_pnl >= 0 ? "good" : "bad"),
    statTile("P&L nao realizado", fmtBRL(m.unrealized_pnl), "", m.unrealized_pnl >= 0 ? "good" : "bad"),
    statTile("Posicoes abertas", m.n_open_positions),
    statTile("Trades fechados", m.n_trades),
    statTile("Taxa de acerto", m.n_trades ? fmtPct(m.win_rate_pct) : "—"),
    statTile("Profit factor", !m.n_trades ? "—" : (m.profit_factor === null ? "∞" : m.profit_factor.toFixed(2))),
    statTile("Drawdown maximo", hasCycles || m.equity_series.length > 1 ? fmtPct(m.max_drawdown_pct) : "—", "", "bad"),
    statTile("Custos totais", fmtBRL(m.total_costs)),
    statTile("IR total pago", fmtBRL(m.total_tax)),
  ].join("");
}

function renderHbPositions(positions, quotes, maxHoldingDays) {
  const tbody = document.querySelector("#hb-positions-table tbody");
  const emptyEl = document.getElementById("hb-positions-empty");
  if (!positions.length) {
    tbody.innerHTML = "";
    emptyEl.hidden = false;
    return;
  }
  emptyEl.hidden = true;
  tbody.innerHTML = positions.map(p => {
    const q = quotes[p.ticker];
    const price = q?.price ?? p.entry_price;
    const pnl = (price - p.entry_price) * p.qty;
    const pnlPct = (price / p.entry_price - 1) * 100;
    const distStop = p.stop_price ? (price / p.stop_price - 1) * 100 : null;
    const distTake = price ? (p.take_price / price - 1) * 100 : null;
    return `<tr>
      <td><strong>${p.ticker}</strong></td>
      <td>${p.entry_date}</td>
      <td class="num">R$ ${p.entry_price.toFixed(2)}</td>
      <td class="num">R$ ${price.toFixed(2)}</td>
      <td>
        <span class="badge badge-stop">STOP R$ ${p.stop_price.toFixed(2)}</span>
        <span class="badge badge-take">TAKE R$ ${p.take_price.toFixed(2)}</span>
      </td>
      <td class="num">${p.holding_days}/${maxHoldingDays}</td>
      <td class="num">${fmtPct(distStop)}</td>
      <td class="num">${fmtPct(distTake)}</td>
      <td class="num">${pnlCell(pnl, `${fmtBRL(pnl)} (${fmtPct(pnlPct)})`)}</td>
    </tr>`;
  }).join("");
}

function renderHbTrades(trades) {
  const tbody = document.querySelector("#hb-trades-table tbody");
  const emptyEl = document.getElementById("hb-trades-empty");
  if (!trades.length) {
    tbody.innerHTML = "";
    emptyEl.hidden = false;
    return;
  }
  emptyEl.hidden = true;
  const rows = [...trades].sort((a, b) => String(b.exit_date).localeCompare(String(a.exit_date)));
  tbody.innerHTML = rows.map(t => {
    const retPct = (t.exit_price / t.entry_price - 1) * 100;
    return `<tr>
      <td><strong>${t.ticker}</strong></td>
      <td>${t.entry_date}</td>
      <td>${t.exit_date}</td>
      <td class="num">R$ ${t.entry_price.toFixed(2)}</td>
      <td class="num">R$ ${t.exit_price.toFixed(2)}</td>
      <td class="num">${t.qty}</td>
      <td><span class="badge ${alertBadgeClass(t.exit_reason)}">${alertLabel(t.exit_reason)}</span></td>
      <td class="num">${pnlCell(t.gross_pnl, fmtBRL(t.gross_pnl))}</td>
      <td class="num">${fmtBRL(t.total_costs)}</td>
      <td class="num">${fmtBRL(t.tax_paid)}</td>
      <td class="num">${pnlCell(t.net_pnl, fmtBRL(t.net_pnl))}</td>
      <td class="num">${pnlCell(retPct, fmtPct(retPct))}</td>
    </tr>`;
  }).join("");
}

function renderHbCycleStats(m) {
  const row = document.getElementById("hb-cycles-stat-row");
  if (!m.cycles.n) {
    row.innerHTML = '<div class="empty-state">Sem histórico de patrimônio suficiente ainda (precisa de ~30 dias de cotações desde o primeiro trade).</div>';
    return;
  }
  const c = m.cycles;
  row.innerHTML = [
    statTile("Retorno medio/ciclo", fmtPct(c.mean_pct)),
    statTile("% de ciclos ≥ meta", fmtPct(c.pct_meta), `meta: ${m.meta_por_ciclo_pct}%`),
    statTile("% de ciclos negativos", fmtPct(c.pct_neg), "", "bad"),
    statTile("Pior ciclo", fmtPct(c.worst_pct), "", "bad"),
    statTile("Melhor ciclo", fmtPct(c.best_pct)),
  ].join("");
}

function wireActions() {
  document.getElementById("hb-export").onclick = () => {
    const blob = new Blob([hbExport()], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `homebroker-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
  };
  document.getElementById("hb-import").onclick = () => document.getElementById("hb-import-file").click();
  document.getElementById("hb-import-file").onchange = (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const r = new FileReader();
    r.onload = () => {
      try { hbImport(r.result); location.reload(); }
      catch (err) { window.alert("Importação falhou: " + err.message); }
    };
    r.readAsText(f);
  };
  document.getElementById("hb-reset").onclick = () => {
    if (window.confirm("Resetar a carteira do homebroker? Apaga todas as posições e trades registrados neste navegador.")) {
      hbResetState(PARAMS);
      location.reload();
    }
  };
}

async function main() {
  const [paramsData, quotesData] = await Promise.all([
    fetchJson("params.json"),
    fetchJson("quotes.json"),
  ]);
  PARAMS = paramsData || HB_FALLBACK_PARAMS;
  QUOTES = quotesData?.quotes || {};

  const state = hbMarkToMarket(hbGetState(PARAMS), QUOTES, PARAMS);
  const m = hbComputeMetrics(state, PARAMS, QUOTES);

  document.getElementById("last-updated").textContent = quotesData?.generated_at
    ? `cotacoes de: ${new Date(quotesData.generated_at).toLocaleString("pt-BR")}`
    : "sem cotacoes publicadas ainda";

  renderHbStats(m);
  renderHbPositions(state.positions, QUOTES, PARAMS.risk.max_holding_days);
  renderHbTrades(state.trades);
  renderHbCycleStats(m);
  if (m.equity_series.length) renderEquityChart("hb-equity-chart", m.equity_series);
  if (m.cycles.series_pct.length) renderCyclesChart("hb-cycles-chart", m.cycles.series_pct, m.meta_por_ciclo_pct);

  wireActions();
}

main().catch(err => {
  console.error(err);
  document.getElementById("last-updated").textContent = "erro ao carregar dados";
});
