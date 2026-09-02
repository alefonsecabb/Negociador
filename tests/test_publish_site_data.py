"""publish_quotes / publish_params: os JSONs que o homebroker 100%-navegador
consome (cotacoes para marcar a mercado e simular saidas; parametros do modelo
para dimensionar posicao e aplicar custos/IR)."""
import json

import pytest

from negociador.backtest.costs import CostParams
from negociador.live import publish_site_data as psd
from negociador.portfolio import paper_portfolio as pp

COSTS = CostParams.from_config(
    {"b3_emolument_pct": 0.0003, "brokerage_fee_brl": 0.0,
     "income_tax_pct": 0.15, "income_tax_exempt_sales_brl": 20_000.0}
)

QUOTE = {"price": 38.1, "open": 37.9, "high": 38.4, "low": 37.7, "date": "2026-09-02"}


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(psd, "SITE_DATA_DIR", tmp_path)
    monkeypatch.setattr(pp, "DB_PATH", tmp_path / "test_negociador.db")
    pp.initialize(100_000.0)
    return tmp_path


def _read(site, name):
    return json.loads((site / name).read_text(encoding="utf-8"))


def test_publish_quotes_shape(site):
    psd.publish_quotes({"PETR4": QUOTE})
    data = _read(site, "quotes.json")
    assert "generated_at" in data
    assert data["quotes"]["PETR4"]["price"] == 38.1


def test_publish_quotes_skips_when_empty(site):
    psd.publish_quotes({"PETR4": QUOTE})
    before = (site / "quotes.json").read_text(encoding="utf-8")
    psd.publish_quotes({})
    assert (site / "quotes.json").read_text(encoding="utf-8") == before


def test_publish_params_shape(site):
    data = psd.publish_params()

    assert _read(site, "params.json") == data
    assert data["capital_inicial"] == pytest.approx(100_000.0)
    for key in ("atr_stop_multiple", "reward_risk_ratio", "breakeven_after_r", "max_holding_days"):
        assert key in data["risk"]
    for key in ("risk_per_trade_pct", "max_position_pct", "max_open_positions", "min_cash_reserve_pct"):
        assert key in data["position_sizing"]
    for key in ("b3_emolument_pct", "brokerage_fee_brl", "income_tax_pct", "income_tax_exempt_sales_brl"):
        assert key in data["costs"]
    assert 0 < data["target_monthly_return_pct"] < 1


def test_publish_params_included_in_publish_all(site):
    psd.publish_all(fetch_quotes=False)
    assert (site / "params.json").exists()
    assert (site / "portfolio.json").exists()


def test_publish_portfolio_prefers_quotes_json(site, monkeypatch):
    def _boom(ticker):
        raise AssertionError(f"fetch_last_quote nao deveria ser chamado ({ticker})")

    monkeypatch.setattr(psd, "fetch_last_quote", _boom)
    psd.publish_quotes({"PETR4": QUOTE})
    pp.open_position("PETR4", "2026-01-05", 30.0, 100, 28.0, 36.0, 1.0, COSTS)

    data = psd.publish_portfolio(fetch_quotes=True)

    assert data["positions"][0]["current_price"] == pytest.approx(38.1)
