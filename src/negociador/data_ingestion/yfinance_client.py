"""Wrapper fino sobre yfinance com retry e normalizacao de colunas.

O yfinance, dependendo da versao/forma de chamada, pode devolver colunas
com MultiIndex (nivel "Ticker"). Este modulo sempre devolve um DataFrame
"achatado" com colunas: Open, High, Low, Close, Volume e indice de datas
(tz-naive, em dias para dados diarios).
"""
from __future__ import annotations

import logging
import time

import pandas as pd
import yfinance as yf

from negociador.universe import to_yfinance_symbol

logger = logging.getLogger(__name__)

OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        # normalmente (campo, ticker) -> mantem so o campo
        df = df.copy()
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df


def fetch_history(
    ticker: str,
    start: str | None = None,
    end: str | None = None,
    period: str | None = None,
    interval: str = "1d",
    max_retries: int = 3,
    retry_delay_s: float = 2.0,
) -> pd.DataFrame:
    """Busca historico OHLCV para um ticker B3 (sem sufixo .SA).

    Use `start`/`end` para uma janela especifica, ou `period` (ex. "5y")
    para uma janela relativa a hoje. Retorna DataFrame vazio (nao levanta
    excecao) se todas as tentativas falharem - quem chama decide o que
    fazer (pular o ticker, logar, etc).
    """
    symbol = to_yfinance_symbol(ticker)
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            kwargs = dict(interval=interval, auto_adjust=True, progress=False)
            if period:
                kwargs["period"] = period
            else:
                kwargs["start"] = start
                kwargs["end"] = end
            df = yf.download(symbol, **kwargs)
            df = _flatten_columns(df)
            if df.empty:
                logger.warning("Historico vazio para %s (tentativa %d/%d).", symbol, attempt, max_retries)
            else:
                df = df[[c for c in OHLCV_COLUMNS if c in df.columns]].copy()
                df.index = pd.to_datetime(df.index).tz_localize(None)
                df.index.name = "date"
                return df
        except Exception as exc:  # yfinance pode levantar varios tipos de erro de rede/parsing
            last_exc = exc
            logger.warning("Falha ao buscar %s (tentativa %d/%d): %s", symbol, attempt, max_retries, exc)
        if attempt < max_retries:
            time.sleep(retry_delay_s * attempt)
    if last_exc:
        logger.error("Desistindo de buscar %s apos %d tentativas.", symbol, max_retries)
    return pd.DataFrame(columns=OHLCV_COLUMNS)


def fetch_last_quote(ticker: str) -> dict | None:
    """Busca a cotacao mais recente disponivel (pode ter atraso de minutos).

    Retorna um dict com price/high/low/open/volume/as_of, ou None se falhar.
    Usa dados intradiarios de curto periodo (mais proximos do "agora" que o
    fechamento diario).
    """
    df = fetch_history(ticker, period="5d", interval="15m")
    if df.empty:
        # fallback: tenta diario (mercado pode estar fechado ou intraday indisponivel)
        df = fetch_history(ticker, period="5d", interval="1d")
    if df.empty:
        return None
    last = df.iloc[-1]
    return {
        "price": float(last["Close"]),
        "open": float(last["Open"]),
        "high": float(last["High"]),
        "low": float(last["Low"]),
        "volume": float(last["Volume"]),
        "as_of": df.index[-1].isoformat(),
    }


def fetch_today_bar(ticker: str) -> dict | None:
    """Agrega os candles intradiarios do dia corrente num unico bar OHLCV
    "hoje ate agora" (Open do 1o candle, High/Low extremos, Close do ultimo,
    Volume somado). Usado pelo monitor ao vivo para avaliar as regras de
    entrada/saida com o dado mais atual disponivel, sem esperar o fechamento.

    Retorna None se nao houver dado intradiario disponivel (ex. mercado fechado
    ha muito tempo, ou falha da fonte).
    """
    df = fetch_history(ticker, period="5d", interval="15m")
    if df.empty:
        return None
    last_session_date = df.index[-1].date()
    today_rows = df[df.index.date == last_session_date]
    if today_rows.empty:
        return None
    return {
        "date": last_session_date.isoformat(),
        "Open": float(today_rows["Open"].iloc[0]),
        "High": float(today_rows["High"].max()),
        "Low": float(today_rows["Low"].min()),
        "Close": float(today_rows["Close"].iloc[-1]),
        "Volume": float(today_rows["Volume"].sum()),
        "as_of": df.index[-1].isoformat(),
    }
