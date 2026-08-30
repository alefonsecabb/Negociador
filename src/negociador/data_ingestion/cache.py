"""Cache local (parquet) do historico OHLCV, por ticker, com update incremental."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from negociador.data_ingestion.yfinance_client import fetch_history

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "prices"

DEFAULT_BACKFILL_PERIOD = "8y"


def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker.upper()}.parquet"


def load_cached(ticker: str) -> pd.DataFrame:
    """Le o parquet local de um ticker (DataFrame vazio se nao existir)."""
    path = _cache_path(ticker)
    if not path.exists():
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    df = pd.read_parquet(path)
    df.index = pd.to_datetime(df.index)
    return df


def update_ticker_cache(ticker: str, backfill_period: str = DEFAULT_BACKFILL_PERIOD) -> pd.DataFrame:
    """Atualiza o cache de um ticker: backfill completo na 1a vez, so o delta depois.

    Retorna o DataFrame completo (cache atualizado) apos a operacao.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_cached(ticker)

    if existing.empty:
        logger.info("Backfill completo (%s) para %s.", backfill_period, ticker)
        new_data = fetch_history(ticker, period=backfill_period, interval="1d")
        combined = new_data
    else:
        last_date = existing.index.max()
        start = (last_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info("Atualizacao incremental de %s a partir de %s.", ticker, start)
        new_data = fetch_history(ticker, start=start, interval="1d")
        if new_data.empty:
            combined = existing
        else:
            combined = pd.concat([existing, new_data])
            combined = combined[~combined.index.duplicated(keep="last")].sort_index()

    if not combined.empty:
        combined.to_parquet(_cache_path(ticker))
    return combined


def update_all(tickers: list[str], backfill_period: str = DEFAULT_BACKFILL_PERIOD) -> dict[str, int]:
    """Atualiza o cache de uma lista de tickers. Retorna {ticker: n_linhas} para relatorio."""
    report: dict[str, int] = {}
    for i, ticker in enumerate(tickers, 1):
        try:
            df = update_ticker_cache(ticker, backfill_period=backfill_period)
            report[ticker] = len(df)
            logger.info("[%d/%d] %s: %d linhas em cache.", i, len(tickers), ticker, len(df))
        except Exception as exc:
            logger.error("Erro atualizando %s: %s", ticker, exc)
            report[ticker] = -1
    return report
