from typing import Tuple


def calculate_ebita(
    starting_val: float,
    revenue: float,
    non_operating_adjustments_sum: float,
) -> Tuple[float, float]:
    ebita = starting_val + non_operating_adjustments_sum
    margin = (ebita / revenue) * 100.0 if revenue > 0.0 else 0.0
    return ebita, margin


def calculate_invested_capital(
    oca: float,
    ocl: float,
    onca: float,
    oncl: float,
    annualized_revenue: float,
) -> Tuple[float, float, float, float]:
    nwc = oca - ocl
    nltoa = onca - oncl
    ic = nwc + nltoa
    turnover = annualized_revenue / ic if ic != 0.0 else 0.0
    return nwc, nltoa, ic, turnover


def calculate_tax_rates(
    income_before_taxes: float,
    income_tax_expense: float,
    total_tax_adj: float,
    ebita: float,
) -> Tuple[float, float]:
    if income_before_taxes != 0.0:
        effective_rate = income_tax_expense / income_before_taxes
    else:
        effective_rate = -0.25

    adjusted_tax = income_tax_expense + total_tax_adj
    adjusted_rate = (adjusted_tax / ebita) if ebita != 0.0 else -0.25

    # Flip the sign before returning so the ROIC calculations and markdown makes sense
    return -effective_rate, -adjusted_rate


def calculate_roic(
    ebita: float,
    tax_rate: float,
    invested_capital: float,
    multiplier: float,
) -> Tuple[float, float, float]:
    nopat = ebita * (1.0 - tax_rate)
    annualized_nopat = nopat * multiplier
    roic = (
        (annualized_nopat / invested_capital) * 100.0
        if invested_capital != 0.0
        else 0.0
    )
    return nopat, annualized_nopat, roic
