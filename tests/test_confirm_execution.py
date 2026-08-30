import pytest

from negociador.portfolio import paper_portfolio as pp
from negociador.cli import confirm_execution as ce


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """apply_ignore/apply_confirmation operam sempre no pp.DB_PATH default -
    redireciona para um banco temporario por teste."""
    db_path = tmp_path / "test_negociador.db"
    monkeypatch.setattr(pp, "DB_PATH", db_path)
    pp.initialize(100_000.0)
    return db_path


def test_apply_ignore_sets_status_without_touching_cash(isolated_db):
    alert_id = pp.create_alert("PETR4", "ENTRADA", 30.0, 30.1)
    cash_before = pp.get_cash()

    result = ce.apply_ignore(alert_id)

    assert result["ok"] is True
    assert result["action"] == "IGNORE"
    assert pp.get_alerts()[0]["status"] == "ignorado"
    assert pp.get_cash() == cash_before


def test_apply_ignore_rejects_unknown_alert(isolated_db):
    result = ce.apply_ignore(999)
    assert result["ok"] is False


def test_apply_ignore_rejects_already_resolved_alert(isolated_db):
    alert_id = pp.create_alert("VALE3", "ENTRADA", 60.0, 60.2)
    pp.set_alert_status(alert_id, "executado")
    result = ce.apply_ignore(alert_id)
    assert result["ok"] is False


def test_reconcile_dispatches_ignore_action(isolated_db, tmp_path, monkeypatch):
    alert_id = pp.create_alert("ITUB4", "ENTRADA", 30.0, 30.1)
    events_file = tmp_path / "events.jsonl"
    cursor_file = tmp_path / "events_cursor.txt"
    monkeypatch.setattr(ce, "EVENTS_FILE", events_file)
    monkeypatch.setattr(ce, "CURSOR_FILE", cursor_file)

    ce.record_event(alert_id, action="ignore")
    results = ce.reconcile_pending_events(params={"costs": {}, "position_sizing": {}, "risk": {}})

    assert len(results) == 1
    assert results[0]["result"]["ok"] is True
    assert results[0]["result"]["action"] == "IGNORE"
    assert pp.get_alerts()[0]["status"] == "ignorado"


def test_reconcile_treats_legacy_events_without_action_as_confirm(isolated_db, tmp_path, monkeypatch):
    """Linhas gravadas antes do campo 'action' existir devem continuar confirmando (compat retroativa)."""
    alert_id = pp.create_alert("VALE3", "STOP_LOSS", 60.0, 59.5, stop_price=60.0, take_price=65.0)
    events_file = tmp_path / "events.jsonl"
    cursor_file = tmp_path / "events_cursor.txt"
    monkeypatch.setattr(ce, "EVENTS_FILE", events_file)
    monkeypatch.setattr(ce, "CURSOR_FILE", cursor_file)
    events_file.write_text('{"alert_id": %d, "fill_price": null}\n' % alert_id, encoding="utf-8")

    params = {
        "costs": {"b3_emolument_pct": 0.0, "brokerage_fee_brl": 0.0, "income_tax_pct": 0.15, "income_tax_exempt_sales_brl": 20000.0},
        "position_sizing": {"risk_per_trade_pct": 0.01, "max_position_pct": 0.1, "max_open_positions": 12, "min_cash_reserve_pct": 0.1},
        "risk": {"atr_stop_multiple": 2.0, "reward_risk_ratio": 2.0, "breakeven_after_r": 0.0, "max_holding_days": 20},
    }
    results = ce.reconcile_pending_events(params=params)

    # sem posicao aberta pra VALE3, a "confirmacao" de um STOP_LOSS deve falhar
    # de forma controlada (nao quebrar) - o importante e que foi tratado como "confirm", nao "ignore"
    assert len(results) == 1
    assert results[0]["result"]["ok"] is False
    assert pp.get_alerts()[0]["status"] == "novo"  # apply_confirmation nao muda status quando falha assim
