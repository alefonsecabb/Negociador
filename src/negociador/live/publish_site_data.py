"""Exporta o estado da carteira/alertas/backtest para site/data/*.json,
consumidos pelo dashboard estatico (GitHub Pages)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from negociador.data_ingestion.yfinance_client import fetch_last_quote
from negociador.portfolio import paper_portfolio as pp
from negociador.universe import load_universe

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SITE_DATA_DIR = PROJECT_ROOT / "site" / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def publish_portfolio(fetch_quotes: bool = True) -> dict:
    cash = pp.get_cash()
    initial_capital = pp.get_initial_capital()
    positions = pp.get_open_positions()

    equity = cash
    for pos in positions:
        current_price = pos["entry_price"]
        if fetch_quotes:
            quote = fetch_last_quote(pos["ticker"])
            if quote:
                current_price = quote["price"]
        pos["current_price"] = current_price
        pos["unrealized_pnl"] = (current_price - pos["entry_price"]) * pos["qty"]
        pos["unrealized_pnl_pct"] = (current_price / pos["entry_price"] - 1) * 100
        equity += current_price * pos["qty"]

    trades = pp.get_trades()
    data = {
        "generated_at": pd_now(),
        "capital_inicial": initial_capital,
        "cash": cash,
        "equity": equity,
        "retorno_total_pct": (equity / initial_capital - 1) * 100 if initial_capital else 0.0,
        "positions": positions,
        "n_trades_fechados": len(trades),
    }
    _write_json(SITE_DATA_DIR / "portfolio.json", data)
    return data


def publish_alerts() -> list[dict]:
    alerts = pp.get_alerts()
    _write_json(SITE_DATA_DIR / "alerts.json", {"generated_at": pd_now(), "alerts": alerts})
    return alerts


def publish_backtest_reports() -> None:
    backtest_path = REPORTS_DIR / "backtest_report.json"
    wf_path = REPORTS_DIR / "walk_forward_report.json"
    out = {"generated_at": pd_now()}
    if backtest_path.exists():
        out["backtest"] = json.loads(backtest_path.read_text(encoding="utf-8"))
    if wf_path.exists():
        out["walk_forward"] = json.loads(wf_path.read_text(encoding="utf-8"))
    _write_json(SITE_DATA_DIR / "backtest.json", out)


def publish_universe() -> list[str]:
    tickers = load_universe()
    _write_json(SITE_DATA_DIR / "universe.json", {"generated_at": pd_now(), "tickers": tickers})
    return tickers


def pd_now() -> str:
    return pd.Timestamp.now().isoformat()


def publish_all(fetch_quotes: bool = True) -> None:
    publish_portfolio(fetch_quotes=fetch_quotes)
    publish_alerts()
    publish_backtest_reports()
    publish_universe()
