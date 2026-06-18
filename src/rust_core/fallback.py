import json
from typing import List


def calculate_dcf(
    revenue_growth_projections: List[float],
    terminal_growth_rate: float,
    wacc: float,
    free_cash_flow_base: float,
    shares_outstanding: float,
    cash: float,
    short_term_investments: float,
    debt: float,
    preferred_equity: float,
    minority_interest: float,
    other_financial: float,
    mid_year: bool = True,
) -> str:
    projected_cash_flows = []
    current_fcf = free_cash_flow_base

    for growth in revenue_growth_projections:
        current_fcf *= 1.0 + growth
        projected_cash_flows.append(current_fcf)

    pv_cash_flows = 0.0
    for i, fcf in enumerate(projected_cash_flows):
        discount_factor = (1.0 + wacc) ** (i + 1 - (0.5 if mid_year else 0.0))
        pv_cash_flows += fcf / discount_factor

    last_fcf = projected_cash_flows[-1] if projected_cash_flows else free_cash_flow_base
    terminal_value = (last_fcf * (1.0 + terminal_growth_rate)) / (
        wacc - terminal_growth_rate
    )
    pv_terminal_value = terminal_value / ((1.0 + wacc) ** len(projected_cash_flows))

    enterprise_value = pv_cash_flows + pv_terminal_value
    net_debt = (
        debt
        + preferred_equity
        + minority_interest
        - cash
        - short_term_investments
        - other_financial
    )
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
