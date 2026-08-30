"""Converte precos-gatilho (referencia) em precos-limite a digitar no homebroker.

O yfinance tem atraso tipico de dado gratuito (minutos). Para que uma ordem
LIMITADA nao deixe de executar por causa desse atraso, nunca sugerimos o
preco de sinal cru: somamos (compra) ou subtraimos (venda) uma margem de
execucao, proporcional a volatilidade recente do ativo (ATR%).

Ver secao "Preco-limite com margem de execucao" do plano - a mesma logica
vale tanto para a entrada (compra) quanto para o stop-loss e o take-profit
(venda), com margens minimas diferentes por serem assimetricas em risco:
perder um take-profit por 1 tick e aceitavel, nao vender no stop nao e.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OrderSide(str, Enum):
    BUY = "COMPRA"
    SELL = "VENDA"


@dataclass(frozen=True)
class ExecutionMarginParams:
    min_buy_margin_pct: float
    min_sell_margin_pct: float
    min_stop_margin_pct: float
    k_margin_atr: float

    @classmethod
    def from_config(cls, cfg: dict) -> "ExecutionMarginParams":
        return cls(
            min_buy_margin_pct=float(cfg["min_buy_margin_pct"]),
            min_sell_margin_pct=float(cfg["min_sell_margin_pct"]),
            min_stop_margin_pct=float(cfg["min_stop_margin_pct"]),
            k_margin_atr=float(cfg["k_margin_atr"]),
        )


def _margin_pct(min_margin_pct: float, atr_pct: float, params: ExecutionMarginParams) -> float:
    """margem = max(margem_minima, k_margin_atr * ATR%_diario) - nunca menor que o piso configurado."""
    atr_component = params.k_margin_atr * max(atr_pct, 0.0)
    return max(min_margin_pct, atr_component)


def buy_limit_price(reference_price: float, atr_pct: float, params: ExecutionMarginParams) -> float:
    """Preco-limite de COMPRA: acima do preco de referencia, para nao perder a entrada
    caso o preco real ja tenha subido um pouco desde o dado que geramos o alerta."""
    margin = _margin_pct(params.min_buy_margin_pct, atr_pct, params)
    return round(reference_price * (1 + margin), 2)


def stop_loss_limit_price(stop_price: float, atr_pct: float, params: ExecutionMarginParams) -> float:
    """Preco-limite de VENDA (stop-loss): abaixo do stop calculado, para garantir a
    execucao mesmo que o preco ja tenha caido um pouco mais. Margem maior que a
    do take-profit: aqui o custo de nao executar (ficar exposto) e maior que o
    custo de vender um pouco mais barato."""
    margin = _margin_pct(params.min_stop_margin_pct, atr_pct, params)
    return round(stop_price * (1 - margin), 2)


def take_profit_limit_price(take_price: float, atr_pct: float, params: ExecutionMarginParams) -> float:
    """Preco-limite de VENDA (take-profit): levemente abaixo do alvo, margem menor -
    aqui o risco e so "vender um pouco mais barato", nunca "ficar sem vender"."""
    margin = _margin_pct(params.min_sell_margin_pct, atr_pct, params)
    return round(take_price * (1 - margin), 2)
