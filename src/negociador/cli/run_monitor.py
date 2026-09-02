"""CLI: roda o monitor ao vivo uma vez (e o que o GitHub Actions chama a cada ciclo).

Uso:
    python -m negociador.cli.run_monitor
    python -m negociador.cli.run_monitor --tickers PETR4 VALE3
"""
from __future__ import annotations

import argparse
import logging

from negociador.config import load_strategy_params
from negociador.live.monitor import run_monitor_once
from negociador.live.publish_site_data import publish_quotes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="*", default=None)
    args = parser.parse_args()

    params = load_strategy_params()
    report = run_monitor_once(params, tickers=args.tickers)

    publish_quotes(report.get("quotes", {}))
    print(f"{len(report.get('quotes', {}))} cotacao(oes) publicada(s) em site/data/quotes.json")

    if report["tax_debited_on_month_roll"]:
        print(f"IR do mes anterior debitado da carteira: R$ {report['tax_debited_on_month_roll']:,.2f}")
    if report["alerts_expired"]:
        print(f"{len(report['alerts_expired'])} alerta(s) expirado(s) (nao confirmados nem ignorados a tempo): {report['alerts_expired']}")
    if report["alerts_created"]:
        print(f"{len(report['alerts_created'])} alerta(s) novo(s):")
        for a in report["alerts_created"]:
            print(f"  #{a['id']} {a['ticker']} - {a['type']}")
    else:
        print("Nenhum alerta novo neste ciclo.")
    if report["errors"]:
        print(f"\n{len(report['errors'])} erro(s) durante o ciclo:")
        for e in report["errors"]:
            print(f"  {e['ticker']} ({e['stage']}): {e['error']}")


if __name__ == "__main__":
    main()
