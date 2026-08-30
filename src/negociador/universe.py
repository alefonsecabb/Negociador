"""Catalogo de tickers do universo monitorado (acoes do Ibovespa).

A fonte de verdade e o arquivo config/ibov_universe.json, atualizado
manualmente pelo usuario a cada rebalanceamento trimestral do indice
(janeiro/maio/setembro - ver nota dentro do proprio arquivo). Se o arquivo
nao existir ou estiver corrompido, cai para uma lista hardcoded de
fallback (snapshot datado) para a ferramenta nunca ficar sem universo.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UNIVERSE_FILE = PROJECT_ROOT / "config" / "ibov_universe.json"

# Snapshot de fallback (carteira teorica do Ibovespa, capturada em 30/08/2026
# via API publica da B3). So usado se config/ibov_universe.json nao puder
# ser lido - mantenha o JSON atualizado em vez de depender deste fallback.
IBOV_TICKERS_FALLBACK: list[str] = [
    "ABEV3", "ALOS3", "ASAI3", "AURE3", "AXIA3", "AZZA3", "B3SA3", "BBAS3",
    "BBDC3", "BBDC4", "BBSE3", "BEEF3", "BPAC11", "BRAP4", "BRAV3", "CEAB3",
    "CMIG4", "CMIN3", "COGN3", "CPFE3", "CPLE3", "CSAN3", "CSMG3", "CSNA3",
    "CURY3", "CXSE3", "CYRE3", "DIRR3", "EGIE3", "EMBJ3", "ENEV3", "ENGI11",
    "EQTL3", "FLRY3", "GGBR4", "GOAU4", "HAPV3", "HYPE3", "IGTI11", "ISAE4",
    "ITSA4", "ITUB4", "KLBN11", "LREN3", "MBRF3", "MGLU3", "MOTV3", "MRVE3",
    "MULT3", "NATU3", "PETR3", "PETR4", "POMO4", "PRIO3", "PSSA3", "RADL3",
    "RAIL3", "RDOR3", "RECV3", "RENT3", "SANB11", "SBSP3", "SLCE3", "SMFT3",
    "SUZB3", "TAEE11", "TIMS3", "TOTS3", "UGPA3", "USIM5", "VALE3", "VAMO3",
    "VBBR3", "VIVA3", "VIVT3", "WEGE3", "YDUQ3",
]


def to_yfinance_symbol(ticker: str) -> str:
    """Converte um ticker B3 (ex. PETR4) para o simbolo usado pelo yfinance (PETR4.SA)."""
    ticker = ticker.strip().upper()
    return ticker if ticker.endswith(".SA") else f"{ticker}.SA"


def load_universe(universe_file: Path = UNIVERSE_FILE) -> list[str]:
    """Carrega a lista de tickers do Ibovespa a partir do JSON de configuracao.

    Retorna a lista ordenada de tickers (sem sufixo .SA). Cai para o
    fallback hardcoded se o arquivo nao existir, estiver vazio ou corrompido.
    """
    try:
        with open(universe_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        tickers = data.get("tickers") or []
        if not tickers:
            raise ValueError("campo 'tickers' vazio")
        return sorted(set(t.strip().upper() for t in tickers))
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        logger.warning(
            "Nao foi possivel carregar %s (%s) - usando fallback hardcoded com %d tickers.",
            universe_file, exc, len(IBOV_TICKERS_FALLBACK),
        )
        return sorted(set(IBOV_TICKERS_FALLBACK))


if __name__ == "__main__":
    tickers = load_universe()
    print(f"{len(tickers)} tickers carregados:")
    print(", ".join(tickers))
