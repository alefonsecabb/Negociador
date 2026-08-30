"""Carregamento de config/strategy_params.yaml."""
from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STRATEGY_PARAMS_FILE = PROJECT_ROOT / "config" / "strategy_params.yaml"


def load_strategy_params(path: Path = STRATEGY_PARAMS_FILE) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
