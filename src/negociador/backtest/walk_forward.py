"""Validacao anti-overfitting: walk-forward rolante + holdout final.

Para cada janela: calibra os parametros (grid search) SOMENTE nos dados de
TREINO, e avalia esses parametros no periodo de TESTE (fora da amostra) logo
em seguida - nunca o contrario. O desempenho de treino nunca e reportado
como "quanto a estrategia rende"; so o agregado das janelas de TESTE conta.

Ao final, reserva um HOLDOUT (os ultimos N meses do historico) nunca tocado
durante nenhuma etapa de calibracao das janelas rolantes, avaliado uma unica
vez com os parametros calibrados sobre todo o periodo anterior a ele.
"""
from __future__ import annotations

import pandas as pd

from negociador.backtest.calibration import build_params_variant, calibrate
from negociador.backtest.engine import run_backtest
from negociador.backtest.metrics import summarize_backtest


def _month_windows(start: pd.Timestamp, end: pd.Timestamp, train_months: int, test_months: int, step_months: int, holdout_start: pd.Timestamp):
    windows = []
    train_start = start
    while True:
        train_end = train_start + pd.DateOffset(months=train_months)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=test_months)
        if test_end > holdout_start:
            break
        windows.append((train_start, train_end, test_start, test_end))
        train_start = train_start + pd.DateOffset(months=step_months)
    return windows


def run_walk_forward(price_data: dict, base_params: dict, target: float | None = None) -> dict:
    wf_cfg = base_params["walk_forward"]
    target = target if target is not None else base_params["target_monthly_return_pct"]

    all_dates = sorted(set().union(*[df.index for df in price_data.values()]))
    start_date, end_date = pd.Timestamp(all_dates[0]), pd.Timestamp(all_dates[-1])
    holdout_start = end_date - pd.DateOffset(months=wf_cfg["final_holdout_months"])

    windows = _month_windows(
        start_date, end_date,
        train_months=wf_cfg["train_months"], test_months=wf_cfg["test_months"],
        step_months=wf_cfg["step_months"], holdout_start=holdout_start,
    )

    oos_windows = []
    for train_start, train_end, test_start, test_end in windows:
        best_overrides, _train_report = calibrate(price_data, base_params, start=train_start, end=train_end, target=target)
        test_params = build_params_variant(base_params, best_overrides)
        test_result = run_backtest(price_data, test_params, start=test_start, end=test_end)
        test_report = summarize_backtest(test_result, target_monthly_return_pct=target)
        oos_windows.append(
            {
                "train_window": [str(train_start.date()), str(train_end.date())],
                "test_window": [str(test_start.date()), str(test_end.date())],
                "chosen_params": best_overrides,
                "test_report_out_of_sample": test_report,
            }
        )

    # Holdout final: calibra com TODO o historico anterior ao holdout (nunca o holdout em si)
    holdout_overrides, _ = calibrate(price_data, base_params, start=start_date, end=holdout_start, target=target)
    holdout_params = build_params_variant(base_params, holdout_overrides)
    holdout_result = run_backtest(price_data, holdout_params, start=holdout_start, end=end_date)
    holdout_report = summarize_backtest(holdout_result, target_monthly_return_pct=target)

    # Resumo agregado das janelas OOS (o numero mais honesto do projeto)
    oos_cycle_pct_hits = [
        w["test_report_out_of_sample"]["ciclos_rolantes_30d"]["pct_janelas_atingiu_meta"]
        for w in oos_windows
        if w["test_report_out_of_sample"]["ciclos_rolantes_30d"]["pct_janelas_atingiu_meta"] is not None
    ]
    oos_mean_returns = [
        w["test_report_out_of_sample"]["ciclos_rolantes_30d"]["retorno_medio_pct"]
        for w in oos_windows
        if w["test_report_out_of_sample"]["ciclos_rolantes_30d"]["retorno_medio_pct"] is not None
    ]

    summary = {
        "n_janelas_out_of_sample": len(oos_windows),
        "media_pct_ciclos_atingiu_meta_oos": (sum(oos_cycle_pct_hits) / len(oos_cycle_pct_hits)) if oos_cycle_pct_hits else None,
        "media_retorno_medio_por_ciclo_oos_pct": (sum(oos_mean_returns) / len(oos_mean_returns)) if oos_mean_returns else None,
    }

    return {
        "summary": summary,
        "windows": oos_windows,
        "holdout": {
            "window": [str(holdout_start.date()), str(end_date.date())],
            "chosen_params": holdout_overrides,
            "report": holdout_report,
        },
    }
