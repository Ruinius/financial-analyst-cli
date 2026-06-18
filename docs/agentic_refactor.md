# Refactoring Ideas

The modeler needs to pull (deterministic script):

1. **[Implemented]** Base revenue, which should be the LTM. If LTM is absolutely not available, then take the available quarters and annualize with a warning in the markdown.
2. **[Implemented]** Base invested capital, which should be the median of LTM. If LTM is absolutely not available, then take the median of the available quarters with a warning in the markdown.
3. **[Implemented]** Adjusted tax rate, which should be the median of all available quarters.

**[Implemented]** model output markdown needs to show the last four quarters (or what's availabe), then the Base (Year 0), then the project Year 1, 2, 3, 4,... 10, terminal.

**[Implemented]** The columns of the markdown should be: Time Period, Revenue ($M), Growth (%), EBITA Margin (%), Invested Capital ($M), Free Cash Flow ($M), Discount Factor (this should include the mid-year adjustment), Discounted FCF.

**[Implemented]** In the Valuation section, the following rows should be present:
| Field | Value |
| ----------------------------- | ------------- |
| Enterprise Value | $186,681M | this is the sum of the Discounted FCF
| (+) Cash and Equivalents | $6,890M | these are the non-operating items. They should all be listed out.
| (-) Total Debt | $6,228M |
| **Equity Value** | **$187,343M** |
| Diluted Shares Outstanding | 411M |
| **Intrinsic Value Per Share** | **$455.82** |
| Currency | USD |
| FX Rate Applied | 1.0000 |
| ADR Ratio Applied | 1.0 |
| Current Market Price | $250.17 |
| **Upside/Downside** | **+82.2%** |

Here is another example:
| Field | Value |
|-------|-------|
| Enterprise Value | $2,538,375M |
| (+) Cash and Equivalents | $308,129M |
| (-) Total Debt | $194,715M |
| **Equity Value** | **$2,651,789M** |
| Diluted Shares Outstanding | 2414M |
| **Intrinsic Value Per Share** | **$164.79** |
| Currency | USD |
| FX Rate Applied | 0.1500 |
| ADR Ratio Applied | 8.0 |
| Current Market Price | $130.76 |
| **Upside/Downside** | **+26.0%** |
| Calculation Date | 2026-04-29 |
