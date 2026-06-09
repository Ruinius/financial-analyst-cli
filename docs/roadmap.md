# Development Roadmap: Financial Analyst CLI

This document outlines the phased development roadmap for the Financial Analyst CLI (`fa`). It breaks down the system requirements into six logical, incremental milestones.

---

## Roadmap Overview

```
Phase 1 ──> Phase 2 ──> Phase 3 ──> Phase 4 ──> Phase 5 ──> Phase 6
Config      Ingestion   Extraction  History     Modeling    Interactive
& Setup     & SEC API   & Metrics   & Trends    & DCF       HTML Viewer
```

---

## Phase 1: Environment & CLI Framework

**Goal**: Establish the base command-line structure, the identity of Sir Pennyworth, and workspace folder configurations.

- **1.1 CLI & Character UI**:
  - Implement `fa` CLI using [Typer](https://typer.tiangolo.com/).
  - Set up Sir Pennyworth ASCII art and custom terminal styling using [Rich](https://rich.readthedocs.io/).
- **1.2 Settings & Configuration (`fa config`)**:
  - Build `fa config init` to guide users through name, email, project name, API keys, and workspace path configuration.
  - Build `fa config show` with masked API keys.
  - Implement workspace validation that checks for and automatically initializes the 8 folders (`1_ingest_data/` to `8_historical_model_json/`) with boilerplate instructions.
  - Build the workspace switching command `fa use <ticker>` to set active workspace paths dynamically.

---

## Phase 2: Ingestion & Filing Downloader

**Goal**: Implement SEC EDGAR retrieval, file hashing to prevent duplicates, text parsing, and file renaming.

- **2.1 EDGAR Client (`fa run edgar`)**:
  - Build the SEC EDGAR API client using correct, declaring User-Agent headers.
  - Download filings (10-K, 10-Q, 20-F) for a given ticker up to a 5-year limit to `1_ingest_data/`.
- **2.2 Ingestion Engine (`fa run ingest`)**:
  - Build a deterministic sequential queue manager to execute ingestion jobs.
  - Compute SHA-256 hashes of incoming files, check against `parsed_data.csv`, and skip duplicates.
  - Build a formatting-preserving parser (PDF/HTML to Markdown) that maintains layout integrity.
- **2.3 Chunker & Metadata Identification**:
  - Implement the 5,000-character chunking algorithm and prepend `chunk_id=0` indices.
  - Integrate LLM to detect true document dates, quarters, and types.
  - Rename files to `YYYYMMDD_document_type.md` (and raw equivalent in `3_archived_data/`).
  - Create and update `6_company_context/ingest_context.md`.

---

## Phase 3: Extraction & Financial Calculations

**Goal**: Process parsed files chunk-by-chunk to extract statements and calculate financial metrics.

- **3.1 Chunk-by-Chunk Agent**:
  - Implement the LLM extraction agent that reads `chunk_id=0` first and requests specific chunks sequentially.
  - Output intermediate chunk-by-chunk notes to `YYYYMMDD_filetype_extracted.md`.
- **3.2 Task-Specific Extraction & Traceability**:
  - Extract relevant sections (Balance Sheet, Income Statement, Moat indicators, Press release announcements) based on document type.
  - Bind metadata containing `source_file`, `chunk_id`, and `exact_snippet` to every extracted numerical figure for auditing.
- **3.3 Financial Calculation Engine & Rust Boundaries**:
  - Build the Operating/Non-Operating classifier using LLM judgment, local dictionary lookups, and Investopedia web search fallbacks.
  - Define strict Pydantic schemas to validate financial data before passing to Rust.
  - Expand the **Rust Core Engine** via PyO3 to calculate Invested Capital, EBITA, Adjusted Taxes, NOPAT, and ROIC schedules.
  - Create and update `6_company_context/extract_context.md`.
  - Propagate audit lineage through all derived metrics calculations.

---

## Phase 4: Longitudinal Synthesis & Historical Trends

**Goal**: Synthesize multi-period metrics and trends into single markdown reports.

- **4.1 Qualitative Trend Synthesis**:
  - Compile analyst views (moat, margins, growth changes over time) into `5_historical_analysis/analyst_views.md`.
  - Track press trends and conference call transcripts in `news_trend.md` and `transcript_trend.md`.
- **4.2 Quantitative Trend Synthesis**:
  - Build the longitudinal financials processor to update `financials_quarter.md` and `financials_annual.md`.
  - Implement Q4 deduction logic (Annual minus Q1-Q3).

---

## Phase 5: Assumptions & Valuation Modeling

**Goal**: Establish DCF assumptions and perform valuation modeling.

- **5.1 Default Assumptions Calculator**:
  - Develop deterministic estimators for base WACC, capital turnover, and growth rates.
- **5.2 Modeler Agent (`fa run model`)**:
  - Leverage historical financials and analyst views to estimate final assumptions.
  - Display the interactive assumptions table to the user for feedback.
  - Save adjustments to `6_company_context/model_context.md`.
- **5.3 Financial Model Generation**:
  - Generate the DCF model markdown inside `7_financial_model/`.
  - Output the baseline model JSON (`YYYYMMDD_ticker_0.json`) inside `8_historical_model_json/`.

---

## Phase 6: HTML Viewer & CLI Queries

**Goal**: Construct local user query utilities and the interactive DCF HTML application.

- **6.1 CLI Query & Trace Engine (`fa query`)**:
  - Implement `fa query summary <ticker>`, `fa query assessment <ticker>`, and `fa query valuation <ticker>`.
  - Implement `fa query trace <ticker> <metric> <period>` to render the audit trial/provenance of any metric from raw chunks.
- **6.2 Interactive REPL / Analyst Chat (`fa chat`)**:
  - Implement the interactive console-based session with Sir Pennyworth.
  - Integrate a sandboxed dynamic math execution context for custom math formulas.
- **6.3 DCF Viewer Server (`fa viewer`)**:
  - Build the zero-dependency interactive HTML browser viewer.
  - Setup a simple Python server to launch the viewer, read from `8_historical_model_json/`, and write back updated override JSON versions (e.g. `YYYYMMDD_ticker_1.json`).
