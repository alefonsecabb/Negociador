import pandas as pd
import pytest

from negociador.backtest.costs import CostParams, TaxTracker, order_cost


@pytest.fixture
def params():
    return CostParams(
        b3_emolument_pct=0.0003,
        brokerage_fee_brl=0.0,
        income_tax_pct=0.15,
        income_tax_exempt_sales_brl=20_000.0,
    )


def test_order_cost_is_emolument_plus_brokerage(params):
    cost = order_cost(10_000.0, params)
    assert cost == pytest.approx(10_000.0 * 0.0003)


def test_tax_exempt_when_sales_below_threshold(params):
    tracker = TaxTracker(params=params)
    tracker.record_sale(pd.Timestamp("2024-01-10"), sale_value=5_000.0, trade_pnl=1_000.0)
    tax = tracker.finalize()
    assert tax == 0.0
    assert tracker.history[-1]["exempt"] is True


def test_tax_charged_when_sales_above_threshold(params):
    tracker = TaxTracker(params=params)
    tracker.record_sale(pd.Timestamp("2024-01-10"), sale_value=25_000.0, trade_pnl=2_000.0)
    tax = tracker.finalize()
    assert tax == pytest.approx(2_000.0 * 0.15)


def test_loss_carries_forward_and_offsets_future_profit(params):
    tracker = TaxTracker(params=params)
    # mes 1: prejuizo de 1000 (independente do volume de vendas)
    tracker.record_sale(pd.Timestamp("2024-01-10"), sale_value=30_000.0, trade_pnl=-1_000.0)
    # mes 2: lucro de 3000, vendas acima do limite -> tributavel, mas compensa o prejuizo do mes 1
    tax_due_at_month2_start = tracker.record_sale(pd.Timestamp("2024-02-10"), sale_value=25_000.0, trade_pnl=3_000.0)
    tax = tracker.finalize()
    # imposto so sobre 3000 - 1000 = 2000
    assert tax == pytest.approx(2_000.0 * 0.15)
    assert tracker.loss_carryforward == pytest.approx(0.0)


def test_exempt_month_preserves_loss_carryforward(params):
    tracker = TaxTracker(params=params)
    tracker.record_sale(pd.Timestamp("2024-01-10"), sale_value=30_000.0, trade_pnl=-1_000.0)
    # mes 2: lucro mas vendas abaixo do limite -> isento, prejuizo NAO deve ser consumido
    tracker.record_sale(pd.Timestamp("2024-02-10"), sale_value=5_000.0, trade_pnl=500.0)
    tracker.finalize()
    assert tracker.loss_carryforward == pytest.approx(1_000.0)
