"""Exporta o estado da carteira/alertas/backtest para site/data/*.json,
consumidos pelo dashboard estatico (GitHub Pages)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from negociador.config import load_strategy_params
from negociador.data_ingestion.yfinance_client import fetch_last_quote
from negociador.portfolio import paper_portfolio as pp
from negociador.universe import load_universe

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SITE_DATA_DIR = PROJECT_ROOT / "site" / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def _load_quotes() -> dict:
    """Le site/data/quotes.json (cotacoes coletadas pelo ultimo run do monitor).
    Devolve {} se o arquivo nao existir ou estiver corrompido."""
    path = SITE_DATA_DIR / "quotes.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("quotes", {})
    except (json.JSONDecodeError, OSError):
        return {}


def publish_quotes(quotes: dict) -> None:
    """Grava site/data/quotes.json com as cotacoes coletadas pelo monitor
    (ultimo Close/Open/High/Low por ticker). Um ciclo sem nenhuma cotacao e'
    sempre falha transitoria de rede - nesse caso NAO sobrescreve o ultimo
    arquivo bom (mesmo racional do fix do backtest.json em 554c2d1)."""
    if not quotes:
        return
    _write_json(SITE_DATA_DIR / "quotes.json", {"generated_at": pd_now(), "quotes": quotes})


def publish_portfolio(fetch_quotes: bool = True) -> dict:
    cash = pp.get_cash()
    initial_capital = pp.get_initial_capital()
    positions = pp.get_open_positions()
    quotes = _load_quotes()

    equity = cash
    for pos in positions:
        current_price = pos["entry_price"]
        cached = quotes.get(pos["ticker"])
        if cached and cached.get("price"):
            current_price = cached["price"]
        elif fetch_quotes:
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


def publish_params() -> dict:
    """Gera site/data/params.json: os parametros do modelo que o homebroker no
    navegador precisa para dimensionar posicao, aplicar custos/IR e simular as
    saidas exatamente como o backtest (dimensionamento, stop/take, breakeven,
    prazo maximo, custos B3 + IR mensal, meta por ciclo)."""
    params = load_strategy_params()
    data = {
        "generated_at": pd_now(),
        "capital_inicial": float(params["capital_inicial"]),
        "risk": {
            "atr_stop_multiple": float(params["risk"]["atr_stop_multiple"]),
            "reward_risk_ratio": float(params["risk"]["reward_risk_ratio"]),
            "breakeven_after_r": float(params["risk"].get("breakeven_after_r", 0.0)),
            "max_holding_days": int(params["risk"]["max_holding_days"]),
        },
        "position_sizing": {
            "risk_per_trade_pct": float(params["position_sizing"]["risk_per_trade_pct"]),
            "max_position_pct": float(params["position_sizing"]["max_position_pct"]),
            "max_open_positions": int(params["position_sizing"]["max_open_positions"]),
            "min_cash_reserve_pct": float(params["position_sizing"]["min_cash_reserve_pct"]),
        },
        "costs": {
            "b3_emolument_pct": float(params["costs"]["b3_emolument_pct"]),
            "brokerage_fee_brl": float(params["costs"]["brokerage_fee_brl"]),
            "income_tax_pct": float(params["costs"]["income_tax_pct"]),
            "income_tax_exempt_sales_brl": float(params["costs"]["income_tax_exempt_sales_brl"]),
        },
        "target_monthly_return_pct": float(params["target_monthly_return_pct"]),
    }
    _write_json(SITE_DATA_DIR / "params.json", data)
    return data


def publish_alerts() -> list[dict]:
    alerts = pp.get_alerts()
    _write_json(SITE_DATA_DIR / "alerts.json", {"generated_at": pd_now(), "alerts": alerts})
    return alerts


def publish_backtest_reports() -> None:
    """Copia reports/backtest_report.json e reports/walk_forward_report.json
    para site/data/backtest.json.

    reports/*.json e' gitignored (saida local, regenerada sob demanda por
    run_backtest.py/run_walk_forward.py) - o monitor ao vivo roda em
    containers efemeros do GitHub Actions que NUNCA tem esses arquivos.
    Por isso, se nenhum dos dois existir no momento da chamada, esta funcao
    NAO sobrescreve site/data/backtest.json: preserva a ultima publicacao
    boa (feita manualmente, com os relatorios presentes) em vez de apagar o
    resultado do backtest/walk-forward do dashboard a cada ciclo do monitor.
    """
    backtest_path = REPORTS_DIR / "backtest_report.json"
    wf_path = REPORTS_DIR / "walk_forward_report.json"
    if not backtest_path.exists() and not wf_path.exists():
        return
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
    publish_params()
    publish_alerts()
    publish_backtest_reports()
    publish_universe()
