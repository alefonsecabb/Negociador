"""Indicadores tecnicos implementados em pandas/numpy puro.

Evita depender de TA-Lib (biblioteca C, instalacao notoriamente dificil)
ou de pandas-ta (sinais de manutencao incerta). Cada funcao recebe/devolve
pd.Series alinhadas ao indice do DataFrame de entrada.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder's smoothing (equivalente ao RSI classico)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    out = out.where(avg_loss != 0.0, 100.0)  # sem perdas -> RSI 100
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def bollinger_bands(close: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = sma(close, period)
    std = close.rolling(window=period, min_periods=period).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower})


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = true_range(high, low, close)
    # Wilder's smoothing, o padrao classico do ATR
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def donchian_channel(high: pd.Series, low: pd.Series, period: int = 20) -> pd.DataFrame:
    """Canal de Donchian EXCLUINDO o candle atual (evita usar o proprio maximo/minimo do dia como gatilho)."""
    upper = high.shift(1).rolling(window=period, min_periods=period).max()
    lower = low.shift(1).rolling(window=period, min_periods=period).min()
    return pd.DataFrame({"upper": upper, "lower": lower})


def add_all_indicators(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Recebe um DataFrame OHLCV e devolve uma copia com todas as colunas de indicadores anexadas.

    `params` segue o formato da secao `indicators` de config/strategy_params.yaml.
    """
    out = df.copy()
    p = params
    out["ema_trend"] = ema(out["Close"], p["ema_trend_period"])
    out["volume_ma"] = sma(out["Volume"], p["volume_ma_period"])

    donch = donchian_channel(out["High"], out["Low"], p["donchian_period"])
    out["donchian_upper"] = donch["upper"]
    out["donchian_lower"] = donch["lower"]

    out["rsi"] = rsi(out["Close"], p["rsi_period"])

    bb = bollinger_bands(out["Close"], p["bollinger_period"], p["bollinger_std"])
    out["bb_mid"] = bb["mid"]
    out["bb_upper"] = bb["upper"]
    out["bb_lower"] = bb["lower"]

    macd_df = macd(out["Close"], p["macd_fast"], p["macd_slow"], p["macd_signal"])
    out["macd"] = macd_df["macd"]
    out["macd_signal"] = macd_df["signal"]
    out["macd_hist"] = macd_df["hist"]

    out["atr"] = atr(out["High"], out["Low"], out["Close"], p["atr_period"])
    out["atr_pct"] = out["atr"] / out["Close"]

    return out
