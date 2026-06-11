# Income Statement Line Item Classifications

This dictionary contains mappings of typical income statement line items to their classification: operating vs non-operating, and whether they are expenses.

## Concepts & Explanations

### Operating vs Non-Operating
- **Operating (`Yes`)**: Line items directly related to the core ongoing operations of the business. These are included in the calculation of Operating Income (EBIT/EBITA), representing the fundamental earning power of the company's business activities. Examples: Revenues, Cost of Revenue, SG&A, R&D, and Depreciation of operating assets.
- **Non-Operating (`No`)**: Line items representing financing, investing, tax, or peripheral/one-off transactions. These are excluded from Operating EBIT/EBITA to evaluate core business performance cleanly. Examples: Interest Expense, Interest Income, Restructuring charges, asset impairments, and investment gains/losses.

### Expense
- **Expense (`Yes`)**: Outflows or consumption of assets in the course of business. Identifying a line item as an expense (`Yes`) helps determine whether it should be added or subtracted when parsing the statement.
- **Why this guidance is necessary**: Companies use positive and negative numbers freely and inconsistently. For example, some list expenses as positive numbers under an "Expenses" block, while others list them as negative numbers. Knowing if a line item is fundamentally an expense serves as guidance when resolving sign ambiguity and ensuring mathematical summations (like Total Expenses or Net Income) match the expected relationships.

---

## Classification Table

| Line Item | Operating | Expense |
| :--- | :--- | :--- |
| Acquisition termination fee | No | Yes |
| Amortization acquired | No | Yes |
| Amortization and impairment of intangibles | No | Yes |
| Amortization internal | Yes | Yes |
| Amortization of acquired intangibles | No | Yes |
| Amortization of acquired technology operating | No | Yes |
| Amortization of developed technologies | Yes | Yes |
| Amortization of intangibles operating | No | Yes |
| Amortization of intangibles opex | No | Yes |
| Amortization of purchased intangibles opex | No | Yes |
| Asset impairment charges | No | Yes |
| Compensation | Yes | Yes |
| Compensation and benefits expense | Yes | Yes |
| Consulting revenue | Yes | No |
| Cost of goods sold | Yes | Yes |
| Cost of goods sold header | Yes | Yes |
| Cost of home sales | Yes | Yes |
| Cost of land sales and other | Yes | Yes |
| Cost of product and other revenue | Yes | Yes |
| Cost of product revenue | Yes | Yes |
| Cost of products | Yes | Yes |
| Cost of products sold | Yes | Yes |
| Cost of revenue | Yes | Yes |
| Cost of revenue financial services | Yes | Yes |
| Cost of revenue header | Yes | Yes |
| Cost of revenue homebuilding | Yes | Yes |
| Cost of revenue other | Yes | Yes |
| Cost of revenue product | Yes | Yes |
| Cost of revenue service | Yes | Yes |
| Cost of revenue subscription and maintenance | Yes | Yes |
| Cost of service revenue | Yes | Yes |
| Cost of services | Yes | Yes |
| Cost of services and other revenue | Yes | Yes |
| Cost of subscription revenue | Yes | Yes |
| Debt extinguishment gain loss | No | No |
| Debt extinguishment loss | No | No |
| Depreciation and amortization | Yes | Yes |
| Depreciation and amortization operating | Yes | Yes |
| Depreciation and amortization opex | Yes | Yes |
| Depreciation expense | Yes | Yes |
| Depreciation expense operating | Yes | Yes |
| Discontinued operations | No | No |
| Ebit | Yes | No |
| Eliminations | Yes | Yes |
| Equipment and rents expense | Yes | Yes |
| Equity method earnings | No | No |
| Equity method income loss | No | No |
| Equity method investment activity | No | No |
| Equity method investment earnings net | No | No |
| Equity method investment income | No | No |
| Equity method investment income financial services | No | No |
| Equity method investment loss | No | No |
| Expenses financial services | Yes | Yes |
| Financing revenue | Yes | No |
| Foreign exchange gain loss net | No | No |
| Freight in expense | Yes | Yes |
| Freight revenue | Yes | No |
| Fuel expense | Yes | Yes |
| Fulfillment expense | Yes | Yes |
| Gain loss divestitures | No | No |
| Gain loss on asset disposition operating | No | No |
| Gain loss on equity investments | No | No |
| General administrative expense | Yes | Yes |
| General and administrative expense | Yes | Yes |
| Goodwill impairment | No | Yes |
| Gross profit | Yes | No |
| Gross profit home sales | Yes | No |
| Gross profit land sales and other | Yes | No |
| Gross revenue | Yes | No |
| Impairment and restructuring charges | No | Yes |
| Impairment charges operating | No | Yes |
| Income before taxes | No | No |
| Income tax provision | Yes | Yes |
| Information technology expense | Yes | Yes |
| Infrastructure revenue | Yes | No |
| Intangible asset impairment | No | Yes |
| Interest and dividend income | No | No |
| Interest and investment income | No | No |
| Interest and investment income net | No | No |
| Interest and other income | No | No |
| Interest and other income net | No | No |
| Interest expense | No | Yes |
| Interest expense banking | Yes | Yes |
| Interest expense net | No | Yes |
| Interest income | No | No |
| Interest income and other non operating | No | No |
| Interest income banking | Yes | No |
| Interest income expense net | No | Yes |
| Investment income and other non operating | No | No |
| Investment income net | No | No |
| Investment income non operating | No | No |
| Ip and development income | Yes | No |
| Litigation expense | No | Yes |
| Litigation provision operating | No | Yes |
| Litigation settlement expense | No | Yes |
| Loss on business disposal operating | No | No |
| Loss on sale of subsidiaries | No | No |
| Marketing and demand creation expense | Yes | Yes |
| Marketing expense | Yes | Yes |
| Medical costs | Yes | Yes |
| Merchandise expense | Yes | Yes |
| Merger and acquisition costs | No | Yes |
| Net income | No | No |
| Net income consolidated | No | No |
| Net income continuing operations | No | No |
| Net income loss | No | No |
| Net income noncontrolling | No | No |
| Net income parent | No | No |
| Net interest income banking | Yes | No |
| Net sales | Yes | No |
| Network and processing expense | Yes | Yes |
| Online marketing revenue | Yes | No |
| Operating expenses | Yes | Yes |
| Operating gain loss dispositions | No | No |
| Operating gains other | No | No |
| Operating income | Yes | No |
| Operating income financial services | Yes | No |
| Operating income homebuilding | Yes | No |
| Operating income loss | Yes | No |
| Operating income operations | Yes | No |
| Operating investment income loss | No | No |
| Operating loss divestitures | No | No |
| Operating overhead expense | Yes | Yes |
| Operations and support expense | Yes | Yes |
| Other income expense net | No | No |
| Other non operating expense | No | No |
| Other non operating income | No | No |
| Other non operating income expense net | No | No |
| Other non operating income net | No | No |
| Other operating charges | Yes | Yes |
| Other operating expense | Yes | Yes |
| Other operating expense net | Yes | Yes |
| Other operating gains net | Yes | No |
| Other operating income expense net | Yes | No |
| Other operating revenue | Yes | No |
| Other pension benefit costs | No | Yes |
| Other revenue | Yes | No |
| Personnel expense | Yes | Yes |
| Premium revenue | Yes | No |
| Pretax income | No | No |
| Pretax income financial services | No | No |
| Pretax income homebuilding | No | No |
| Product and other revenue | Yes | No |
| Product revenue | Yes | No |
| Professional fees expense | Yes | Yes |
| Purchased services and materials expense | Yes | Yes |
| Research and development expense | Yes | Yes |
| Restructuring and impairment charges | No | Yes |
| Restructuring and other exit costs | No | Yes |
| Restructuring and transformation costs | No | Yes |
| Restructuring charges | No | Yes |
| Restructuring costs | No | Yes |
| Restructuring expense | No | Yes |
| Restructuring expense cogs | No | Yes |
| Restructuring expense operating | No | Yes |
| Restructuring expense opex | No | Yes |
| Revenue | Yes | No |
| Revenue adjustments | Yes | Yes |
| Revenue advertising and other | Yes | No |
| Revenue agency | Yes | No |
| Revenue financial services | Yes | No |
| Revenue home sales | Yes | No |
| Revenue homebuilding | Yes | No |
| Revenue land sales and other | Yes | No |
| Revenue maintenance | Yes | No |
| Revenue merchant | Yes | No |
| Revenue non recurring | Yes | No |
| Revenue other | Yes | No |
| Revenue product | Yes | No |
| Revenue recurring | Yes | No |
| Revenue service | Yes | No |
| Revenue subscription | Yes | No |
| Revenue subtotal | Yes | No |
| Sales and marketing expense | Yes | Yes |
| Sales and other operating expense | Yes | Yes |
| Sales discounts | Yes | Yes |
| Sales general and administrative expense | Yes | Yes |
| Segment cost of revenue | Yes | Yes |
| Segment gross profit | Yes | No |
| Segment operating income | Yes | No |
| Segment pretax income | No | No |
| Segment revenue | Yes | No |
| Segment revenue subtotal | Yes | No |
| Selling and administrative expense | Yes | Yes |
| Selling and marketing expense | Yes | Yes |
| Selling general and administrative expense | Yes | Yes |
| Selling marketing expense | Yes | Yes |
| Service revenue | Yes | No |
| Services and other revenue | Yes | No |
| Software revenue | Yes | No |
| Subscription revenue | Yes | No |
| Technology and infrastructure expense | Yes | Yes |
| Total cost of goods sold | Yes | Yes |
| Total cost of revenue | Yes | Yes |
| Total cost of sales | Yes | Yes |
| Total costs and expenses | Yes | Yes |
| Total expense and other income | No | No |
| Total expenses | No | Yes |
| Total non operating income expense | No | No |
| Total non operating income expense net | No | No |
| Total non operating interest and other net | No | No |
| Total operating expenses | Yes | Yes |
| Total other income expense net | No | No |
| Total revenue | Yes | No |
