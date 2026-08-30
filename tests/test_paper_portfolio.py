import pytest

from negociador.portfolio import paper_portfolio as pp


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_negociador.db"


def test_expire_stale_alerts_marks_old_pending_alerts(db_path):
    pp.initialize(100_000.0, db_path=db_path)
    alert_id = pp.create_alert("PETR4", "ENTRADA", 30.0, 30.1, db_path=db_path)

    # forca o alerta a parecer criado ha 5 dias
    with pp.connect(db_path) as conn:
        conn.execute("UPDATE alerts SET created_at = datetime('now', '-5 days') WHERE id = ?", (alert_id,))

    expired = pp.expire_stale_alerts(max_age_days=2, db_path=db_path)

    assert expired == [alert_id]
    alert = pp.get_alerts(db_path=db_path)[0]
    assert alert["status"] == "expirado"


def test_expire_stale_alerts_leaves_recent_alerts_pending(db_path):
    pp.initialize(100_000.0, db_path=db_path)
    pp.create_alert("VALE3", "ENTRADA", 60.0, 60.2, db_path=db_path)

    expired = pp.expire_stale_alerts(max_age_days=2, db_path=db_path)

    assert expired == []
    alert = pp.get_alerts(db_path=db_path)[0]
    assert alert["status"] == "novo"


def test_expired_ticker_is_free_for_a_new_alert(db_path):
    pp.initialize(100_000.0, db_path=db_path)
    alert_id = pp.create_alert("ITUB4", "ENTRADA", 30.0, 30.1, db_path=db_path)
    assert pp.has_open_or_recent_alert("ITUB4", "ENTRADA", db_path=db_path) is True

    with pp.connect(db_path) as conn:
        conn.execute("UPDATE alerts SET created_at = datetime('now', '-5 days') WHERE id = ?", (alert_id,))
    pp.expire_stale_alerts(max_age_days=2, db_path=db_path)

    assert pp.has_open_or_recent_alert("ITUB4", "ENTRADA", db_path=db_path) is False


def test_expire_stale_alerts_does_not_touch_already_resolved_alerts(db_path):
    pp.initialize(100_000.0, db_path=db_path)
    alert_id = pp.create_alert("WEGE3", "ENTRADA", 40.0, 40.1, db_path=db_path)
    pp.set_alert_status(alert_id, "executado", db_path=db_path)
    with pp.connect(db_path) as conn:
        conn.execute("UPDATE alerts SET created_at = datetime('now', '-10 days') WHERE id = ?", (alert_id,))

    expired = pp.expire_stale_alerts(max_age_days=2, db_path=db_path)

    assert expired == []
    assert pp.get_alerts(db_path=db_path)[0]["status"] == "executado"
