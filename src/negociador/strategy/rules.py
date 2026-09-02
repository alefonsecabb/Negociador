"""Regras de entrada/saida da estrategia de swing trade (long-only).

Duas variantes, escolhidas por `strategy_variant` em strategy_params.yaml:

- trend_breakout: preco acima da EMA de longo prazo (filtro de tendencia) +
  rompimento do canal de Donchian (maxima de N dias) com volume acima da media.
- mean_reversion: mesmo filtro de tendencia + RSI saindo de sobrevenda ou
  toque na banda inferior de Bollinger, com confirmacao de cruzamento do MACD.

As funcoes aqui operam sobre uma linha (Series) do DataFrame ja enriquecido
por `indicators.ta.add_all_indicators`, e sao usadas tanto pelo motor de
backtest (backtest/engine.py) quanto pelo monitor ao vivo (live/monitor.py) -
uma unica implementacao das regras, para nunca haver divergencia entre o
que foi validado no backtest e o que roda ao vivo.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


@dataclass(frozen=True)
class RiskParams:
    atr_stop_multiple: float
    reward_risk_ratio: float
    breakeven_after_r: float
    max_holding_days: int

    @classmethod
    def from_config(cls, risk_cfg: dict) -> "RiskParams":
        return cls(
            atr_stop_multiple=float(risk_cfg["atr_stop_multiple"]),
            reward_risk_ratio=float(risk_cfg["reward_risk_ratio"]),
            breakeven_after_r=float(risk_cfg.get("breakeven_after_r", 0.0)),
            max_holding_days=int(risk_cfg["max_holding_days"]),
        )


class ExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TIME_EXIT = "SAIDA_POR_TEMPO"


def compute_stop_take(entry_price: float, atr_value: float, risk: RiskParams) -> tuple[float, float]:
    """Calcula stop-loss e take-profit a partir do ATR no momento da entrada.

    stop = entrada - k*ATR ; take = entrada + k*RR*ATR
    """
    stop = entry_price - risk.atr_stop_multiple * atr_value
    take = entry_price + risk.atr_stop_multiple * risk.reward_risk_ratio * atr_value
    return max(stop, 0.01), take


def apply_breakeven(entry_price: float, current_stop: float, high_since_entry: float, atr_at_entry: float, risk: RiskParams) -> float:
    """Move o stop para o preco de entrada (breakeven) apos atingir `breakeven_after_r` de lucro (em R = risco inicial)."""
    if risk.breakeven_after_r <= 0:
        return current_stop
    initial_risk = entry_price - (entry_price - risk.atr_stop_multiple * atr_at_entry)
    if initial_risk <= 0:
        return current_stop
    profit_in_r = (high_since_entry - entry_price) / initial_risk
    if profit_in_r >= risk.breakeven_after_r and current_stop < entry_price:
        return entry_price
    return current_stop


def _trend_filter(row: pd.Series) -> bool:
    return pd.notna(row.get("ema_trend")) and row["Close"] > row["ema_trend"]


def check_entry_trend_breakout(row: pd.Series) -> bool:
    """Rompimento de Donchian com volume acima da media, com filtro de tendencia."""
    if not _trend_filter(row):
        return False
    if pd.isna(row.get("donchian_upper")) or pd.isna(row.get("volume_ma")):
        return False
    breakout = row["Close"] > row["donchian_upper"]
    volume_confirms = row["Volume"] > row["volume_ma"]
    return bool(breakout and volume_confirms)


def check_entry_mean_reversion(row: pd.Series, prev_row: pd.Series) -> bool:
    """RSI saindo de sobrevenda (ou toque na banda inferior) + MACD cruzando para cima."""
    if not _trend_filter(row):
        return False
    required = ["rsi", "bb_lower", "macd", "macd_signal"]
    if any(pd.isna(row.get(c)) for c in required) or any(pd.isna(prev_row.get(c)) for c in required):
        return False

    rsi_recovering = prev_row["rsi"] < 30 <= row["rsi"]
    touched_lower_band = row["Low"] <= row["bb_lower"]
    macd_cross_up = prev_row["macd"] <= prev_row["macd_signal"] and row["macd"] > row["macd_signal"]

    return bool((rsi_recovering or touched_lower_band) and macd_cross_up)


def check_entry(row: pd.Series, prev_row: pd.Series, variant: str) -> bool:
    if variant == "trend_breakout":
        return check_entry_trend_breakout(row)
    if variant == "mean_reversion":
        return check_entry_mean_reversion(row, prev_row)
    raise ValueError(f"strategy_variant desconhecida: {variant!r}")


def fill_price_for_level(row: pd.Series, level_price: float, side: str) -> float:
    """Preco de preenchimento realista quando um stop/take e atingido num candle.

    Se o candle ABRE alem do nivel (gap), assume-se preenchimento no Open - pior
    preco para o stop, melhor preco para o take, ambos realistas. Caso contrario,
    preenche exatamente no nivel. Usada tanto pelo motor de backtest quanto pelo
    monitor ao vivo (saidas automaticas), para nao haver divergencia de preco de
    saida entre o que foi validado e o que roda ao vivo.
    """
    open_ = float(row["Open"])
    if side == "stop":
        return open_ if open_ <= level_price else level_price
    return open_ if open_ >= level_price else level_price  # "take"


def check_exit(
    row: pd.Series,
    stop_price: float,
    take_price: float,
    holding_days: int,
    max_holding_days: int,
) -> ExitReason | None:
    """Verifica, num candle D+1 (ou seguinte), se stop/take/tempo foram atingidos.

    Regra de desempate conservadora: se o candle toca stop E take no mesmo dia,
    assume-se que o stop foi atingido primeiro.
    """
    hit_stop = row["Low"] <= stop_price
    hit_take = row["High"] >= take_price
    if hit_stop:
        return ExitReason.STOP_LOSS
    if hit_take:
        return ExitReason.TAKE_PROFIT
    if holding_days >= max_holding_days:
        return ExitReason.TIME_EXIT
    return None
