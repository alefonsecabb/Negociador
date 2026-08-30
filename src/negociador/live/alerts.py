"""Geracao de alertas (ENTRADA/STOP/TAKE-PROFIT/SAIDA POR TEMPO) para o dashboard.

So GERA e PERSISTE o alerta (com o preco-limite e a recomendacao de ordem
stop nativa da corretora, quando aplicavel) - a carteira ficticia so muda
quando o usuario confirma a execucao (ver cli/confirm_execution.py). Isso
mantem a ferramenta no papel de apoio a decisao, nunca de execucao automatica.
"""
from __future__ import annotations

from negociador.portfolio.paper_portfolio import create_alert, has_open_or_recent_alert
from negociador.strategy.order_pricing import (
    ExecutionMarginParams,
    stop_loss_limit_price,
    take_profit_limit_price,
)
from negociador.strategy.signals import EntrySignal


def raise_entry_alert(signal: EntrySignal, margin_params: ExecutionMarginParams, db_path=None) -> int | None:
    """Cria um alerta de ENTRADA se ainda nao houver um pendente ('novo') para o ticker."""
    kwargs = {"db_path": db_path} if db_path else {}
    if has_open_or_recent_alert(signal.ticker, "ENTRADA", **kwargs):
        return None
    return create_alert(
        ticker=signal.ticker,
        alert_type="ENTRADA",
        reference_price=signal.reference_price,
        limit_price=signal.limit_price,
        stop_price=signal.stop_price,
        take_price=signal.take_price,
        extra={
            "atr": signal.reference_price * signal.atr_pct,
            "atr_pct": signal.atr_pct,
            "variant": signal.variant,
            "as_of": signal.as_of,
            "recomendacao": (
                f"Ordem LIMITADA de compra a R$ {signal.limit_price:.2f}. "
                f"Assim que executada, cadastre no homebroker uma ordem STOP de venda a "
                f"R$ {signal.stop_price:.2f} (protecao) e, se possivel, um take-profit (OCO) a "
                f"R$ {signal.take_price:.2f}."
            ),
        },
        **kwargs,
    )


def raise_exit_alert(
    ticker: str,
    exit_reason: str,
    reference_price: float,
    stop_price: float,
    take_price: float,
    atr_pct: float,
    margin_params: ExecutionMarginParams,
    db_path=None,
) -> int | None:
    """Cria um alerta de saida (STOP_LOSS / TAKE_PROFIT / SAIDA_POR_TEMPO) para uma
    posicao ja aberta na carteira ficticia, se ainda nao houver um pendente."""
    kwargs = {"db_path": db_path} if db_path else {}
    if has_open_or_recent_alert(ticker, exit_reason, **kwargs):
        return None

    if exit_reason == "STOP_LOSS":
        limit_price = stop_loss_limit_price(stop_price, atr_pct, margin_params)
        recomendacao = f"VENDA (stop-loss) - ordem limitada a R$ {limit_price:.2f}."
    elif exit_reason == "TAKE_PROFIT":
        limit_price = take_profit_limit_price(take_price, atr_pct, margin_params)
        recomendacao = f"VENDA (take-profit) - ordem limitada a R$ {limit_price:.2f}."
    else:  # SAIDA_POR_TEMPO
        limit_price = stop_loss_limit_price(reference_price, atr_pct, margin_params)
        recomendacao = f"VENDA (saida por tempo, prazo maximo em posicao atingido) - ordem limitada a R$ {limit_price:.2f}."

    return create_alert(
        ticker=ticker,
        alert_type=exit_reason,
        reference_price=reference_price,
        limit_price=limit_price,
        stop_price=stop_price,
        take_price=take_price,
        extra={"atr_pct": atr_pct, "recomendacao": recomendacao},
        **kwargs,
    )
