# Refactoring Ideas

The modeler needs to pull (deterministic script):

1. **[Implemented]** Base revenue, which should be the LTM. If LTM is absolutely not available, then take the available quarters and annualize with a warning in the markdown.
2. **[Implemented]** Base invested capital, which should be the median of LTM. If LTM is absolutely not available, then take the median of the available quarters with a warning in the markdown.
3. **[Implemented]** Adjusted tax rate, which should be the median of all available quarters.

**[Implemented]** model output markdown needs to show the last four quarters (or what's availabe), then the Base (Year 0), then the project Year 1, 2, 3, 4,... 10, terminal.

**[Implemented]** The columns of the markdown should be: Time Period, Revenue ($M), Growth (%), EBITA Margin (%), Invested Capital ($M), Free Cash Flow ($M), Discount Factor (this should include the mid-year adjustment), Discounted FCF.
