use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
pub struct DcfResult {
    pub projected_cash_flows: Vec<f64>,
    pub terminal_value: f64,
    pub enterprise_value: f64,
    pub intrinsic_value_per_share: f64,
}

/// Computes the Discounted Cash Flow valuation.
#[pyfunction]
pub fn calculate_dcf(
    revenue_growth_projections: Vec<f64>,
    terminal_growth_rate: f64,
    wacc: f64,
    free_cash_flow_base: f64,
    shares_outstanding: f64,
    net_debt: f64,
) -> PyResult<String> {
    let mut projected_cash_flows = Vec::new();
    let mut current_fcf = free_cash_flow_base;

    for growth in &revenue_growth_projections {
        current_fcf *= 1.0 + growth;
        projected_cash_flows.push(current_fcf);
    }

    let mut pv_cash_flows = 0.0;
    for (i, fcf) in projected_cash_flows.iter().enumerate() {
        let discount_factor = (1.0 + wacc).powi((i + 1) as i32);
        pv_cash_flows += fcf / discount_factor;
    }

    let last_fcf = *projected_cash_flows.last().unwrap_or(&free_cash_flow_base);
    let terminal_value = (last_fcf * (1.0 + terminal_growth_rate)) / (wacc - terminal_growth_rate);
    let pv_terminal_value = terminal_value / (1.0 + wacc).powi(projected_cash_flows.len() as i32);

    let enterprise_value = pv_cash_flows + pv_terminal_value;
    let equity_value = enterprise_value - net_debt;
    let intrinsic_value_per_share = if shares_outstanding > 0.0 {
        equity_value / shares_outstanding
    } else {
        0.0
    };

    let result = DcfResult {
        projected_cash_flows,
        terminal_value,
        enterprise_value,
        intrinsic_value_per_share,
    };

    serde_json::to_string(&result)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))
}

/// Calculate EBITA and EBITA Margin.
#[pyfunction]
pub fn calculate_ebita(
    starting_val: f64,
    revenue: f64,
    non_operating_adjustments_sum: f64,
) -> PyResult<(f64, f64)> {
    let ebita = starting_val + non_operating_adjustments_sum;
    let margin = if revenue > 0.0 {
        (ebita / revenue) * 100.0
    } else {
        0.0
    };
    Ok((ebita, margin))
}

/// Calculate Invested Capital components and Capital Turnover.
#[pyfunction]
pub fn calculate_invested_capital(
    oca: f64,
    ocl: f64,
    onca: f64,
    oncl: f64,
    annualized_revenue: f64,
) -> PyResult<(f64, f64, f64, f64)> {
    let nwc = oca - ocl;
    let nltoa = onca - oncl;
    let ic = nwc + nltoa;
    let turnover = if ic != 0.0 {
        annualized_revenue / ic
    } else {
        0.0
    };
    Ok((nwc, nltoa, ic, turnover))
}

/// Calculate Effective and Adjusted Tax Rates.
#[pyfunction]
pub fn calculate_tax_rates(
    income_before_taxes: f64,
    income_tax_expense: f64,
    net_income: f64,
    total_tax_adj: f64,
    ebita: f64,
) -> PyResult<(f64, f64)> {
    let effective_rate = if income_before_taxes != 0.0 {
        // reported provision is often negative for expense
        -(income_tax_expense / income_before_taxes)
    } else if income_before_taxes != 0.0 {
        (income_before_taxes - net_income) / income_before_taxes
    } else {
        0.21
    };

    let adjusted_tax = income_tax_expense + total_tax_adj;
    let adjusted_rate = if ebita != 0.0 {
        -(adjusted_tax / ebita)
    } else {
        0.0
    };

    Ok((effective_rate, adjusted_rate))
}

/// Calculate NOPAT, Annualized NOPAT, and ROIC.
#[pyfunction]
pub fn calculate_roic(
    ebita: f64,
    tax_rate: f64,
    invested_capital: f64,
    multiplier: f64,
) -> PyResult<(f64, f64, f64)> {
    let nopat = ebita * (1.0 - tax_rate);
    let annualized_nopat = nopat * multiplier;
    let roic = if invested_capital != 0.0 {
        (annualized_nopat / invested_capital) * 100.0
    } else {
        0.0
    };
    Ok((nopat, annualized_nopat, roic))
}

/// A Python module implemented in Rust.
#[pymodule]
fn _rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(calculate_dcf, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_ebita, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_invested_capital, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_tax_rates, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_roic, m)?)?;
    Ok(())
}
