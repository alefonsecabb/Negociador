"""Dimensionamento de posicao (position sizing) para a carteira ficticia."""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class PositionSizingParams:
    risk_per_trade_pct: float
    max_position_pct: float
    max_open_positions: int
    min_cash_reserve_pct: float

    @classmethod
    def from_config(cls, cfg: dict) -> "PositionSizingParams":
        return cls(
            risk_per_trade_pct=float(cfg["risk_per_trade_pct"]),
            max_position_pct=float(cfg["max_position_pct"]),
            max_open_positions=int(cfg["max_open_positions"]),
            min_cash_reserve_pct=float(cfg["min_cash_reserve_pct"]),
        )


def shares_to_buy(
    equity: float,
    cash_available: float,
    entry_price: float,
    stop_price: float,
    params: PositionSizingParams,
    lot_size: int = 1,
) -> int:
    """Calcula a quantidade de acoes a comprar dado o risco por operacao.

    risco_em_reais = equity * risk_per_trade_pct
    quantidade = risco_em_reais / (entrada - stop), limitada por:
      - teto de alocacao por posicao (max_position_pct do patrimonio)
      - caixa disponivel (respeitando a reserva minima)
      - lot_size (tamanho do lote; 1 para permitir fracionario)
    """
    if entry_price <= stop_price:
        return 0

    risk_per_share = entry_price - stop_price
    risk_budget = equity * params.risk_per_trade_pct
    qty_by_risk = risk_budget / risk_per_share

    max_alloc = equity * params.max_position_pct
    qty_by_alloc = max_alloc / entry_price

    usable_cash = max(cash_available - equity * params.min_cash_reserve_pct, 0.0)
    qty_by_cash = usable_cash / entry_price

    qty = min(qty_by_risk, qty_by_alloc, qty_by_cash)
    qty = math.floor(qty / lot_size) * lot_size
    return max(int(qty), 0)


def can_open_new_position(open_positions_count: int, params: PositionSizingParams) -> bool:
    return open_positions_count < params.max_open_positions
