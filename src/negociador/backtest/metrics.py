"""Metricas de avaliacao do backtest - sempre reportadas de forma honesta,
lado a lado, sem destacar so os resultados bons."""
from __future__ import annotations

import pandas as pd

from negociador.backtest.engine import BacktestResult


def max_drawdown(equity_curve: pd.Series) -> float:
    """Maior queda percentual do pico ao vale (valor negativo, ex. -0.23 = -23%)."""
    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1.0
    return float(drawdown.min()) if len(drawdown) else 0.0


def win_rate(trades: list) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.net_pnl > 0)
    return wins / len(trades)


def profit_factor(trades: list) -> float:
    gross_wins = sum(t.net_pnl for t in trades if t.net_pnl > 0)
    gross_losses = sum(-t.net_pnl for t in trades if t.net_pnl < 0)
    if gross_losses == 0:
        return float("inf") if gross_wins > 0 else 0.0
    return gross_wins / gross_losses


def rolling_cycle_returns(equity_curve: pd.Series, cycle_days: int = 30) -> pd.Series:
    """Retorno da carteira em cada janela ROLANTE de `cycle_days` dias corridos
    (nao mes calendario): para cada data D, compara equity(D) com equity na data
    mais proxima de D - cycle_days (usando o ultimo valor conhecido ate la, via asof).

    So produz um valor para datas que ja tem pelo menos `cycle_days` de historico
    (janelas antes disso ficam de fora - nao ha o que comparar).
    """
    if equity_curve.empty:
        return pd.Series(dtype=float)
    returns = {}
    for date in equity_curve.index:
        past_date = date - pd.Timedelta(days=cycle_days)
        if past_date < equity_curve.index[0]:
            continue
        past_equity = equity_curve.asof(past_date)
        if pd.isna(past_equity) or past_equity <= 0:
            continue
        returns[date] = equity_curve.loc[date] / past_equity - 1.0
    return pd.Series(returns)


def summarize_backtest(
    result: BacktestResult,
    target_monthly_return_pct: float = 0.05,
    cycle_days: int = 30,
    include_series: bool = False,
) -> dict:
    """Relatorio honesto de desempenho - a metrica-chave e '% de ciclos >= meta',
    sempre reportada ao lado de '% de ciclos negativos' e do pior drawdown."""
    equity = result.equity_curve
    trades = result.trades

    total_return = (equity.iloc[-1] / result.initial_capital - 1.0) if len(equity) else 0.0
    n_days = (equity.index[-1] - equity.index[0]).days if len(equity) > 1 else 0
    n_cycles_elapsed = max(n_days / cycle_days, 1e-9)
    # CAGR mensal equivalente (para contextualizar o retorno total num "por ciclo medio" simples)
    equivalent_return_per_cycle = (1 + total_return) ** (1 / n_cycles_elapsed) - 1 if total_return > -1 else -1.0

    cycle_returns = rolling_cycle_returns(equity, cycle_days=cycle_days)

    total_costs = sum(t.total_costs for t in trades)
    total_tax = sum(t.tax_paid for t in trades)

    report = {
        "periodo": {
            "inicio": str(equity.index[0].date()) if len(equity) else None,
            "fim": str(equity.index[-1].date()) if len(equity) else None,
            "dias_corridos": n_days,
        },
        "capital_inicial": result.initial_capital,
        "capital_final": float(equity.iloc[-1]) if len(equity) else result.initial_capital,
        "retorno_total_pct": total_return * 100,
        "retorno_equivalente_por_ciclo_30d_pct": equivalent_return_per_cycle * 100,
        "meta_por_ciclo_pct": target_monthly_return_pct * 100,
        "ciclos_rolantes_30d": {
            "n_janelas_avaliadas": int(len(cycle_returns)),
            "retorno_medio_pct": float(cycle_returns.mean() * 100) if len(cycle_returns) else None,
            "retorno_mediano_pct": float(cycle_returns.median() * 100) if len(cycle_returns) else None,
            "pct_janelas_atingiu_meta": float((cycle_returns >= target_monthly_return_pct).mean() * 100) if len(cycle_returns) else None,
            "pct_janelas_negativas": float((cycle_returns < 0).mean() * 100) if len(cycle_returns) else None,
            "pior_janela_pct": float(cycle_returns.min() * 100) if len(cycle_returns) else None,
            "melhor_janela_pct": float(cycle_returns.max() * 100) if len(cycle_returns) else None,
        },
        "risco": {
            "drawdown_maximo_pct": max_drawdown(equity) * 100,
        },
        "operacoes": {
            "numero_de_trades": len(trades),
            "taxa_de_acerto_pct": win_rate(trades) * 100,
            "profit_factor": profit_factor(trades),
            "custos_totais_brl": total_costs,
            "ir_total_pago_brl": total_tax,
        },
    }

    if include_series:
        report["series"] = {
            "equity_curve": [[str(d.date()), float(v)] for d, v in equity.items()],
            "cycle_returns_pct": [float(v * 100) for v in cycle_returns.values],
        }

    return report
