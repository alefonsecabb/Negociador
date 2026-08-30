"""CLI: confirma que uma ordem sugerida por um alerta foi executada no homebroker.

So a partir desta confirmacao a carteira ficticia (negociador.db) muda de
estado - o monitor ao vivo (run_monitor) so gera alertas, nunca abre/fecha
posicoes sozinho.

Dois modos de uso:

1) Direto (rodando localmente, com o computador ligado durante o expediente):
       python -m negociador.cli.confirm_execution --alert-id 5
       python -m negociador.cli.confirm_execution --alert-id 5 --fill-price 42.10

2) Via arquivo de eventos (o botao "marquei como executado" do dashboard,
   pelo navegador, grava uma linha em data/events.jsonl usando a GitHub API;
   o workflow on_execute.yml chama este mesmo script em modo --reconcile):
       python -m negociador.cli.confirm_execution --reconcile
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from negociador.config import load_strategy_params
from negociador.backtest.costs import CostParams
from negociador.data_ingestion.yfinance_client import fetch_last_quote
from negociador.portfolio import paper_portfolio as pp
from negociador.strategy.position_sizing import PositionSizingParams, can_open_new_position, shares_to_buy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVENTS_FILE = PROJECT_ROOT / "data" / "events.jsonl"
CURSOR_FILE = PROJECT_ROOT / "data" / "events_cursor.txt"


def _current_equity(costs: CostParams) -> float:
    cash = pp.get_cash()
    equity = cash
    for pos in pp.get_open_positions():
        quote = fetch_last_quote(pos["ticker"])
        price = quote["price"] if quote else pos["entry_price"]
        equity += price * pos["qty"]
    return equity


def apply_confirmation(alert_id: int, fill_price: float | None, params: dict) -> dict:
    """Aplica a confirmacao de um alerta: abre ou fecha a posicao correspondente."""
    alerts = pp.get_alerts()
    alert = next((a for a in alerts if a["id"] == alert_id), None)
    if alert is None:
        return {"ok": False, "error": f"alerta #{alert_id} nao encontrado"}
    if alert["status"] != "novo":
        return {"ok": False, "error": f"alerta #{alert_id} ja esta em status '{alert['status']}'"}

    costs = CostParams.from_config(params["costs"])
    sizing = PositionSizingParams.from_config(params["position_sizing"])
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    extra = json.loads(alert["extra_json"] or "{}")

    if alert["alert_type"] == "ENTRADA":
        price = fill_price if fill_price is not None else alert["limit_price"]
        open_positions = pp.get_open_positions()
        if not can_open_new_position(len(open_positions), sizing) or alert["ticker"] in {p["ticker"] for p in open_positions}:
            pp.set_alert_status(alert_id, "ignorado")
            return {"ok": False, "error": "limite de posicoes atingido ou ticker ja em posicao"}
        equity = _current_equity(costs)
        qty = shares_to_buy(equity, pp.get_cash(), price, alert["stop_price"], sizing)
        if qty <= 0:
            pp.set_alert_status(alert_id, "ignorado")
            return {"ok": False, "error": "quantidade calculada foi zero (caixa insuficiente ou risco/posicao mal dimensionados)"}
        opened = pp.open_position(
            alert["ticker"], today, price, qty, alert["stop_price"], alert["take_price"],
            atr_at_entry=extra.get("atr", (price - alert["stop_price"]) / params["risk"]["atr_stop_multiple"]),
            costs=costs,
        )
        if not opened:
            return {"ok": False, "error": "caixa insuficiente no momento da confirmacao"}
        pp.set_alert_status(alert_id, "executado")
        return {"ok": True, "action": "OPEN", "ticker": alert["ticker"], "qty": qty, "price": price}

    else:  # STOP_LOSS, TAKE_PROFIT, SAIDA_POR_TEMPO
        price = fill_price if fill_price is not None else alert["limit_price"]
        trade = pp.close_position(alert["ticker"], today, price, alert["alert_type"], costs)
        if trade is None:
            return {"ok": False, "error": f"{alert['ticker']} nao esta em posicao aberta"}
        pp.set_alert_status(alert_id, "executado")
        return {"ok": True, "action": "CLOSE", **trade}


def record_event(alert_id: int, fill_price: float | None = None) -> None:
    """Registra um evento de confirmacao em data/events.jsonl (append-only) -
    usado pelo fluxo via navegador (GitHub API) antes do on_execute.yml reconciliar."""
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    event = {"alert_id": alert_id, "fill_price": fill_price, "recorded_at": pd.Timestamp.now().isoformat()}
    with open(EVENTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def reconcile_pending_events(params: dict) -> list[dict]:
    """Processa as linhas de data/events.jsonl ainda nao aplicadas (cursor em
    data/events_cursor.txt) e aplica cada confirmacao pendente."""
    if not EVENTS_FILE.exists():
        return []
    lines = EVENTS_FILE.read_text(encoding="utf-8").splitlines()
    cursor = int(CURSOR_FILE.read_text().strip()) if CURSOR_FILE.exists() else 0

    results = []
    for line in lines[cursor:]:
        if not line.strip():
            continue
        event = json.loads(line)
        result = apply_confirmation(event["alert_id"], event.get("fill_price"), params)
        results.append({"event": event, "result": result})

    CURSOR_FILE.write_text(str(len(lines)))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alert-id", type=int, default=None, help="Confirma diretamente este alerta")
    parser.add_argument("--fill-price", type=float, default=None, help="Preco realmente executado (default: preco-limite do alerta)")
    parser.add_argument("--reconcile", action="store_true", help="Processa eventos pendentes em data/events.jsonl")
    args = parser.parse_args()

    params = load_strategy_params()

    if args.reconcile:
        results = reconcile_pending_events(params)
        print(f"{len(results)} evento(s) processado(s).")
        for r in results:
            print(f"  alerta #{r['event']['alert_id']}: {r['result']}")
        return

    if args.alert_id is None:
        parser.error("informe --alert-id ou --reconcile")

    record_event(args.alert_id, args.fill_price)
    result = apply_confirmation(args.alert_id, args.fill_price, params)
    print(result)


if __name__ == "__main__":
    main()
