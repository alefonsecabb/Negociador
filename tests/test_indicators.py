import numpy as np
import pandas as pd
import pytest

from negociador.indicators import ta


def test_sma_matches_manual_average():
    s = pd.Series([1, 2, 3, 4, 5, 6], dtype=float)
    result = ta.sma(s, period=3)
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx((1 + 2 + 3) / 3)
    assert result.iloc[5] == pytest.approx((4 + 5 + 6) / 3)


def test_ema_reacts_faster_than_sma_to_recent_move():
    s = pd.Series([10] * 20 + [20] * 5, dtype=float)
    sma_v = ta.sma(s, period=10).iloc[-1]
    ema_v = ta.ema(s, period=10).iloc[-1]
    # EMA da mais peso aos ultimos valores -> deve estar mais perto de 20 que a SMA
    assert ema_v > sma_v


def test_rsi_is_100_when_only_gains():
    s = pd.Series(range(1, 30), dtype=float)  # sobe todo dia, sem perdas
    result = ta.rsi(s, period=14)
    assert result.iloc[-1] == pytest.approx(100.0)


def test_rsi_is_bounded_0_100():
    rng = np.random.default_rng(42)
    s = pd.Series(100 + np.cumsum(rng.normal(0, 1, 200)))
    result = ta.rsi(s, period=14).dropna()
    assert (result >= 0).all() and (result <= 100).all()


def test_macd_histogram_is_macd_minus_signal():
    rng = np.random.default_rng(1)
    s = pd.Series(100 + np.cumsum(rng.normal(0, 1, 100)))
    out = ta.macd(s, fast=12, slow=26, signal=9)
    diff = (out["hist"] - (out["macd"] - out["signal"])).dropna()
    assert (diff.abs() < 1e-9).all()


def test_bollinger_bands_upper_above_lower():
    rng = np.random.default_rng(2)
    s = pd.Series(100 + np.cumsum(rng.normal(0, 1, 100)))
    bb = ta.bollinger_bands(s, period=20, num_std=2.0)
    valid = bb.dropna()
    assert (valid["upper"] >= valid["mid"]).all()
    assert (valid["mid"] >= valid["lower"]).all()


def test_atr_is_nonnegative():
    high = pd.Series([10, 11, 12, 11, 13, 14, 12, 15], dtype=float)
    low = pd.Series([9, 9.5, 10, 10, 11, 12, 11, 12], dtype=float)
    close = pd.Series([9.5, 10.5, 11, 10.5, 12, 13, 11.5, 14], dtype=float)
    result = ta.atr(high, low, close, period=3).dropna()
    assert (result >= 0).all()


def test_donchian_channel_excludes_current_bar():
    high = pd.Series([1, 2, 3, 100, 4], dtype=float)
    low = pd.Series([1, 2, 3, 0.01, 4], dtype=float)
    donch = ta.donchian_channel(high, low, period=3)
    # no candle do pico (indice 3), o canal deve refletir os 3 candles ANTERIORES (1,2,3), nao o proprio 100/0.01
    assert donch["upper"].iloc[3] == pytest.approx(3.0)
    assert donch["lower"].iloc[3] == pytest.approx(1.0)


def test_add_all_indicators_produces_expected_columns():
    idx = pd.date_range("2024-01-01", periods=150, freq="B")
    rng = np.random.default_rng(3)
    close = 30 + np.cumsum(rng.normal(0, 0.5, len(idx)))
    df = pd.DataFrame(
        {
            "Open": close + rng.normal(0, 0.1, len(idx)),
            "High": close + np.abs(rng.normal(0, 0.3, len(idx))),
            "Low": close - np.abs(rng.normal(0, 0.3, len(idx))),
            "Close": close,
            "Volume": rng.integers(1000, 100000, len(idx)),
        },
        index=idx,
    )
    params = {
        "ema_trend_period": 20, "donchian_period": 10, "volume_ma_period": 10,
        "rsi_period": 14, "bollinger_period": 20, "bollinger_std": 2.0,
        "macd_fast": 12, "macd_slow": 26, "macd_signal": 9, "atr_period": 14,
    }
    out = ta.add_all_indicators(df, params)
    expected_cols = {
        "ema_trend", "volume_ma", "donchian_upper", "donchian_lower", "rsi",
        "bb_mid", "bb_upper", "bb_lower", "macd", "macd_signal", "macd_hist",
        "atr", "atr_pct",
    }
    assert expected_cols.issubset(out.columns)
    assert len(out) == len(df)
