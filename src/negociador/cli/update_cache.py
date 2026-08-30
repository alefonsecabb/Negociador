"""CLI: atualiza o cache historico (parquet) de todos os tickers do universo.

Uso:
    python -m negociador.cli.update_cache                 # todos os tickers do Ibovespa
    python -m negociador.cli.update_cache PETR4 VALE3      # so os tickers informados
    python -m negociador.cli.update_cache --backfill 5y    # janela de backfill customizada
"""
from __future__ import annotations

import argparse
import logging

from negociador.data_ingestion.cache import DEFAULT_BACKFILL_PERIOD, update_all
from negociador.universe import load_universe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="*", help="Tickers especificos (default: universo Ibovespa completo)")
    parser.add_argument("--backfill", default=DEFAULT_BACKFILL_PERIOD, help=f"Periodo de backfill inicial (default: {DEFAULT_BACKFILL_PERIOD})")
    args = parser.parse_args()

    tickers = args.tickers or load_universe()
    print(f"Atualizando cache de {len(tickers)} ticker(s)...")
    report = update_all(tickers, backfill_period=args.backfill)

    ok = {t: n for t, n in report.items() if n >= 0}
    failed = {t: n for t, n in report.items() if n < 0}
    print(f"\nOK: {len(ok)}/{len(tickers)} tickers.")
    if failed:
        print(f"FALHARAM ({len(failed)}): {', '.join(failed)}")
    if ok:
        avg_rows = sum(ok.values()) / len(ok)
        print(f"Media de {avg_rows:.0f} linhas por ticker.")


if __name__ == "__main__":
    main()
