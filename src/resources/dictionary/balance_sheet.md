# Balance Sheet Line Item Classifications

This dictionary contains mappings of typical balance sheet line items to their classification: operating vs non-operating, and the category for non-operating items.

## Concepts & Explanations

### Operating vs Non-Operating

- **Operating (`Yes`)**: Operating assets and liabilities are those required for the day-to-day operations of the business. They are used to calculate Net Working Capital (NWC) and Net Long-Term Operating Assets (NLTOA), which sum to **Invested Capital**. This is critical for computing Return on Invested Capital (ROIC). Examples: Accounts Receivable, Inventory, Accounts Payable, Operating Lease Right-of-Use Assets, and Accrued Liabilities.
- **Non-Operating (`No`)**: Assets and liabilities that are not directly involved in core operations. These are excluded from Invested Capital. Examples: Cash, Short-Term Investments, Debt, and Equity.

### Non-Operating Category

The non-operating category indicates the specific type of non-operating asset or liability. This classification is critical for the valuation transition from **Enterprise Value (EV)** to **Equity Value**:

- **cash**: Cash and cash equivalents. Added to Enterprise Value to find Equity Value.
- **short_term_investments**: Liquid, marketable short-term investment securities. Added to Enterprise Value to find Equity Value.
- **debt**: Interest-bearing debt (short-term, long-term, and convertible debt). Subtracted from Enterprise Value to find Equity Value.
- **goodwill_intangibles**: Non-operating goodwill and acquired intangibles (which are separated from core operating assets to calculate ROIC under certain methodologies).
- **common_equity**: Common stock, additional paid-in capital, retained earnings, treasury stock, AOCI, etc. Used in the capital structure reconciliation.
- **preferred_equity**: Preferred stock.
- **minority_interest**: Non-controlling / minority interests.
- **other_financial_physical_assets**: Non-operating investments (long-term/equity method), assets held for sale, pension assets, etc. Added to or subtracted from Enterprise Value based on whether they represent non-operating value or obligations.
- **other_financial_liabilities**: Non-operating liabilities like liabilities held for sale, dividends payable, and pension liabilities.

---

## Classification Table

| Line Item                                | Operating | Non-Operating Category          |
| :--------------------------------------- | :-------- | :------------------------------ |
| Accounts payable                         | Yes       |                                 |
| Accounts payable accrued expenses        | Yes       |                                 |
| Accounts payable accrued liabilities     | Yes       |                                 |
| Accounts payable and accrued expenses    | Yes       |                                 |
| Accounts payable and accrued liabilities | Yes       |                                 |
| Accounts receivable                      | Yes       |                                 |
| Accounts receivable net                  | Yes       |                                 |
| Accrued and other current liabilities    | Yes       |                                 |
| Accrued benefits current                 | Yes       |                                 |
| Accrued capex liabilities                | Yes       |                                 |
| Accrued compensation                     | Yes       |                                 |
| Accrued liabilities                      | Yes       |                                 |
| Accrued litigation current               | No        | other_financial_liabilities     |
| Accrued revenue                          | Yes       |                                 |
| Accrued revenue share                    | Yes       |                                 |
| Accumulated deficit                      | No        | common_equity                   |
| Accumulated depreciation                 | Yes       |                                 |
| Accumulated other comprehensive income   | No        | common_equity                   |
| Additional paid in capital               | No        | common_equity                   |
| Advances from customers                  | Yes       |                                 |
| Advances to suppliers                    | Yes       |                                 |
| Aoci                                     | No        | common_equity                   |
| Assets held for sale                     | No        | other_financial_physical_assets |
| Buildings and improvements               | Yes       |                                 |
| Cash and equivalents                     | No        | cash                            |
| Cash and marketable securities           | No        | cash                            |
| Cash and short term investments          | No        | cash                            |
| Client funds obligations                 | Yes       |                                 |
| Client incentives current asset          | Yes       |                                 |
| Client incentives liability              | Yes       |                                 |
| Client incentives noncurrent asset       | Yes       |                                 |
| Commercial paper                         | No        | debt                            |
| Common stock                             | No        | common_equity                   |
| Common stock and apic                    | No        | common_equity                   |
| Common stock and paid in capital         | No        | common_equity                   |
| Computer hardware and software           | Yes       |                                 |
| Construction in progress                 | Yes       |                                 |
| Content advances                         | Yes       |                                 |
| Content assets net                       | Yes       |                                 |
| Content costs noncurrent                 | Yes       |                                 |
| Contract liabilities current             | Yes       |                                 |
| Convertible debt                         | No        | debt                            |
| Current assets operating subtotal        | Yes       |                                 |
| Current content liabilities              | Yes       |                                 |
| Current contract receivables net         | Yes       |                                 |
| Current debt                             | No        | debt                            |
| Current deferred revenue                 | Yes       |                                 |
| Current finance receivables net          | Yes       |                                 |
| Current financing receivables            | Yes       |                                 |
| Current income tax payable               | Yes       |                                 |
| Current income tax receivable            | Yes       |                                 |
| Current income taxes payable             | Yes       |                                 |
| Current lease liabilities                | Yes       |                                 |
| Current liabilities operating subtotal   | Yes       |                                 |
| Current notes receivable                 | No        |                                 |
| Current notes receivables                | No        |                                 |
| Current portion convertible debt         | No        | debt                            |
| Current portion long term debt           | No        | debt                            |
| Current portion notes payable            | No        | debt                            |
| Customer collateral assets               | Yes       |                                 |
| Customer collateral liability            | Yes       |                                 |
| Customer deposits escrow assets          | Yes       |                                 |
| Customer deposits liabilities            | Yes       |                                 |
| Customer funds payable                   | Yes       |                                 |
| Customer funds receivable                | Yes       |                                 |
| Customer restricted deposits             | Yes       |                                 |
| Customer restricted deposits liability   | Yes       |                                 |
| Deferred contract costs                  | Yes       |                                 |
| Deferred costs noncurrent                | Yes       |                                 |
| Deferred revenue current                 | Yes       |                                 |
| Deferred revenue noncurrent              | Yes       |                                 |
| Deferred tax assets                      | Yes       |                                 |
| Deferred tax assets and other            | Yes       |                                 |
| Deferred tax assets and other noncurrent | Yes       |                                 |
| Deferred tax assets noncurrent           | Yes       |                                 |
| Deferred tax liabilities                 | Yes       |                                 |
| Derivatives                              | No        | short_term_investments          |
| Dividends payable                        | No        | other_financial_liabilities     |
| Due from related parties current         | No        | other_financial_physical_assets |
| Due from related parties noncurrent      | No        | other_financial_physical_assets |
| Due to related parties current           | No        | debt                            |
| Due to related parties noncurrent        | No        | debt                            |
| Equity investments current               | No        | other_financial_physical_assets |
| Equity investments noncurrent            | No        | other_financial_physical_assets |
| Equity method investments                | No        | other_financial_physical_assets |
| Equity parent                            | No        | common_equity                   |
| Finance lease liabilities current        | Yes       |                                 |
| Finance lease liabilities noncurrent     | Yes       |                                 |
| Financial services assets                | Yes       |                                 |
| Financial services liabilities           | Yes       |                                 |
| Financing receivables current            | Yes       |                                 |
| Financing receivables noncurrent         | Yes       |                                 |
| Fixtures and equipment                   | Yes       |                                 |
| Franchisee deposits liability            | Yes       |                                 |
| Funds held for clients                   | Yes       |                                 |
| Funds held for customers asset           | Yes       |                                 |
| Funds held for customers liability       | Yes       |                                 |
| Gift card liability                      | Yes       |                                 |
| Ginnie mae loans asset                   | Yes       |                                 |
| Ginnie mae loans liability               | Yes       |                                 |
| Goodwill                                 | No        | goodwill_intangibles            |
| Goodwill and intangible assets           | No        | goodwill_intangibles            |
| Goodwill and intangibles                 | No        | goodwill_intangibles            |
| Indefinite lived trademarks              | Yes       |                                 |
| Intangible assets                        | No        | goodwill_intangibles            |
| Intangible assets net                    | No        | goodwill_intangibles            |
| Intangibles net                          | No        | goodwill_intangibles            |
| Inventory                                | Yes       |                                 |
| Inventory homes in progress and finished | Yes       |                                 |
| Inventory land and lots                  | Yes       |                                 |
| Inventory rental properties              | Yes       |                                 |
| Land                                     | Yes       |                                 |
| Land use rights                          | Yes       |                                 |
| Liabilities held for sale                | No        | other_financial_liabilities     |
| Licensed copyrights                      | Yes       |                                 |
| Loans payable                            | No        | debt                            |
| Long term bank borrowings                | No        | debt                            |
| Long term content liabilities            | Yes       |                                 |
| Long term convertible notes              | No        | debt                            |
| Long term debt                           | No        | debt                            |
| Long term debt related party             | No        | debt                            |
| Long term deferred revenue               | Yes       |                                 |
| Long term exchangeable bonds             | No        | debt                            |
| Long term income tax payable             | Yes       |                                 |
| Long term income taxes payable           | Yes       |                                 |
| Long term investment securities          | No        | other_financial_physical_assets |
| Long term investments                    | No        | other_financial_physical_assets |
| Long term investments other              | No        | other_financial_physical_assets |
| Long term lease liabilities              | Yes       |                                 |
| Long term marketable securities          | No        | other_financial_physical_assets |
| Long term unsecured notes                | No        | debt                            |
| Marketable securities current            | No        | short_term_investments          |
| Medical costs payable                    | Yes       |                                 |
| Merchant deposits                        | Yes       |                                 |
| Mezzanine equity                         | No        | preferred_equity                |
| Mortgage and loans payable current       | No        | debt                            |
| Mortgage and loans payable noncurrent    | No        | debt                            |
| Mortgage facility debt                   | No        | debt                            |
| Mortgage inventory                       | Yes       |                                 |
| Mortgage loans held for sale             | Yes       |                                 |
| Noncontrolling interest                  | No        | minority_interest               |
| Noncontrolling interests                 | No        | minority_interest               |
| Noncurrent contract receivables net      | Yes       |                                 |
| Noncurrent deferred revenue              | Yes       |                                 |
| Noncurrent finance receivables net       | Yes       |                                 |
| Noncurrent financing receivables         | Yes       |                                 |
| Noncurrent income tax liabilities        | Yes       |                                 |
| Noncurrent income taxes payable          | Yes       |                                 |
| Noncurrent lease liabilities             | Yes       |                                 |
| Noncurrent lease receivables             | Yes       |                                 |
| Noncurrent notes receivable              | No        |                                 |
| Noncurrent notes receivables             | No        |                                 |
| Operating lease assets                   | Yes       |                                 |
| Operating lease liabilities              | Yes       |                                 |
| Operating lease liabilities current      | Yes       |                                 |
| Operating lease liabilities noncurrent   | Yes       |                                 |
| Operating lease right of use assets      | Yes       |                                 |
| Other accrued liabilities                | No        | other_financial_liabilities     |
| Other current assets                     | Yes       |                                 |
| Other current liabilities                | No        | other_financial_liabilities     |
| Other noncurrent assets                  | Yes       |                                 |
| Other noncurrent liabilities             | No        | other_financial_liabilities     |
| Parent equity                            | No        | common_equity                   |
| Pension and postretirement benefits      | No        | other_financial_liabilities     |
| Pension assets                           | No        | other_financial_physical_assets |
| Pension liabilities                      | No        | other_financial_liabilities     |
| Pension liabilities noncurrent           | No        | other_financial_liabilities     |
| Postretirement benefit liabilities       | No        | other_financial_liabilities     |
| Postretirement benefits noncurrent       | No        | other_financial_liabilities     |
| Preferred stock                          | No        | preferred_equity                |
| Prepaid and other current assets         | Yes       |                                 |
| Prepaid expenses                         | Yes       |                                 |
| Prepayments and other current assets     | Yes       |                                 |
| Produced content                         | Yes       |                                 |
| Property plant and equipment             | Yes       |                                 |
| Property plant and equipment gross       | Yes       |                                 |
| Property plant and equipment net         | Yes       |                                 |
| Property plant equipment                 | Yes       |                                 |
| Property plant equipment gross           | Yes       |                                 |
| Property plant equipment net             | Yes       |                                 |
| Receivables prepaid and other assets     | Yes       |                                 |
| Redeemable noncontrolling interests      | No        | minority_interest               |
| Restricted cash                          | No        | cash                            |
| Retained earnings                        | No        | common_equity                   |
| Retained earnings deficit                | No        | common_equity                   |
| Reverse repurchase obligations           | No        | debt                            |
| Right of use assets                      | Yes       |                                 |
| Settlement assets                        | Yes       |                                 |
| Settlement obligations                   | Yes       |                                 |
| Settlement payable                       | Yes       |                                 |
| Settlement receivable                    | Yes       |                                 |
| Short term debt                          | No        | debt                            |
| Short term debt related party            | No        | debt                            |
| Short term investment                    | No        | short_term_investments          |
| Short term investments                   | No        | short_term_investments          |
| Statutory reserves                       | No        | common_equity                   |
| Stock dividends                          | No        | common_equity                   |
| Taxes payable current                    | Yes       |                                 |
| Taxes payable noncurrent                 | Yes       |                                 |
| Total assets                             | No        |                                 |
| Total cash and equivalents               | No        |                                 |
| Total cash and investments               | No        |                                 |
| Total current assets                     | No        |                                 |
| Total current liabilities                | No        |                                 |
| Total current operating assets           | Yes       |                                 |
| Total current operating liabilities      | Yes       |                                 |
| Total equity                             | No        |                                 |
| Total equity combined                    | No        |                                 |
| Total equity parent                      | No        |                                 |
| Total inventory                          | Yes       |                                 |
| Total liabilities                        | No        |                                 |
| Total liabilities and equity             | No        |                                 |
| Total liabilities mezzanine and equity   | No        |                                 |
| Total noncurrent assets                  | No        |                                 |
| Total noncurrent liabilities             | No        |                                 |
| Total parent equity                      | No        |                                 |
| Treasury stock                           | No        | common_equity                   |
| Unbilled receivables                     | Yes       |                                 |
| Vendor non trade receivables             | Yes       |                                 |
