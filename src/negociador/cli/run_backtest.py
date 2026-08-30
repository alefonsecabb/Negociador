"""CLI: roda o backtest completo sobre o cache local e imprime/grava o relatorio.

Uso:
    python -m negociador.cli.run_backtest
    python -m negociador.cli.run_backtest --start 2019-01-01 --end 2026-08-01
    python -m negociador.cli.run_backtest --tickers PETR4 VALE3 ITUB4
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from negociador.backtest.engine import run_backtest
from negociador.backtest.metrics import summarize_backtest
from negociador.config import load_strategy_params
from negociador.data_ingestion.cache import load_cached
from negociador.indicators.ta import add_all_indicators
from negociador.universe import load_universe

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPORTS_DIR = PROJECT_ROOT / "reports"


def load_price_data_with_indicators(tickers: list[str], params: dict) -> dict:
    data = {}
    for ticker in tickers:
        df = load_cached(ticker)
        if df.empty or len(df) < params["indicators"]["ema_trend_period"] + 5:
            continue
        data[ticker] = add_all_indicators(df, params["indicators"])
    return data


def print_report(report: dict) -> None:
    p = report["periodo"]
    print(f"\n=== Backtest: {p['inicio']} a {p['fim']} ({p['dias_corridos']} dias corridos) ===")
    print(f"Capital inicial: R$ {report['capital_inicial']:,.2f}")
    print(f"Capital final:   R$ {report['capital_final']:,.2f}")
    print(f"Retorno total:   {report['retorno_total_pct']:.2f}%")
    print(f"Retorno equivalente por ciclo de 30d: {report['retorno_equivalente_por_ciclo_30d_pct']:.2f}%  (meta: {report['meta_por_ciclo_pct']:.1f}%)")

    c = report["ciclos_rolantes_30d"]
    print(f"\n--- Ciclos rolantes de 30 dias (n={c['n_janelas_avaliadas']}) ---")
    if c["n_janelas_avaliadas"]:
        print(f"Retorno medio:   {c['retorno_medio_pct']:.2f}%")
        print(f"Retorno mediano: {c['retorno_mediano_pct']:.2f}%")
        print(f"% de ciclos >= meta ({report['meta_por_ciclo_pct']:.1f}%): {c['pct_janelas_atingiu_meta']:.1f}%")
        print(f"% de ciclos negativos: {c['pct_janelas_negativas']:.1f}%")
        print(f"Pior ciclo: {c['pior_janela_pct']:.2f}%  |  Melhor ciclo: {c['melhor_janela_pct']:.2f}%")
    else:
        print("(historico insuficiente para calcular ciclos rolantes)")

    print("\n--- Risco ---")
    print(f"Drawdown maximo: {report['risco']['drawdown_maximo_pct']:.2f}%")

    o = report["operacoes"]
    print("\n--- Operacoes ---")
    print(f"Numero de trades: {o['numero_de_trades']}")
    print(f"Taxa de acerto:   {o['taxa_de_acerto_pct']:.1f}%")
    print(f"Profit factor:    {o['profit_factor']:.2f}")
    print(f"Custos totais (emolumentos+corretagem): R$ {o['custos_totais_brl']:,.2f}")
    print(f"IR total pago:    R$ {o['ir_total_pago_brl']:,.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="*", default=None, help="Tickers especificos (default: universo Ibovespa)")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out", default=str(REPORTS_DIR / "backtest_report.json"))
    args = parser.parse_args()

    params = load_strategy_params()
    tickers = args.tickers or load_universe()
    print(f"Carregando cache de {len(tickers)} ticker(s) e calculando indicadores...")
    price_data = load_price_data_with_indicators(tickers, params)
    print(f"{len(price_data)}/{len(tickers)} tickers com historico suficiente para o backtest.")

    result = run_backtest(price_data, params, start=args.start, end=args.end)
    report = summarize_backtest(result, target_monthly_return_pct=params["target_monthly_return_pct"], include_series=True)
    print_report(report)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nRelatorio salvo em {args.out}")


if __name__ == "__main__":
    main()
