"""Custos de mercado e imposto de renda para swing trade de acoes na B3 (pessoa fisica).

Regras implementadas (validadas em 30/08/2026 contra B3 e Receita Federal):

- Emolumentos B3: 0,0300% do valor de cada operacao (compra e venda separadamente).
- Corretagem: valor fixo parametrizavel por ordem (padrao R$0, refletindo
  corretoras "zero-fee" comuns hoje - ajustavel para a corretora real do usuario).
- IR: apurado por MES CALENDARIO. Se a soma das VENDAS (valor bruto alienado,
  nao o lucro) do mes for < R$20.000, o ganho liquido do mes fica ISENTO.
  Caso contrario, incide 15% sobre o ganho liquido do mes inteiro (nao so o
  excedente). Prejuizos apurados em qualquer mes (independente do volume de
  vendas) sao acumulados e compensam lucros de meses futuros, sem prazo de
  validade.

Simplificacao assumida (documentada, e irrelevante para validar a META
MENSAL): o imposto de um mes e debitado da carteira no fechamento do
proprio mes, e nao no mes seguinte (quando a DARF de fato venceria).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True)
class CostParams:
    b3_emolument_pct: float
    brokerage_fee_brl: float
    income_tax_pct: float
    income_tax_exempt_sales_brl: float

    @classmethod
    def from_config(cls, cfg: dict) -> "CostParams":
        return cls(
            b3_emolument_pct=float(cfg["b3_emolument_pct"]),
            brokerage_fee_brl=float(cfg["brokerage_fee_brl"]),
            income_tax_pct=float(cfg["income_tax_pct"]),
            income_tax_exempt_sales_brl=float(cfg["income_tax_exempt_sales_brl"]),
        )


def order_cost(trade_value: float, params: CostParams) -> float:
    """Custo de uma unica ordem (compra OU venda): emolumentos + corretagem fixa."""
    return trade_value * params.b3_emolument_pct + params.brokerage_fee_brl


@dataclass
class MonthTaxState:
    year_month: str
    sales_total: float = 0.0
    net_profit: float = 0.0  # lucro/prejuizo das vendas fechadas no mes, ANTES do IR (mas apos emolumentos/corretagem)


@dataclass
class TaxTracker:
    """Apura o IR mensal de swing trade, mes a mes, com compensacao de prejuizo acumulado."""

    params: CostParams
    loss_carryforward: float = 0.0
    current_month: MonthTaxState | None = None
    history: list[dict] = field(default_factory=list)

    def record_sale(self, date: pd.Timestamp, sale_value: float, trade_pnl: float) -> float:
        """Registra uma venda (fechamento de posicao). Se isso encerra o mes
        corrente (a venda e do mes seguinte ao acumulado), fecha o mes anterior,
        calcula o IR devido e o retorna (para ser debitado da carteira);
        caso contrario, retorna 0.0 (imposto ainda nao apurado)."""
        month_key = date.strftime("%Y-%m")
        tax_due = 0.0
        if self.current_month is None:
            self.current_month = MonthTaxState(year_month=month_key)
        elif month_key != self.current_month.year_month:
            tax_due = self._close_month(self.current_month)
            self.current_month = MonthTaxState(year_month=month_key)

        self.current_month.sales_total += sale_value
        self.current_month.net_profit += trade_pnl
        return tax_due

    def finalize(self) -> float:
        """Fecha o ultimo mes em aberto (chamar ao final do backtest)."""
        if self.current_month is None:
            return 0.0
        tax_due = self._close_month(self.current_month)
        self.current_month = None
        return tax_due

    def roll_to_date(self, date: pd.Timestamp) -> float:
        """Fecha o mes corrente SE `date` ja estiver num mes seguinte, mesmo sem
        nenhuma venda nova ainda registrada nesse novo mes. Usado pelo motor ao
        vivo (que roda continuamente, sem um "fim do backtest" natural): sem
        isso, o IR de um mes so seria apurado quando a PROXIMA venda acontecesse,
        que pode ser semanas depois do mes ter de fato fechado."""
        if self.current_month is None:
            return 0.0
        month_key = date.strftime("%Y-%m")
        if month_key == self.current_month.year_month:
            return 0.0
        tax_due = self._close_month(self.current_month)
        self.current_month = None
        return tax_due

    def _close_month(self, month: MonthTaxState) -> float:
        tax_due = 0.0
        if month.net_profit < 0:
            self.loss_carryforward += -month.net_profit
        elif month.sales_total >= self.params.income_tax_exempt_sales_brl:
            taxable = max(month.net_profit - self.loss_carryforward, 0.0)
            used_loss = min(month.net_profit, self.loss_carryforward)
            self.loss_carryforward -= used_loss
            tax_due = taxable * self.params.income_tax_pct
        # se sales_total < isencao e profit >= 0: isento, prejuizo acumulado preservado

        self.history.append(
            {
                "year_month": month.year_month,
                "sales_total": month.sales_total,
                "net_profit": month.net_profit,
                "tax_due": tax_due,
                "loss_carryforward_after": self.loss_carryforward,
                "exempt": month.sales_total < self.params.income_tax_exempt_sales_brl,
            }
        )
        return tax_due

    def to_state_dict(self) -> dict:
        """Serializa o estado mutavel (para persistir em sqlite entre execucoes do
        monitor ao vivo - o GitHub Actions roda em containers efemeros)."""
        return {
            "loss_carryforward": self.loss_carryforward,
            "current_month": self.current_month.year_month if self.current_month else None,
            "month_sales_total": self.current_month.sales_total if self.current_month else 0.0,
            "month_net_profit": self.current_month.net_profit if self.current_month else 0.0,
        }

    @classmethod
    def from_state_dict(cls, params: CostParams, state: dict) -> "TaxTracker":
        tracker = cls(params=params, loss_carryforward=float(state.get("loss_carryforward", 0.0)))
        if state.get("current_month"):
            tracker.current_month = MonthTaxState(
                year_month=state["current_month"],
                sales_total=float(state.get("month_sales_total", 0.0)),
                net_profit=float(state.get("month_net_profit", 0.0)),
            )
        return tracker
