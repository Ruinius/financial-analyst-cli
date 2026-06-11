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

/// A Python module implemented in Rust.
#[pymodule]
fn _rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(calculate_dcf, m)?)?;
    Ok(())
}
