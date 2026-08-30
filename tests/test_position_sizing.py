import pytest

from negociador.strategy.position_sizing import PositionSizingParams, can_open_new_position, shares_to_buy


@pytest.fixture
def params():
    return PositionSizingParams(
        risk_per_trade_pct=0.01,
        max_position_pct=0.10,
        max_open_positions=12,
        min_cash_reserve_pct=0.10,
    )


def test_shares_to_buy_respects_risk_budget(params):
    equity = 100_000.0
    # entrada/stop bem distantes (risco por acao alto) para o teto de risco ser o fator limitante,
    # nao o teto de alocacao maxima por posicao (10% = R$10.000 / entrada)
    qty = shares_to_buy(equity, cash_available=equity, entry_price=50.0, stop_price=30.0, params=params)
    # risco = 100_000 * 1% = 1_000 ; risco por acao = 20 -> 50 acoes
    assert qty == 50


def test_shares_to_buy_capped_by_max_allocation(params):
    equity = 100_000.0
    # risco por acao muito pequeno faria a qty por risco ser gigante; o teto de 10% do patrimonio deve prevalecer
    qty = shares_to_buy(equity, cash_available=equity, entry_price=50.0, stop_price=49.9, params=params)
    max_alloc_qty = int((equity * params.max_position_pct) // 50.0)
    assert qty == max_alloc_qty


def test_shares_to_buy_respects_cash_reserve(params):
    equity = 100_000.0
    # caixa disponivel bem menor que o patrimonio (ja alocado em outras posicoes)
    qty = shares_to_buy(equity, cash_available=5_000.0, entry_price=50.0, stop_price=47.0, params=params)
    usable_cash = 5_000.0 - equity * params.min_cash_reserve_pct  # = -5000 -> 0
    assert qty == 0


def test_shares_to_buy_zero_when_stop_above_entry(params):
    qty = shares_to_buy(100_000.0, 100_000.0, entry_price=50.0, stop_price=51.0, params=params)
    assert qty == 0


def test_can_open_new_position(params):
    assert can_open_new_position(11, params) is True
    assert can_open_new_position(12, params) is False
