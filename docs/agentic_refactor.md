# Agentic Refactor Plan: Financial Statement Extraction & Interpretation

Deterministic parsing of financial statements often fails due to the vast diversity in corporate reporting layouts, terminology, and footnote disclosures. To handle this variability robustly, we are transitioning from brittle deterministic rules to a flexible, multi-agent architecture.

---

## 1. Core Objectives
- **Acknowledge Non-Deterministic Layouts:** Accept that financial reporting structures are inherently heterogeneous.
- **Inject Agentic Judgment:** Use LLM-based agents for classification, subtotal validation, and key metric extraction where layout rules fail.
- **Maintain Mathematical Integrity:** Combine agentic interpretation with deterministic calculation scripts (Rust/Python fallbacks) to ensure mathematical correctness.

---

## 2. Pipeline & Agent Specification

### Phase A: Core Financial Extraction (Structured Output)
1. **Balance Sheet Extraction Agent**
   - **Status:** `DONE`
   - **Responsibility:** Extract raw tabular data of assets, liabilities, and equity from financial documents into structured JSON.

2. **Income Statement Extraction Agent**
   - **Status:** `DONE`
   - **Responsibility:** Extract raw tabular revenue, expense, and income lines.

### Phase B: Interpretation & Classification
3. **Financial Statement Interpretation Agent**
   - **Status:** `DONE`
   - **Responsibility:** Inspect the extracted Balance Sheet and Income Statement to:
     - Distinguish between raw items, subtotals, and totals (`calculated_line` classification).
     - Categorize items as **operating** versus **non-operating**.
     - Handle unnamed or ambiguous line items by interpreting context, indentation, spacing, and placement.
     - Perform cross-statement quality checks to verify that subtotals match the sum of their constituent line items.

4. **Diluted Shares Outstanding Agent**
   - **Status:** `DONE`
   - **Responsibility:** Execute a targeted, low-latency search (maximum 4–5 turns) with access to the already extracted Income Statement, using keyword context (`find_key_word_context`) to extract correct diluted shares outstanding for the reported periods.

### Phase C: Derived Metric Calculation
5. **Organic Growth Agent**
   - **Status:** `DONE`
   - **Responsibility:**
     - Scan the parsed document for mentions of organic growth, constant currency (CC) adjustments, and merger & acquisition (M&A) contributions, with direct access to the already extracted Income Statement.
     - Retrieve reported revenue numbers from the Income Statement.
     - If organic growth is explicitly reported, extract and verify it.
     - Otherwise, dynamically compute the organic growth rate by executing the growth calculation script with adjusted revenue figures (e.g., backing out acquisitions or adjusting for constant currency exchange rates).
     - *Example:* If revenue is $11.1B (up 13% reported, 12% CC) and includes a $444M acquisition contribution:
       $$\text{Organic Growth} = 12\% \text (CC) - \left(\frac{\$444\text{M}}{\$11.1\text{B}}\right) = 12\% - 4\% = 8\%$$

6. **Operating EBITA Agent**
   - **Status:** `DONE`
   - **Responsibility:**
     - Locate the operating income line item (or nearest equivalent) on the Income Statement (with direct access to the extracted Income Statement).
     - Identify and back out non-operating line items listed above operating income.
     - Search the rest of the document for non-operating or non-recurring adjustments (e.g., restructuring charges, amortization of intangibles, asset write-offs).
     - Make reasoned judgment calls to determine if these items are already accounted for or constitute duplicates, then compute the clean Operating EBITA.

7. **Adjusted Taxes Agent**
   - **Status:** `DONE`
   - **Responsibility:**
     - Locate the reported income tax line using access to the extracted Income Statement.
     - Calculate adjusted taxes by backing out the tax effect of non-operating items (using a standard statutory tax rate of 25%: 21% federal, 4% state/local) from the operating income and adjusted items.
     - Apply agent judgment to identify non-recurring tax benefits or adjustments in footnotes.

### Phase D: Deterministic Calculations
- Once the agents complete categorization and alignment, run deterministic scripts (via Rust calculation engine or Python fallbacks) to compute:
  - **Invested Capital**
  - **Return on Invested Capital (ROIC)** (annualized)
  - **Capital Turnover** (annualized)

---

## 3. Qualitative Report Refinement

8. **Analyst Report Agent**
   - **Status:** `DONE`
   - **Responsibility:** Refactor the existing single-turn LLM call into a multi-turn, interactive reasoning agent that synthesizes analyst views, assesses qualitative trends, and verifies source citations.

---

## 4. Scope Exclusions (Deferred to Future Phases)
- **Transcript Parsing & Other Documents:** Maintain current heuristic/single-turn processing; defer full agentic refactoring.
