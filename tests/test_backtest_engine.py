import pandas as pd
import pytest

from negociador.backtest.engine import run_backtest


def make_ticker_df(rows: list[dict], start_date: str = "2024-01-02") -> pd.DataFrame:
    idx = pd.bdate_range(start=start_date, periods=len(rows))
    df = pd.DataFrame(rows, index=idx)
    return df


BASE_PARAMS = {
    "strategy_variant": "trend_breakout",
    "risk": {
        "atr_stop_multiple": 2.0,
        "reward_risk_ratio": 2.0,
        "breakeven_after_r": 0.0,
        "max_holding_days": 20,
    },
    "position_sizing": {
        "risk_per_trade_pct": 0.01,
        "max_position_pct": 0.5,
        "max_open_positions": 5,
        "min_cash_reserve_pct": 0.0,
    },
    "costs": {
        "b3_emolument_pct": 0.0,
        "brokerage_fee_brl": 0.0,
        "income_tax_pct": 0.15,
        "income_tax_exempt_sales_brl": 20_000.0,
    },
    "capital_inicial": 100_000.0,
}


def test_entry_executes_next_day_open_not_same_day_close():
    # dia0: sem sinal (abaixo do canal); dia1: fecha acima do canal com volume -> sinal;
    # dia2: deve abrir a posicao no OPEN (nao no close do dia1)
    rows = [
        dict(Open=10.0, High=10.2, Low=9.8, Close=10.0, Volume=1000,
             ema_trend=9.0, donchian_upper=10.5, volume_ma=900, atr=0.5),
        dict(Open=10.1, High=11.2, Low=10.0, Close=11.0, Volume=1200,
             ema_trend=9.0, donchian_upper=10.5, volume_ma=900, atr=0.5),
        dict(Open=11.2, High=11.5, Low=11.0, Close=11.3, Volume=1100,
             ema_trend=9.0, donchian_upper=10.5, volume_ma=900, atr=0.5),
        dict(Open=11.3, High=11.6, Low=11.1, Close=11.4, Volume=1000,
             ema_trend=9.0, donchian_upper=10.5, volume_ma=900, atr=0.5),
    ]
    df = make_ticker_df(rows)
    result = run_backtest({"TEST1": df}, BASE_PARAMS)

    # sinal fecha no dia1 (indice 1) -> no proprio dia1 o patrimonio ainda deve ser
    # 100% caixa (nenhuma posicao aberta usando o CLOSE do dia1 como preco de entrada)
    assert result.equity_curve.iloc[1] == pytest.approx(BASE_PARAMS["capital_inicial"])
    # execucao so no dia2 (indice 2), no OPEN de 11.2: qty=1000 acoes (risco de 1% / R$1 de risco por acao)
    # cash cai para 88800 e o patrimonio do dia2 e marcado pelo CLOSE do dia2 (11.3), nao pelo preco de entrada
    assert result.final_cash == pytest.approx(88_800.0)
    assert result.equity_curve.iloc[2] == pytest.approx(88_800.0 + 1000 * 11.3)


def test_take_profit_exit_uses_target_price_when_no_gap():
    rows = [
        dict(Open=10.0, High=10.2, Low=9.8, Close=10.0, Volume=1000,
             ema_trend=9.0, donchian_upper=10.5, volume_ma=900, atr=0.5),
        dict(Open=10.1, High=11.2, Low=10.0, Close=11.0, Volume=1200,
             ema_trend=9.0, donchian_upper=10.5, volume_ma=900, atr=0.5),
        # entrada no Open=11.2 -> stop=11.2-2*0.5=10.2 ; take=11.2+2*2*0.5=13.2
        dict(Open=11.2, High=11.5, Low=11.0, Close=11.3, Volume=1100,
             ema_trend=9.0, donchian_upper=10.5, volume_ma=900, atr=0.5),
        dict(Open=11.3, High=11.6, Low=11.1, Close=11.4, Volume=1000,
             ema_trend=9.0, donchian_upper=10.5, volume_ma=900, atr=0.5),
        # High atinge o take (13.2), Open (13.0) nao ultrapassa o alvo -> preenche no preco-alvo, nao no Open
        dict(Open=13.0, High=14.0, Low=12.8, Close=13.5, Volume=1000,
             ema_trend=9.0, donchian_upper=10.5, volume_ma=900, atr=0.5),
    ]
    df = make_ticker_df(rows)
    result = run_backtest({"TEST1": df}, BASE_PARAMS)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "TAKE_PROFIT"
    assert trade.exit_price == pytest.approx(13.2)
    assert trade.net_pnl > 0


def test_stop_loss_exit_fills_at_open_on_gap_down():
    rows = [
        dict(Open=10.0, High=10.2, Low=9.8, Close=10.0, Volume=1000,
             ema_trend=9.0, donchian_upper=10.5, volume_ma=900, atr=0.5),
        dict(Open=10.1, High=11.2, Low=10.0, Close=11.0, Volume=1200,
             ema_trend=9.0, donchian_upper=10.5, volume_ma=900, atr=0.5),
        # entrada no Open=11.2 -> stop=10.2
        dict(Open=11.2, High=11.5, Low=11.0, Close=11.3, Volume=1100,
             ema_trend=9.0, donchian_upper=10.5, volume_ma=900, atr=0.5),
        # gap para baixo: abre em 9.5, ja abaixo do stop de 10.2 -> preenche no Open (pior preco), nao no stop
        dict(Open=9.5, High=9.8, Low=9.0, Close=9.4, Volume=1000,
             ema_trend=9.0, donchian_upper=10.5, volume_ma=900, atr=0.5),
    ]
    df = make_ticker_df(rows)
    result = run_backtest({"TEST1": df}, BASE_PARAMS)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "STOP_LOSS"
    assert trade.exit_price == pytest.approx(9.5)
    assert trade.net_pnl < 0


def test_time_exit_forces_close_after_max_holding_days():
    params = {**BASE_PARAMS, "risk": {**BASE_PARAMS["risk"], "max_holding_days": 2}}
    rows = [
        dict(Open=10.0, High=10.2, Low=9.8, Close=10.0, Volume=1000,
             ema_trend=9.0, donchian_upper=10.5, volume_ma=900, atr=0.5),
        dict(Open=10.1, High=11.2, Low=10.0, Close=11.0, Volume=1200,
             ema_trend=9.0, donchian_upper=10.5, volume_ma=900, atr=0.5),
        # entrada no Open=11.2; dias seguintes ficam parados, sem tocar stop/take
        dict(Open=11.2, High=11.3, Low=11.1, Close=11.2, Volume=1100,
             ema_trend=9.0, donchian_upper=10.5, volume_ma=900, atr=0.5),
        dict(Open=11.2, High=11.3, Low=11.1, Close=11.2, Volume=1000,
             ema_trend=9.0, donchian_upper=10.5, volume_ma=900, atr=0.5),
        dict(Open=11.2, High=11.3, Low=11.1, Close=11.2, Volume=1000,
             ema_trend=9.0, donchian_upper=10.5, volume_ma=900, atr=0.5),
    ]
    df = make_ticker_df(rows)
    result = run_backtest({"TEST1": df}, params)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "SAIDA_POR_TEMPO"


def test_equity_curve_covers_full_date_range():
    rows = [
        dict(Open=10.0, High=10.2, Low=9.8, Close=10.0, Volume=1000,
             ema_trend=11.0, donchian_upper=10.5, volume_ma=900, atr=0.5)  # tendencia contra -> nunca entra
        for _ in range(5)
    ]
    df = make_ticker_df(rows)
    result = run_backtest({"TEST1": df}, BASE_PARAMS)
    assert len(result.trades) == 0
    assert len(result.equity_curve) == len(df)
    assert (result.equity_curve == BASE_PARAMS["capital_inicial"]).all()
