"""CLI: gera os JSONs estaticos em site/data/ a partir do estado atual (carteira,
alertas, relatorios de backtest/walk-forward, universo) - consumidos pelo GitHub Pages.

Uso:
    python -m negociador.cli.publish_site
    python -m negociador.cli.publish_site --no-quotes   # nao busca cotacao ao vivo (mais rapido/offline)
"""
from __future__ import annotations

import argparse

from negociador.live.publish_site_data import publish_all


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-quotes", action="store_true", help="Nao busca cotacao ao vivo para marcar posicoes a mercado")
    args = parser.parse_args()
    publish_all(fetch_quotes=not args.no_quotes)
    print("site/data/*.json atualizado.")


if __name__ == "__main__":
    main()
