from src.utils.financial_math import (
    clean_val,
    calculate_ebita,
    calculate_invested_capital,
    calculate_tax_rates,
    calculate_roic,
)


def test_clean_val():
    assert clean_val("12,345") == 12345.0
    assert clean_val("$12,345.50") == 12345.50
    assert clean_val("(1,000)") == -1000.0
    assert clean_val("N/A") == 0.0
    assert clean_val(" -- ") == 0.0
    assert clean_val("10%") == 0.10
    assert clean_val("280 million") == 280.0
    assert clean_val("283 million shares") == 283.0
    assert clean_val("280M") == 280.0
    assert clean_val("280.5M") == 280.5
    assert clean_val("(15.5 million)") == -15.5


def test_calculations_logic():
    # Test EBITA
    ebita, margin = calculate_ebita(100.0, 500.0, 10.0)
    assert ebita == 110.0
    assert margin == 22.0

    # Test Invested Capital
    nwc, nltoa, ic, turnover = calculate_invested_capital(
        200.0, 150.0, 400.0, 300.0, 500.0
    )
    assert nwc == 50.0
    assert nltoa == 100.0
    assert ic == 150.0
    assert turnover == 500.0 / 150.0

    # Test Tax Rates
    eff, adj = calculate_tax_rates(120.0, -30.0, -5.0, 110.0)
    assert eff == 0.25
    assert adj == (35.0 / 110.0)

    # Test ROIC
    nopat, ann_nopat, roic = calculate_roic(110.0, 0.20, 150.0, 4.0)
    assert nopat == 88.0
    assert ann_nopat == 352.0
    assert roic == (352.0 / 150.0) * 100.0
