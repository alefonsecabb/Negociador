"""Motor de sinais diario/monitoramento ao vivo.

Roda 1x por invocacao (o GitHub Actions chama isso a cada ~15min durante o
horario de pregao). A cada chamada:

1. Fecha o mes de IR anterior, se aplicavel (paper_portfolio.roll_tax_month).
2. Para cada posicao ABERTA na carteira ficticia (fluxo manual/CLI): busca a
   cotacao mais recente, recalcula indicadores, atualiza holding_days/stop de
   breakeven, e verifica se stop/take/tempo foram atingidos -> gera alerta de SAIDA.
3. Para os demais tickers do universo (Ibovespa): verifica condicoes de
   ENTRADA -> gera alerta de ENTRADA.
4. Devolve as cotacoes coletadas (report["quotes"]) - o CLI as grava em
   site/data/quotes.json para o homebroker no navegador marcar a mercado e
   simular as saidas.

So GERA ALERTAS/COTACOES - nunca abre/fecha posicoes sozinho. O homebroker do
dashboard e' 100% local (localStorage do navegador): o botao "Executar" abre a
posicao ali na hora e o proprio navegador simula stop/take/tempo com as
cotacoes publicadas.
"""
from __future__ import annotations

import logging

import pandas as pd

from negociador.backtest.costs import CostParams
from negociador.data_ingestion.cache import load_cached
from negociador.data_ingestion.yfinance_client import fetch_today_bar
from negociador.indicators.ta import add_all_indicators
from negociador.live.alerts import raise_entry_alert, raise_exit_alert
from negociador.portfolio import paper_portfolio as pp
from negociador.strategy.order_pricing import ExecutionMarginParams
from negociador.strategy.rules import RiskParams, apply_breakeven, check_exit
from negociador.strategy.signals import evaluate_entry_signal
from negociador.universe import load_universe

logger = logging.getLogger(__name__)


def build_live_frame(ticker: str, indicator_params: dict) -> tuple[pd.DataFrame | None, dict | None]:
    """Cache historico + bar "hoje ate agora" (agregado do intradiario) -> indicadores."""
    cached = load_cached(ticker)
    if cached.empty:
        return None, None
    today_bar = fetch_today_bar(ticker)
    if today_bar is None:
        df = cached
    else:
        today_date = pd.Timestamp(today_bar["date"])
        row = pd.Series({k: today_bar[k] for k in ["Open", "High", "Low", "Close", "Volume"]}, name=today_date)
        df = cached.copy()
        df.loc[today_date] = row
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="last")]
    return add_all_indicators(df, indicator_params), today_bar


def _holding_days(frame: pd.DataFrame, entry_date: pd.Timestamp, as_of_date: pd.Timestamp) -> int:
    return int(((frame.index > entry_date) & (frame.index <= as_of_date)).sum())


def run_monitor_once(params: dict, tickers: list[str] | None = None) -> dict:
    tickers = tickers or load_universe()
    costs = CostParams.from_config(params["costs"])
    risk = RiskParams.from_config(params["risk"])
    margin = ExecutionMarginParams.from_config(params["execution_margin"])
    variant = params["strategy_variant"]
    indicator_params = params["indicators"]

    today_str = pd.Timestamp.now().strftime("%Y-%m-%d")
    pp.initialize(params["capital_inicial"])
    tax_due = pp.roll_tax_month(today_str, costs)

    # Expira alertas pendentes antigos ANTES de varrer sinais novos, para que o
    # ticker liberado ja possa receber um alerta fresco (preco atual) neste
    # mesmo ciclo, em vez de esperar o proximo.
    expires_after_days = params.get("alerts", {}).get("expires_after_days", 2)
    expired_ids = pp.expire_stale_alerts(expires_after_days)

    open_positions = {p["ticker"]: p for p in pp.get_open_positions()}
    quotes: dict[str, dict] = {}
    report = {
        "tax_debited_on_month_roll": tax_due,
        "alerts_expired": expired_ids,
        "alerts_created": [],
        "errors": [],
        "quotes": quotes,
    }

    def _record_quote(ticker: str, row: pd.Series, bar_date) -> None:
        quotes[ticker] = {
            "price": float(row["Close"]),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "date": str(bar_date),
        }

    # --- 1) posicoes abertas na carteira sqlite (fluxo manual/CLI): verifica saida ---
    for ticker, pos in open_positions.items():
        try:
            frame, today_bar = build_live_frame(ticker, indicator_params)
        except Exception as exc:
            logger.exception("Erro processando posicao aberta %s", ticker)
            report["errors"].append({"ticker": ticker, "stage": "exit_check", "error": str(exc)})
            continue
        if frame is None or today_bar is None or frame.empty:
            continue

        row = frame.iloc[-1]
        _record_quote(ticker, row, today_bar["date"])
        entry_date = pd.Timestamp(pos["entry_date"])
        as_of_date = pd.Timestamp(today_bar["date"])
        holding_days = _holding_days(frame, entry_date, as_of_date)
        high_since_entry = max(float(pos["high_since_entry"]), float(row["High"]))
        new_stop = apply_breakeven(pos["entry_price"], pos["stop_price"], high_since_entry, pos["atr_at_entry"], risk)
        pp.update_position(ticker, stop_price=new_stop, high_since_entry=high_since_entry, holding_days=holding_days)

        reason = check_exit(row, new_stop, pos["take_price"], holding_days, risk.max_holding_days)
        if reason:
            atr_pct = float(row["atr_pct"]) if pd.notna(row.get("atr_pct")) else 0.0
            alert_id = raise_exit_alert(
                ticker, reason.value, float(row["Close"]), new_stop, pos["take_price"], atr_pct, margin,
            )
            if alert_id:
                report["alerts_created"].append({"id": alert_id, "ticker": ticker, "type": reason.value})

    # --- 2) watchlist: verifica entrada (exclui quem ja esta em posicao) ---
    for ticker in tickers:
        if ticker in open_positions:
            continue
        try:
            frame, today_bar = build_live_frame(ticker, indicator_params)
        except Exception as exc:
            logger.exception("Erro processando watchlist %s", ticker)
            report["errors"].append({"ticker": ticker, "stage": "entry_scan", "error": str(exc)})
            continue
        if frame is None or today_bar is None or len(frame) < 2:
            continue

        row = frame.iloc[-1]
        _record_quote(ticker, row, today_bar["date"])
        signal = evaluate_entry_signal(ticker, row, frame.iloc[-2], variant, risk, margin)
        if signal:
            alert_id = raise_entry_alert(signal, margin)
            if alert_id:
                report["alerts_created"].append({"id": alert_id, "ticker": ticker, "type": "ENTRADA"})

    return report
