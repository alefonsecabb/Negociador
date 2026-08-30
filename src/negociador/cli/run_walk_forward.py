"""CLI: roda a validacao walk-forward + holdout final e grava o relatorio.

Ao final, sobrescreve config/strategy_params.yaml com os parametros
vencedores calibrados sobre o periodo anterior ao holdout (os mesmos usados
para produzir o resultado do holdout) - esses passam a ser os parametros
"correntes" do modelo, usados pelo monitor ao vivo.

Uso:
    python -m negociador.cli.run_walk_forward
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from negociador.backtest.walk_forward import run_walk_forward
from negociador.cli.run_backtest import load_price_data_with_indicators
from negociador.config import STRATEGY_PARAMS_FILE, load_strategy_params
from negociador.universe import load_universe

# Chave calibravel -> regex do campo correspondente em strategy_params.yaml.
# Atualiza so o VALOR de cada linha via substituicao de texto, preservando
# comentarios e o resto do arquivo (yaml.safe_dump reescreveria tudo sem
# comentarios, o que degradaria a documentacao do arquivo de config).
_YAML_FIELD_PATTERN = {
    "atr_stop_multiple": r"(atr_stop_multiple:\s*)[\d.]+",
    "reward_risk_ratio": r"(reward_risk_ratio:\s*)[\d.]+",
    "risk_per_trade_pct": r"(risk_per_trade_pct:\s*)[\d.]+",
}


def _update_yaml_values_preserving_comments(path: Path, overrides: dict) -> None:
    text = path.read_text(encoding="utf-8")
    for key, value in overrides.items():
        pattern = _YAML_FIELD_PATTERN[key]
        text, n = re.subn(pattern, lambda m: f"{m.group(1)}{value}", text, count=1)
        if n == 0:
            raise ValueError(f"Nao encontrei o campo '{key}' em {path} para atualizar.")
    path.write_text(text, encoding="utf-8")

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPORTS_DIR = PROJECT_ROOT / "reports"


def main() -> None:
    params = load_strategy_params()
    tickers = load_universe()
    print(f"Carregando cache de {len(tickers)} ticker(s) e calculando indicadores...")
    price_data = load_price_data_with_indicators(tickers, params)
    print(f"{len(price_data)}/{len(tickers)} tickers com historico suficiente.")

    t0 = time.time()
    result = run_walk_forward(price_data, params)
    elapsed = time.time() - t0
    print(f"\nWalk-forward concluido em {elapsed/60:.1f} min.")

    s = result["summary"]
    print(f"\n=== Resumo out-of-sample ({s['n_janelas_out_of_sample']} janelas) ===")
    print(f"Media de % de ciclos que atingiram a meta (OOS): {s['media_pct_ciclos_atingiu_meta_oos']}")
    print(f"Media do retorno medio por ciclo (OOS): {s['media_retorno_medio_por_ciclo_oos_pct']}")

    for w in result["windows"]:
        c = w["test_report_out_of_sample"]["ciclos_rolantes_30d"]
        print(
            f"  treino {w['train_window']} -> teste {w['test_window']} | "
            f"params={w['chosen_params']} | % ciclos>=meta OOS={c['pct_janelas_atingiu_meta']} | "
            f"retorno medio OOS={c['retorno_medio_pct']}"
        )

    h = result["holdout"]
    hc = h["report"]["ciclos_rolantes_30d"]
    print(f"\n=== Holdout final {h['window']} (nunca tocado na calibracao) ===")
    print(f"Parametros escolhidos: {h['chosen_params']}")
    print(f"% de ciclos >= meta no holdout: {hc['pct_janelas_atingiu_meta']}")
    print(f"Retorno medio por ciclo no holdout: {hc['retorno_medio_pct']}")
    print(f"Drawdown maximo no holdout: {h['report']['risco']['drawdown_maximo_pct']}")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / "walk_forward_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nRelatorio completo salvo em {out_path}")

    # Os parametros do holdout (calibrados sobre todo o historico anterior a ele,
    # a janela de dados mais recente e mais representativa disponivel) viram o
    # padrao "corrente" do modelo em strategy_params.yaml - atualizando so os
    # valores calibrados, preservando comentarios e o resto do arquivo.
    _update_yaml_values_preserving_comments(STRATEGY_PARAMS_FILE, h["chosen_params"])
    print(f"config/strategy_params.yaml atualizado com os parametros calibrados: {h['chosen_params']}")


if __name__ == "__main__":
    main()
