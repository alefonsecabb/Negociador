"""Grid search (pequeno, de proposito) dos parametros de risco/dimensionamento,
maximizando a metrica '% de ciclos de 30 dias >= meta', avaliada no periodo
informado (tipicamente a janela de TREINO de um walk-forward - ver walk_forward.py).

O grid e deliberadamente pequeno (poucos parametros, poucos valores cada) para
reduzir o risco de "data snooping"/overfitting por multiplos testes.
"""
from __future__ import annotations

import copy
from itertools import product

from negociador.backtest.engine import run_backtest
from negociador.backtest.metrics import summarize_backtest

# Onde, dentro da secao correspondente de strategy_params.yaml, cada parametro do grid vive
_PARAM_SECTION = {
    "atr_stop_multiple": "risk",
    "reward_risk_ratio": "risk",
    "risk_per_trade_pct": "position_sizing",
}


def grid_combinations(grid: dict) -> list[dict]:
    keys = list(grid.keys())
    return [dict(zip(keys, values)) for values in product(*[grid[k] for k in keys])]


def build_params_variant(base_params: dict, overrides: dict) -> dict:
    params = copy.deepcopy(base_params)
    for key, value in overrides.items():
        section = _PARAM_SECTION[key]
        params[section][key] = value
    return params


def calibrate(
    price_data: dict,
    base_params: dict,
    start=None,
    end=None,
    target: float = 0.05,
    cycle_days: int = 30,
) -> tuple[dict, dict]:
    """Roda todas as combinacoes de `base_params['calibration_grid']` no periodo
    [start, end] e devolve (overrides_vencedores, relatorio_do_vencedor).

    Criterio de escolha: maior '% de ciclos >= meta'; empate resolvido pelo
    maior retorno medio por ciclo.
    """
    combos = grid_combinations(base_params["calibration_grid"])
    best_overrides, best_report, best_score = None, None, None

    for overrides in combos:
        params = build_params_variant(base_params, overrides)
        result = run_backtest(price_data, params, start=start, end=end)
        report = summarize_backtest(result, target_monthly_return_pct=target, cycle_days=cycle_days)
        c = report["ciclos_rolantes_30d"]
        score = (c["pct_janelas_atingiu_meta"] or 0.0, c["retorno_medio_pct"] if c["retorno_medio_pct"] is not None else -999.0)
        if best_score is None or score > best_score:
            best_score, best_overrides, best_report = score, overrides, report

    return best_overrides, best_report
