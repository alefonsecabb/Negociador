// Homebroker fictício — motor 100% no navegador (localStorage). Porta a lógica
// do modelo Python (position sizing, custos B3, IR mensal, breakeven, check_exit,
// preço de saída no gap, métricas) para o JS, para o dashboard não precisar de
// backend nem de token do GitHub. Estado compartilhado entre index.html e
// homebroker.html (mesma origem).

const HB_KEY = "negociador_homebroker_v1";

// Fallback usado só se site/data/params.json ainda não foi publicado.
// Espelha config/strategy_params.yaml.
const HB_FALLBACK_PARAMS = {
  capital_inicial: 100000,
  risk: { atr_stop_multiple: 3.0, reward_risk_ratio: 2.5, breakeven_after_r: 1.0, max_holding_days: 20 },
  position_sizing: { risk_per_trade_pct: 0.02, max_position_pct: 0.10, max_open_positions: 12, min_cash_reserve_pct: 0.10 },
  costs: { b3_emolument_pct: 0.0003, brokerage_fee_brl: 0.0, income_tax_pct: 0.15, income_tax_exempt_sales_brl: 20000.0 },
  target_monthly_return_pct: 0.05,
};

// ---------- estado / persistência ----------

function hbDefaultState(capitalInicial) {
  const cap = capitalInicial || 100000;
  return {
    version: 1,
    created_at: new Date().toISOString(),
    capital_inicial: cap,
    cash: cap,
    positions: [],       // {ticker, entry_date, entry_price, qty, stop_price, take_price, atr_at_entry, high_since_entry, holding_days, last_eval_date}
    trades: [],          // {ticker, entry_date, exit_date, entry_price, exit_price, qty, exit_reason, gross_pnl, total_costs, tax_paid, net_pnl}
    equity_history: [],   // {date, equity, cash}
    tax: { loss_carryforward: 0, current_month: null, month_sales_total: 0, month_net_profit: 0 },
    tax_history: [],
    executed_alert_ids: [],
    dismissed_alert_ids: [],
  };
}

function hbLoadState() {
  try {
    const raw = localStorage.getItem(HB_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function hbSaveState(s) {
  try { localStorage.setItem(HB_KEY, JSON.stringify(s)); return true; } catch { return false; }
}

function hbGetState(params) {
  return hbLoadState() || hbDefaultState(params && params.capital_inicial);
}

function hbResetState(params) {
  const s = hbDefaultState(params && params.capital_inicial);
  hbSaveState(s);
  return s;
}

function hbExport() {
  return JSON.stringify(hbLoadState() || hbDefaultState(), null, 2);
}

function hbImport(text) {
  const s = JSON.parse(text);
  if (!s || typeof s !== "object" || !Array.isArray(s.positions) || !Array.isArray(s.trades)) {
    throw new Error("JSON de carteira invalido");
  }
  hbSaveState(s);
  return s;
}

// ---------- primitivas do modelo (portadas do Python) ----------

function hbOrderCost(tradeValue, costs) {
  return tradeValue * costs.b3_emolument_pct + costs.brokerage_fee_brl;
}

// dias uteis em (fromISO, toISO]  (aproxima o Python _holding_days, que conta
// pregoes reais; ignora feriados, aceitavel para a simulacao no navegador)
function hbBusinessDaysBetween(fromISO, toISO) {
  const from = new Date(fromISO + "T00:00:00Z");
  const to = new Date(toISO + "T00:00:00Z");
  if (!(to > from)) return 0;
  let count = 0;
  const d = new Date(from);
  d.setUTCDate(d.getUTCDate() + 1);
  while (d <= to) {
    const wd = d.getUTCDay();
    if (wd !== 0 && wd !== 6) count++;
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return count;
}

// porta de strategy.position_sizing.shares_to_buy (lot_size = 1)
function hbSharesToBuy(equity, cashAvailable, entryPrice, stopPrice, sizing) {
  if (entryPrice <= stopPrice) return 0;
  const qtyByRisk = (equity * sizing.risk_per_trade_pct) / (entryPrice - stopPrice);
  const qtyByAlloc = (equity * sizing.max_position_pct) / entryPrice;
  const usableCash = Math.max(cashAvailable - equity * sizing.min_cash_reserve_pct, 0);
  const qtyByCash = usableCash / entryPrice;
  return Math.max(Math.floor(Math.min(qtyByRisk, qtyByAlloc, qtyByCash)), 0);
}

// porta de strategy.rules.apply_breakeven
function hbApplyBreakeven(entryPrice, currentStop, highSinceEntry, atrAtEntry, risk) {
  if (risk.breakeven_after_r <= 0) return currentStop;
  const initialRisk = risk.atr_stop_multiple * atrAtEntry;
  if (initialRisk <= 0) return currentStop;
  const profitInR = (highSinceEntry - entryPrice) / initialRisk;
  if (profitInR >= risk.breakeven_after_r && currentStop < entryPrice) return entryPrice;
  return currentStop;
}

// porta de strategy.rules.check_exit (stop tem prioridade no mesmo candle)
function hbCheckExit(bar, stopPrice, takePrice, holdingDays, maxHoldingDays) {
  if (bar.low <= stopPrice) return "STOP_LOSS";
  if (bar.high >= takePrice) return "TAKE_PROFIT";
  if (holdingDays >= maxHoldingDays) return "SAIDA_POR_TEMPO";
  return null;
}

// porta de strategy.rules.fill_price_for_level
function hbFillPrice(bar, level, side) {
  if (side === "stop") return bar.open <= level ? bar.open : level;
  return bar.open >= level ? bar.open : level; // "take"
}

// ---------- IR mensal (porta de backtest.costs.TaxTracker) ----------

function hbMonthKey(dateISO) { return String(dateISO).slice(0, 7); }

function hbCloseTaxMonth(tax, taxHistory, costs) {
  let taxDue = 0;
  const net = tax.month_net_profit;
  const sales = tax.month_sales_total;
  if (net < 0) {
    tax.loss_carryforward += -net;
  } else if (sales >= costs.income_tax_exempt_sales_brl) {
    const taxable = Math.max(net - tax.loss_carryforward, 0);
    tax.loss_carryforward -= Math.min(net, tax.loss_carryforward);
    taxDue = taxable * costs.income_tax_pct;
  }
  taxHistory.push({
    year_month: tax.current_month, sales_total: sales, net_profit: net,
    tax_due: taxDue, loss_carryforward_after: tax.loss_carryforward,
    exempt: sales < costs.income_tax_exempt_sales_brl,
  });
  return taxDue;
}

function hbResetTaxMonth(tax, monthKey) {
  tax.current_month = monthKey;
  tax.month_sales_total = 0;
  tax.month_net_profit = 0;
}

function hbTaxRecordSale(tax, taxHistory, dateISO, saleValue, tradePnl, costs) {
  const monthKey = hbMonthKey(dateISO);
  let taxDue = 0;
  if (tax.current_month === null) {
    hbResetTaxMonth(tax, monthKey);
  } else if (monthKey !== tax.current_month) {
    taxDue = hbCloseTaxMonth(tax, taxHistory, costs);
    hbResetTaxMonth(tax, monthKey);
  }
  tax.month_sales_total += saleValue;
  tax.month_net_profit += tradePnl;
  return taxDue;
}

function hbTaxRollToDate(tax, taxHistory, dateISO, costs) {
  if (tax.current_month === null) return 0;
  if (hbMonthKey(dateISO) === tax.current_month) return 0;
  const taxDue = hbCloseTaxMonth(tax, taxHistory, costs);
  tax.current_month = null;
  tax.month_sales_total = 0;
  tax.month_net_profit = 0;
  return taxDue;
}

// ---------- operações ----------

function hbEquity(state, quotes) {
  let eq = state.cash;
  for (const p of state.positions) {
    const q = quotes && quotes[p.ticker];
    eq += (q && q.price ? q.price : p.entry_price) * p.qty;
  }
  return eq;
}

function hbOpenPosition(state, alert, params, opts) {
  opts = opts || {};
  const ticker = alert.ticker;
  if (state.positions.some(p => p.ticker === ticker)) {
    return { ok: false, error: `Ja ha posicao aberta em ${ticker}.` };
  }
  if (state.positions.length >= params.position_sizing.max_open_positions) {
    return { ok: false, error: "Limite de posicoes abertas atingido." };
  }
  const entry = Number(opts.entryPrice) > 0 ? Number(opts.entryPrice) : alert.limit_price;
  const stop = alert.stop_price;
  const take = alert.take_price;
  const extra = alert.extra_json ? JSON.parse(alert.extra_json) : {};
  const atrAtEntry = extra.atr || (entry - stop) / params.risk.atr_stop_multiple;

  let qty = Number(opts.qty);
  if (!(qty > 0)) {
    qty = hbSharesToBuy(hbEquity(state, opts.quotes || {}), state.cash, entry, stop, params.position_sizing);
  }
  qty = Math.floor(qty);
  if (!(qty > 0)) return { ok: false, error: "Quantidade calculada foi zero (caixa insuficiente ou risco mal dimensionado)." };

  const buyValue = entry * qty;
  const buyCost = hbOrderCost(buyValue, params.costs);
  if (buyValue + buyCost > state.cash) return { ok: false, error: "Caixa insuficiente para essa quantidade." };

  state.cash -= buyValue + buyCost;
  state.positions.push({
    ticker, entry_date: opts.entryDate || new Date().toISOString().slice(0, 10),
    entry_price: entry, qty, stop_price: stop, take_price: take,
    atr_at_entry: atrAtEntry, high_since_entry: entry, holding_days: 0, last_eval_date: null,
  });
  if (!state.executed_alert_ids.includes(alert.id)) state.executed_alert_ids.push(alert.id);
  hbSaveState(state);
  return { ok: true, qty, entry };
}

function hbClosePosition(state, pos, exitDate, exitPrice, reason, costs) {
  const saleValue = exitPrice * pos.qty;
  const buyCost = hbOrderCost(pos.entry_price * pos.qty, costs);
  const sellCost = hbOrderCost(saleValue, costs);
  const grossPnl = (exitPrice - pos.entry_price) * pos.qty;
  const netPnl = grossPnl - buyCost - sellCost;
  const taxDue = hbTaxRecordSale(state.tax, state.tax_history, exitDate, saleValue, netPnl, costs);
  state.cash += saleValue - sellCost - taxDue;
  state.trades.push({
    ticker: pos.ticker, entry_date: pos.entry_date, exit_date: exitDate,
    entry_price: pos.entry_price, exit_price: exitPrice, qty: pos.qty, exit_reason: reason,
    gross_pnl: grossPnl, total_costs: buyCost + sellCost, tax_paid: taxDue, net_pnl: netPnl,
  });
}

// Marca a mercado com as cotações publicadas: atualiza breakeven/holding_days,
// dispara stop/take/tempo, fecha o mês de IR quando vira o mês e grava um ponto
// diário de patrimônio. Idempotente por data de cotação (last_eval_date).
function hbMarkToMarket(state, quotes, params) {
  const risk = params.risk;
  const costs = params.costs;

  let asOf = null;
  for (const t in quotes) {
    const d = quotes[t] && quotes[t].date;
    if (d && (!asOf || d > asOf)) asOf = d;
  }

  let changed = false;

  for (const pos of [...state.positions]) {
    const q = quotes[pos.ticker];
    if (!q || !q.date) continue;
    if (q.date <= pos.entry_date) continue;                       // saída só a partir do dia seguinte à entrada (como no backtest)
    if (pos.last_eval_date && q.date <= pos.last_eval_date) continue;

    const bar = { open: q.open, high: q.high, low: q.low, close: q.price };
    const holdingDays = hbBusinessDaysBetween(pos.entry_date, q.date);
    const highSinceEntry = Math.max(pos.high_since_entry, q.high);
    const newStop = hbApplyBreakeven(pos.entry_price, pos.stop_price, highSinceEntry, pos.atr_at_entry, risk);

    pos.high_since_entry = highSinceEntry;
    pos.stop_price = newStop;
    pos.holding_days = holdingDays;
    pos.last_eval_date = q.date;
    changed = true;

    const reason = hbCheckExit(bar, newStop, pos.take_price, holdingDays, risk.max_holding_days);
    if (reason) {
      let exitPrice;
      if (reason === "STOP_LOSS") exitPrice = hbFillPrice(bar, newStop, "stop");
      else if (reason === "TAKE_PROFIT") exitPrice = hbFillPrice(bar, pos.take_price, "take");
      else exitPrice = bar.close;
      hbClosePosition(state, pos, q.date, exitPrice, reason, costs);
      state.positions = state.positions.filter(p => p !== pos);
    }
  }

  if (asOf) {
    const rolled = hbTaxRollToDate(state.tax, state.tax_history, asOf, costs);
    if (rolled) { state.cash -= rolled; changed = true; }

    const eq = hbEquity(state, quotes);
    const last = state.equity_history[state.equity_history.length - 1];
    if (last && last.date === asOf) {
      last.equity = eq; last.cash = state.cash;
    } else if (!last || asOf > last.date) {
      state.equity_history.push({ date: asOf, equity: eq, cash: state.cash });
      changed = true;
    }
  }

  if (changed) hbSaveState(state);
  return state;
}

// ---------- métricas (porta de backtest.metrics) ----------

function hbMaxDrawdown(equityValues) {
  if (!equityValues.length) return 0;
  let peak = -Infinity, mdd = 0;
  for (const v of equityValues) {
    if (v > peak) peak = v;
    const dd = v / peak - 1;
    if (dd < mdd) mdd = dd;
  }
  return mdd;
}

function hbWinRate(trades) {
  if (!trades.length) return 0;
  return trades.filter(t => t.net_pnl > 0).length / trades.length;
}

function hbProfitFactor(trades) {
  const wins = trades.filter(t => t.net_pnl > 0).reduce((a, t) => a + t.net_pnl, 0);
  const losses = trades.filter(t => t.net_pnl < 0).reduce((a, t) => a - t.net_pnl, 0);
  if (losses === 0) return wins > 0 ? null : 0;  // null = "sem perdas" (infinito)
  return wins / losses;
}

function hbRollingCycleReturns(history, cycleDays) {
  if (history.length < 2) return [];
  const ts = history.map(h => new Date(h.date + "T00:00:00Z").getTime());
  const first = ts[0];
  const out = [];
  for (let i = 0; i < history.length; i++) {
    const pastTs = ts[i] - cycleDays * 86400000;
    if (pastTs < first) continue;
    let pastEq = null;
    for (let j = 0; j < history.length; j++) {
      if (ts[j] <= pastTs) pastEq = history[j].equity; else break;
    }
    if (pastEq == null || pastEq <= 0) continue;
    out.push(history[i].equity / pastEq - 1);
  }
  return out;
}

function hbComputeMetrics(state, params, quotes) {
  quotes = quotes || {};
  const cap = state.capital_inicial || 100000;
  const equity = hbEquity(state, quotes);
  const realized = state.trades.reduce((a, t) => a + t.net_pnl, 0);
  let unrealized = 0;
  for (const p of state.positions) {
    const q = quotes[p.ticker];
    unrealized += ((q && q.price ? q.price : p.entry_price) - p.entry_price) * p.qty;
  }
  const cycles = hbRollingCycleReturns(state.equity_history, 30);
  const target = params.target_monthly_return_pct;
  const mean = a => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);

  return {
    equity, cash: state.cash, capital_inicial: cap,
    retorno_total_pct: (equity / cap - 1) * 100,
    realized_pnl: realized, unrealized_pnl: unrealized,
    n_open_positions: state.positions.length, n_trades: state.trades.length,
    win_rate_pct: hbWinRate(state.trades) * 100,
    profit_factor: hbProfitFactor(state.trades),
    max_drawdown_pct: hbMaxDrawdown(state.equity_history.map(h => h.equity)) * 100,
    total_costs: state.trades.reduce((a, t) => a + t.total_costs, 0),
    total_tax: state.trades.reduce((a, t) => a + t.tax_paid, 0),
    meta_por_ciclo_pct: target * 100,
    cycles: {
      n: cycles.length,
      mean_pct: cycles.length ? mean(cycles) * 100 : null,
      pct_meta: cycles.length ? (cycles.filter(v => v >= target).length / cycles.length) * 100 : null,
      pct_neg: cycles.length ? (cycles.filter(v => v < 0).length / cycles.length) * 100 : null,
      worst_pct: cycles.length ? Math.min(...cycles) * 100 : null,
      best_pct: cycles.length ? Math.max(...cycles) * 100 : null,
      series_pct: cycles.map(v => v * 100),
    },
    equity_series: state.equity_history.map(h => [h.date, h.equity]),
  };
}
