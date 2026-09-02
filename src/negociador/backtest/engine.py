"""Motor de backtest: simula a estrategia de swing trade sobre o historico em cache.

Principios de design (para nunca reintroduzir lookahead bias por acidente):

- O sinal de ENTRADA e calculado com o fechamento do dia D (dado disponivel
  ate D) e so pode ser executado no dia D+1 (abertura).
- Para posicoes ja abertas, o preco de stop/take e FIXO desde a entrada
  (calculado uma unica vez, com o ATR do dia da entrada) - nunca recalculado
  retroativamente.
- Verificacao de stop/take usa o range Low-High do candle do dia; se o
  candle abre alem do alvo (gap), assume-se preenchimento no Open (pior
  preco para o stop, melhor preco para o take - ambos realistas). Se
  stop E take caem no range do MESMO candle, assume-se o stop primeiro
  (conservador).
- Saida por tempo fecha a mercado (Close do dia) quando `max_holding_days`
  e atingido.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from negociador.backtest.costs import CostParams, TaxTracker, order_cost
from negociador.strategy.position_sizing import PositionSizingParams, can_open_new_position, shares_to_buy
from negociador.strategy.rules import (
    ExitReason,
    RiskParams,
    apply_breakeven,
    check_entry,
    check_exit,
    compute_stop_take,
    fill_price_for_level,
)


@dataclass
class Position:
    ticker: str
    entry_date: pd.Timestamp
    entry_price: float
    qty: int
    stop_price: float
    take_price: float
    atr_at_entry: float
    high_since_entry: float
    holding_days: int = 0


@dataclass
class Trade:
    ticker: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    qty: int
    exit_reason: str
    gross_pnl: float
    total_costs: float
    net_pnl: float
    tax_paid: float = 0.0


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: list[Trade]
    tax_history: list[dict]
    initial_capital: float
    final_cash: float


def run_backtest(
    price_data: dict[str, pd.DataFrame],
    strategy_params: dict,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> BacktestResult:
    """Roda o backtest sobre `price_data` (dict ticker -> DataFrame ja com
    indicadores, via indicators.ta.add_all_indicators) no periodo [start, end].
    """
    variant = strategy_params["strategy_variant"]
    risk = RiskParams.from_config(strategy_params["risk"])
    sizing = PositionSizingParams.from_config(strategy_params["position_sizing"])
    costs = CostParams.from_config(strategy_params["costs"])
    initial_capital = float(strategy_params["capital_inicial"])

    # Calendario global de datas de pregao (uniao de todos os tickers, no periodo)
    all_dates = sorted(set().union(*[df.index for df in price_data.values()]))
    all_dates = pd.DatetimeIndex(all_dates)
    if start:
        all_dates = all_dates[all_dates >= pd.Timestamp(start)]
    if end:
        all_dates = all_dates[all_dates <= pd.Timestamp(end)]

    # Precos de fechamento "forward-filled" por ticker, so para marcacao a mercado
    # do patrimonio (nunca usado para decidir entrada/saida - isso usa so o dado real do dia).
    close_ffill = {t: df["Close"].reindex(all_dates).ffill() for t, df in price_data.items()}

    cash = initial_capital
    open_positions: dict[str, Position] = {}
    pending_entries: dict[str, dict] = {}  # ticker -> {"atr": ..., "reference_close": ...}
    trades: list[Trade] = []
    tax_tracker = TaxTracker(params=costs)
    equity_records: list[tuple[pd.Timestamp, float]] = []

    def close_position(ticker: str, pos: Position, exit_date: pd.Timestamp, exit_price: float, reason: str) -> None:
        nonlocal cash
        sale_value = exit_price * pos.qty
        buy_cost = order_cost(pos.entry_price * pos.qty, costs)
        sell_cost = order_cost(sale_value, costs)
        gross_pnl = (exit_price - pos.entry_price) * pos.qty
        net_pnl = gross_pnl - buy_cost - sell_cost
        cash += sale_value - sell_cost
        tax_due = tax_tracker.record_sale(exit_date, sale_value, net_pnl)
        cash -= tax_due
        trades.append(
            Trade(
                ticker=ticker, entry_date=pos.entry_date, exit_date=exit_date,
                entry_price=pos.entry_price, exit_price=exit_price, qty=pos.qty,
                exit_reason=reason, gross_pnl=gross_pnl,
                total_costs=buy_cost + sell_cost, net_pnl=net_pnl, tax_paid=tax_due,
            )
        )
        del open_positions[ticker]

    for i, date in enumerate(all_dates):
        if i == 0:
            equity_records.append((date, cash))
            continue

        # --- 1) processa saidas das posicoes abertas ---
        for ticker in list(open_positions):
            df = price_data[ticker]
            if date not in df.index:
                continue
            pos = open_positions[ticker]
            day_row = df.loc[date]
            pos.holding_days += 1
            pos.high_since_entry = max(pos.high_since_entry, float(day_row["High"]))
            pos.stop_price = apply_breakeven(pos.entry_price, pos.stop_price, pos.high_since_entry, pos.atr_at_entry, risk)

            reason = check_exit(day_row, pos.stop_price, pos.take_price, pos.holding_days, risk.max_holding_days)
            if reason == ExitReason.STOP_LOSS:
                fill = fill_price_for_level(day_row, pos.stop_price, "stop")
                close_position(ticker, pos, date, fill, reason.value)
            elif reason == ExitReason.TAKE_PROFIT:
                fill = fill_price_for_level(day_row, pos.take_price, "take")
                close_position(ticker, pos, date, fill, reason.value)
            elif reason == ExitReason.TIME_EXIT:
                close_position(ticker, pos, date, float(day_row["Close"]), reason.value)

        # --- 2) executa entradas pendentes (decididas no fechamento de ontem) na abertura de hoje ---
        for ticker in list(pending_entries):
            info = pending_entries.pop(ticker)
            if ticker in open_positions or not can_open_new_position(len(open_positions), sizing):
                continue
            df = price_data[ticker]
            if date not in df.index:
                continue
            day_row = df.loc[date]
            entry_price = float(day_row["Open"])
            stop_price, take_price = compute_stop_take(entry_price, info["atr"], risk)
            equity_now = cash + sum(
                open_positions[t].qty * close_ffill[t].get(date, open_positions[t].entry_price)
                for t in open_positions
            )
            qty = shares_to_buy(equity_now, cash, entry_price, stop_price, sizing)
            if qty <= 0:
                continue
            buy_value = entry_price * qty
            buy_cost = order_cost(buy_value, costs)
            if buy_value + buy_cost > cash:
                continue
            cash -= buy_value + buy_cost
            open_positions[ticker] = Position(
                ticker=ticker, entry_date=date, entry_price=entry_price, qty=qty,
                stop_price=stop_price, take_price=take_price, atr_at_entry=info["atr"],
                high_since_entry=float(day_row["High"]),
            )

        # --- 3) varre sinais de entrada usando o fechamento de HOJE -> vira pendente para amanha ---
        for ticker, df in price_data.items():
            if ticker in open_positions or ticker in pending_entries or date not in df.index:
                continue
            loc = df.index.get_loc(date)
            if loc == 0:
                continue
            row, prev_row = df.iloc[loc], df.iloc[loc - 1]
            if pd.isna(row.get("atr")) or row["atr"] <= 0:
                continue
            if check_entry(row, prev_row, variant):
                pending_entries[ticker] = {"atr": float(row["atr"])}

        # --- 4) marca o patrimonio a mercado (fechamento de hoje, com forward-fill entre feriados especificos) ---
        equity = cash + sum(pos.qty * close_ffill[t].get(date, pos.entry_price) for t, pos in open_positions.items())
        equity_records.append((date, equity))

    # fecha o ultimo mes de IR em aberto e debita da carteira final
    final_tax = tax_tracker.finalize()
    cash -= final_tax
    if equity_records:
        last_date, last_equity = equity_records[-1]
        equity_records[-1] = (last_date, last_equity - final_tax)

    equity_curve = pd.Series({d: e for d, e in equity_records}).sort_index()
    return BacktestResult(
        equity_curve=equity_curve,
        trades=trades,
        tax_history=tax_tracker.history,
        initial_capital=initial_capital,
        final_cash=cash,
    )
