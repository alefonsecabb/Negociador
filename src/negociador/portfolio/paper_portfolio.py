"""Carteira ficticia (R$100k) persistida em SQLite.

O GitHub Actions roda em containers efemeros - todo o estado (caixa,
posicoes abertas, historico de trades, alertas, estado do IR) precisa
estar no arquivo data/negociador.db, que e versionado no repo (ver
.gitignore) para persistir de uma execucao agendada para a proxima.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from negociador.backtest.costs import CostParams, TaxTracker, order_cost

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "data" / "negociador.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    cash REAL NOT NULL,
    initial_capital REAL NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    ticker TEXT PRIMARY KEY,
    entry_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    qty INTEGER NOT NULL,
    stop_price REAL NOT NULL,
    take_price REAL NOT NULL,
    atr_at_entry REAL NOT NULL,
    high_since_entry REAL NOT NULL,
    holding_days INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    exit_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    qty INTEGER NOT NULL,
    exit_reason TEXT NOT NULL,
    gross_pnl REAL NOT NULL,
    total_costs REAL NOT NULL,
    tax_paid REAL NOT NULL,
    net_pnl REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    reference_price REAL NOT NULL,
    limit_price REAL NOT NULL,
    stop_price REAL,
    take_price REAL,
    status TEXT NOT NULL DEFAULT 'novo',
    extra_json TEXT
);

CREATE TABLE IF NOT EXISTS tax_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    current_month TEXT,
    month_sales_total REAL NOT NULL DEFAULT 0,
    month_net_profit REAL NOT NULL DEFAULT 0,
    loss_carryforward REAL NOT NULL DEFAULT 0
);
"""


@contextmanager
def connect(db_path: Path | None = None):
    # Resolvido em tempo de CHAMADA (nao de definicao): todas as outras funcoes
    # deste modulo tem `db_path: Path | None = None` e repassam direto pra ca,
    # entao um monkeypatch em paper_portfolio.DB_PATH (comum em testes) so
    # funciona porque a resolucao acontece aqui, na hora de conectar - se
    # cada assinatura capturasse `= DB_PATH` como default, o valor ficaria
    # congelado no momento em que o modulo foi importado, e nunca refletiria
    # uma alteracao posterior de DB_PATH.
    if db_path is None:
        db_path = DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize(initial_capital: float, db_path: Path | None = None) -> None:
    """Cria a carteira com o capital inicial, se ainda nao existir (idempotente)."""
    with connect(db_path) as conn:
        row = conn.execute("SELECT id FROM portfolio_state WHERE id = 1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO portfolio_state (id, cash, initial_capital, updated_at) VALUES (1, ?, ?, datetime('now'))",
                (initial_capital, initial_capital),
            )


def get_cash(db_path: Path | None = None) -> float:
    with connect(db_path) as conn:
        row = conn.execute("SELECT cash FROM portfolio_state WHERE id = 1").fetchone()
        return float(row["cash"]) if row else 0.0


def get_initial_capital(db_path: Path | None = None) -> float:
    with connect(db_path) as conn:
        row = conn.execute("SELECT initial_capital FROM portfolio_state WHERE id = 1").fetchone()
        return float(row["initial_capital"]) if row else 0.0


def _set_cash(conn: sqlite3.Connection, cash: float) -> None:
    conn.execute("UPDATE portfolio_state SET cash = ?, updated_at = datetime('now') WHERE id = 1", (cash,))


def get_open_positions(db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM positions").fetchall()
        return [dict(r) for r in rows]


def get_position(ticker: str, db_path: Path | None = None) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM positions WHERE ticker = ?", (ticker,)).fetchone()
        return dict(row) if row else None


def open_position(
    ticker: str, entry_date: str, entry_price: float, qty: int,
    stop_price: float, take_price: float, atr_at_entry: float,
    costs: CostParams, db_path: Path | None = None,
) -> bool:
    """Abre uma posicao, debitando o valor da compra + custos do caixa.
    Devolve False (sem efeito) se o caixa disponivel for insuficiente."""
    buy_value = entry_price * qty
    buy_cost = order_cost(buy_value, costs)
    with connect(db_path) as conn:
        cash = float(conn.execute("SELECT cash FROM portfolio_state WHERE id = 1").fetchone()["cash"])
        if buy_value + buy_cost > cash:
            return False
        conn.execute(
            """INSERT INTO positions (ticker, entry_date, entry_price, qty, stop_price, take_price, atr_at_entry, high_since_entry, holding_days)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (ticker, entry_date, entry_price, qty, stop_price, take_price, atr_at_entry, entry_price),
        )
        _set_cash(conn, cash - buy_value - buy_cost)
    return True


def update_position(ticker: str, stop_price: float | None = None, high_since_entry: float | None = None,
                     holding_days: int | None = None, db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        current = conn.execute("SELECT * FROM positions WHERE ticker = ?", (ticker,)).fetchone()
        if not current:
            return
        conn.execute(
            "UPDATE positions SET stop_price = ?, high_since_entry = ?, holding_days = ? WHERE ticker = ?",
            (
                stop_price if stop_price is not None else current["stop_price"],
                high_since_entry if high_since_entry is not None else current["high_since_entry"],
                holding_days if holding_days is not None else current["holding_days"],
                ticker,
            ),
        )


def _load_tax_tracker(conn: sqlite3.Connection, costs: CostParams) -> TaxTracker:
    row = conn.execute("SELECT * FROM tax_state WHERE id = 1").fetchone()
    state = dict(row) if row else {}
    return TaxTracker.from_state_dict(costs, state)


def _save_tax_tracker(conn: sqlite3.Connection, tracker: TaxTracker) -> None:
    state = tracker.to_state_dict()
    conn.execute(
        """INSERT INTO tax_state (id, current_month, month_sales_total, month_net_profit, loss_carryforward)
           VALUES (1, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET current_month=excluded.current_month,
               month_sales_total=excluded.month_sales_total,
               month_net_profit=excluded.month_net_profit,
               loss_carryforward=excluded.loss_carryforward""",
        (state["current_month"], state["month_sales_total"], state["month_net_profit"], state["loss_carryforward"]),
    )


def roll_tax_month(today: str, costs: CostParams, db_path: Path | None = None) -> float:
    """Chamar 1x no INICIO de cada execucao do monitor ao vivo: fecha o mes de
    IR anterior se `today` ja estiver em um mes novo (mesmo sem nenhuma venda
    ainda registrada nesse novo mes), debitando o imposto do caixa. Sem isso,
    o IR de um mes sem nenhuma venda logo em seguida ficaria pendurado
    indefinidamente. Retorna o imposto debitado (0.0 se nao havia mes a fechar)."""
    with connect(db_path) as conn:
        tracker = _load_tax_tracker(conn, costs)
        tax_due = tracker.roll_to_date(pd.Timestamp(today))
        if tax_due:
            _save_tax_tracker(conn, tracker)
            row = conn.execute("SELECT cash FROM portfolio_state WHERE id = 1").fetchone()
            _set_cash(conn, float(row["cash"]) - tax_due)
        return tax_due


def close_position(ticker: str, exit_date: str, exit_price: float, exit_reason: str,
                    costs: CostParams, db_path: Path | None = None) -> dict | None:
    """Fecha uma posicao aberta: credita o caixa, calcula custos e o IR do mes
    (usando o TaxTracker persistido), e registra o trade. Devolve o resumo do
    trade, ou None se o ticker nao estiver em posicao."""
    with connect(db_path) as conn:
        pos = conn.execute("SELECT * FROM positions WHERE ticker = ?", (ticker,)).fetchone()
        if not pos:
            return None

        sale_value = exit_price * pos["qty"]
        buy_cost = order_cost(pos["entry_price"] * pos["qty"], costs)
        sell_cost = order_cost(sale_value, costs)
        gross_pnl = (exit_price - pos["entry_price"]) * pos["qty"]
        net_pnl = gross_pnl - buy_cost - sell_cost

        tracker = _load_tax_tracker(conn, costs)
        tax_due = tracker.record_sale(pd.Timestamp(exit_date), sale_value, net_pnl)
        _save_tax_tracker(conn, tracker)

        cash = float(conn.execute("SELECT cash FROM portfolio_state WHERE id = 1").fetchone()["cash"])
        cash += sale_value - sell_cost - tax_due
        _set_cash(conn, cash)

        conn.execute("DELETE FROM positions WHERE ticker = ?", (ticker,))
        conn.execute(
            """INSERT INTO trades (ticker, entry_date, exit_date, entry_price, exit_price, qty, exit_reason,
                                    gross_pnl, total_costs, tax_paid, net_pnl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ticker, pos["entry_date"], exit_date, pos["entry_price"], exit_price, pos["qty"], exit_reason,
             gross_pnl, buy_cost + sell_cost, tax_due, net_pnl),
        )
        return {
            "ticker": ticker, "entry_date": pos["entry_date"], "exit_date": exit_date,
            "entry_price": pos["entry_price"], "exit_price": exit_price, "qty": pos["qty"],
            "exit_reason": exit_reason, "gross_pnl": gross_pnl, "total_costs": buy_cost + sell_cost,
            "tax_paid": tax_due, "net_pnl": net_pnl,
        }


def get_trades(db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM trades ORDER BY exit_date").fetchall()
        return [dict(r) for r in rows]


def create_alert(ticker: str, alert_type: str, reference_price: float, limit_price: float,
                  stop_price: float | None = None, take_price: float | None = None,
                  extra: dict | None = None, db_path: Path | None = None) -> int:
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO alerts (created_at, ticker, alert_type, reference_price, limit_price, stop_price, take_price, status, extra_json)
               VALUES (datetime('now'), ?, ?, ?, ?, ?, ?, 'novo', ?)""",
            (ticker, alert_type, reference_price, limit_price, stop_price, take_price, json.dumps(extra or {}, ensure_ascii=False)),
        )
        return cur.lastrowid


def get_alerts(status: str | None = None, db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        if status:
            rows = conn.execute("SELECT * FROM alerts WHERE status = ? ORDER BY id DESC", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM alerts ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def set_alert_status(alert_id: int, status: str, db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute("UPDATE alerts SET status = ? WHERE id = ?", (status, alert_id))


def has_open_or_recent_alert(ticker: str, alert_type: str, db_path: Path | None = None) -> bool:
    """Evita spam de alertas repetidos: verifica se ja existe um alerta 'novo' do
    mesmo tipo para o ticker (o usuario ainda nao confirmou nem ignorou)."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM alerts WHERE ticker = ? AND alert_type = ? AND status = 'novo'",
            (ticker, alert_type),
        ).fetchone()
        return row is not None


def expire_stale_alerts(max_age_days: float, db_path: Path | None = None) -> list[int]:
    """Marca como 'expirado' qualquer alerta 'novo' criado ha mais de `max_age_days`
    dias corridos - o usuario nunca confirmou nem ignorou. Sem isso, o alerta
    ficaria pendente para sempre com um preco-limite cada vez mais desatualizado,
    e o ticker ficaria bloqueado para um novo sinal (ver has_open_or_recent_alert).
    Chamar no INICIO de cada execucao do monitor, antes de varrer sinais novos.
    Devolve a lista de ids expirados."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id FROM alerts WHERE status = 'novo' AND (julianday('now') - julianday(created_at)) >= ?",
            (max_age_days,),
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            conn.executemany("UPDATE alerts SET status = 'expirado' WHERE id = ?", [(i,) for i in ids])
        return ids
