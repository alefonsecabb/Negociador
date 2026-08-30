"""Combina indicadores + regras de entrada em sinais de ENTRADA para o watchlist.

Usado pelo monitor ao vivo (live/monitor.py) para varrer os tickers do
Ibovespa que NAO estao em posicao e decidir quais geram alerta de compra.
A logica de entrada em si vive em strategy/rules.py (compartilhada com o
backtest) - este modulo so empacota o resultado com o preco-limite sugerido.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from negociador.strategy.order_pricing import ExecutionMarginParams, buy_limit_price
from negociador.strategy.rules import RiskParams, check_entry, compute_stop_take


@dataclass(frozen=True)
class EntrySignal:
    ticker: str
    as_of: str
    reference_price: float
    limit_price: float
    stop_price: float
    take_price: float
    atr_pct: float
    variant: str


def evaluate_entry_signal(
    ticker: str,
    row: pd.Series,
    prev_row: pd.Series,
    variant: str,
    risk_params: RiskParams,
    margin_params: ExecutionMarginParams,
) -> EntrySignal | None:
    """Avalia um unico ticker (ja com indicadores calculados) e devolve um
    EntrySignal se as condicoes de entrada foram atingidas, ou None."""
    if not check_entry(row, prev_row, variant):
        return None
    if pd.isna(row.get("atr")) or row["atr"] <= 0:
        return None

    reference_price = float(row["Close"])
    atr_pct = float(row["atr_pct"])
    stop_price, take_price = compute_stop_take(reference_price, float(row["atr"]), risk_params)
    limit_price = buy_limit_price(reference_price, atr_pct, margin_params)

    return EntrySignal(
        ticker=ticker,
        as_of=str(row.name),
        reference_price=reference_price,
        limit_price=limit_price,
        stop_price=stop_price,
        take_price=take_price,
        atr_pct=atr_pct,
        variant=variant,
    )


def scan_watchlist(
    indicator_frames: dict[str, pd.DataFrame],
    variant: str,
    risk_params: RiskParams,
    margin_params: ExecutionMarginParams,
    exclude_tickers: set[str] | None = None,
) -> list[EntrySignal]:
    """Varre um dict {ticker: DataFrame com indicadores} e devolve os sinais de entrada do ultimo candle."""
    exclude_tickers = exclude_tickers or set()
    signals: list[EntrySignal] = []
    for ticker, df in indicator_frames.items():
        if ticker in exclude_tickers or len(df) < 2:
            continue
        row, prev_row = df.iloc[-1], df.iloc[-2]
        signal = evaluate_entry_signal(ticker, row, prev_row, variant, risk_params, margin_params)
        if signal:
            signals.append(signal)
    return signals
