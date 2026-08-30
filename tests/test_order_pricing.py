import pytest

from negociador.strategy.order_pricing import (
    ExecutionMarginParams,
    buy_limit_price,
    stop_loss_limit_price,
    take_profit_limit_price,
)


@pytest.fixture
def params():
    return ExecutionMarginParams(
        min_buy_margin_pct=0.003,
        min_sell_margin_pct=0.002,
        min_stop_margin_pct=0.004,
        k_margin_atr=0.12,
    )


def test_buy_limit_is_above_reference(params):
    ref = 50.0
    limit = buy_limit_price(ref, atr_pct=0.01, params=params)
    assert limit > ref


def test_buy_limit_uses_minimum_when_atr_small(params):
    ref = 100.0
    limit = buy_limit_price(ref, atr_pct=0.0001, params=params)  # ATR desprezivel -> usa o piso
    assert limit == pytest.approx(ref * 1.003, rel=1e-6)


def test_buy_limit_scales_with_volatility(params):
    ref = 100.0
    low_vol = buy_limit_price(ref, atr_pct=0.01, params=params)
    high_vol = buy_limit_price(ref, atr_pct=0.05, params=params)
    assert high_vol > low_vol


def test_stop_loss_limit_is_below_stop(params):
    stop = 47.0
    limit = stop_loss_limit_price(stop, atr_pct=0.02, params=params)
    assert limit < stop


def test_take_profit_limit_is_below_take_but_smaller_margin_than_stop(params):
    take = 60.0
    stop = 47.0
    take_limit = take_profit_limit_price(take, atr_pct=0.02, params=params)
    stop_limit = stop_loss_limit_price(stop, atr_pct=0.02, params=params)
    assert take_limit < take
    # margem do stop deve ser proporcionalmente maior que a do take (min_stop > min_sell)
    stop_margin = 1 - stop_limit / stop
    take_margin = 1 - take_limit / take
    assert stop_margin > take_margin
