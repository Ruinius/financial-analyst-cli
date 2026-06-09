import json
from typing import List, Tuple


def calculate_dcf(
    revenue_growth_projections: List[float],
    terminal_growth_rate: float,
    wacc: float,
    free_cash_flow_base: float,
    shares_outstanding: float,
    net_debt: float,
) -> str:
    projected_cash_flows = []
    current_fcf = free_cash_flow_base

    for growth in revenue_growth_projections:
        current_fcf *= 1.0 + growth
        projected_cash_flows.append(current_fcf)

    pv_cash_flows = 0.0
    for i, fcf in enumerate(projected_cash_flows):
        discount_factor = (1.0 + wacc) ** (i + 1)
        pv_cash_flows += fcf / discount_factor

    last_fcf = projected_cash_flows[-1] if projected_cash_flows else free_cash_flow_base
    terminal_value = (last_fcf * (1.0 + terminal_growth_rate)) / (
        wacc - terminal_growth_rate
    )
    pv_terminal_value = terminal_value / ((1.0 + wacc) ** len(projected_cash_flows))

    enterprise_value = pv_cash_flows + pv_terminal_value
    equity_value = enterprise_value - net_debt
    intrinsic_value_per_share = (
        equity_value / shares_outstanding if shares_outstanding > 0.0 else 0.0
    )

    result = {
        "projected_cash_flows": projected_cash_flows,
        "terminal_value": terminal_value,
        "enterprise_value": enterprise_value,
        "intrinsic_value_per_share": intrinsic_value_per_share,
    }

    return json.dumps(result)


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
    net_income: float,
    total_tax_adj: float,
    ebita: float,
) -> Tuple[float, float]:
    if income_before_taxes != 0.0:
        effective_rate = -(income_tax_expense / income_before_taxes)
    else:
        effective_rate = 0.21

    adjusted_tax = income_tax_expense + total_tax_adj
    adjusted_rate = -(adjusted_tax / ebita) if ebita != 0.0 else 0.0

    return effective_rate, adjusted_rate


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
