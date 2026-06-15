# Development Roadmap: Financial Analyst CLI

This document outlines the phased development roadmap for the Financial Analyst CLI (`fa`). It breaks down the system requirements into six logical, incremental milestones.

> [!NOTE]
> The legacy `scripts/` directory containing copied scripts from the old `financial-analyst-skills` repository has been cleaned up. Active components (like `document_types.json` and `market_data.py`) have been moved into the main application structure under `src/`.

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
  - [x] Implement `fa` CLI using [Typer](https://typer.tiangolo.com/).
  - [x] Set up Sir Pennyworth ASCII art and custom terminal styling using [Rich](https://rich.readthedocs.io/).
- **1.2 Settings & Configuration (`fa config`)**:
  - [x] Build `fa config init` to guide users through name, email, project name, API keys, and workspace path configuration.
  - [x] Build `fa config show` with masked API keys.
  - [x] Implement workspace validation that checks for and automatically initializes the 7 folders (`1_ingest_data/` to `7_historical_model_json/`) with boilerplate instructions and default wiki/learning files.
  - [x] Build the workspace switching command `fa use <ticker>` to set active workspace paths dynamically.
  - [x] Migrate configuration settings entirely from the global plaintext JSON file (`~/.financial_analyst_cli.json`) to a local `.env` file in the project root, covering all fields (e.g., name, email, project, base workspace, and API keys).
  - [x] **Cross-Platform Default Workspace to Desktop**: Update the configuration initialization to default the base workspace directory (`base_workspace_dir`) to the user's Desktop. Resolve this dynamically using Python's `pathlib.Path.home() / "Desktop"` to ensure cross-platform compatibility across Windows, macOS, and Linux.
  - [x] **Dynamic Ticker Workspace Creation in `fa use <ticker>`**: Update the `fa use <ticker>` command. When switched to a ticker, check if a folder with that ticker name (force uppercase) exists in the configured base workspace. If it does not exist, automatically create the ticker directory and initialize the 7 standard workspace folders (from `1_ingest_data/` to `7_historical_model_json/`) inside it, then update the active workspace path.
  - [x] **Startup Config Auto-Detection**: Modify the CLI entrypoint (`main.py` or `src/cli/main.py`) to check `config_exists()` _before_ invoking the Typer application `app()`. If the configuration is missing, immediately run the `initialize_config_flow()` interactive setup instead of letting Typer exit with the help screen due to `no_args_is_help=True`.
  - [x] **Animated Setup Flow**: Integrate the dynamic Pig ASCII animation (snout wiggling and ear flapping via `prompt_toolkit`'s async prompt loop) directly into the interactive setup prompts in [config.py](src/cli/commands/config.py), ensuring Sir Pennyworth is fully animated during the first-time config wizard.
  - [x] **Verify dotenv content during startup**: Update startup check to verify if the `.env` file contains Sir Pennyworth's configuration settings (e.g. `FULL_NAME`, `EMAIL`), rather than just checking if the file `.env` exists, to determine if it's the user's first time.
- **1.3 Testing & Verification**:
  - [x] Setup the `pytest` testing suite and configuration.
  - [x] Implement unit tests for configuration parsing, masking, CLI command calls, and directory structure initialization using mock parameters.

---

## Phase 2: Ingestion & Filing Downloader

**Goal**: Implement SEC EDGAR retrieval, file hashing to prevent duplicates, text parsing, and file renaming.

- **2.1 EDGAR Client (`fa run edgar`)**:
  - [x] Build the SEC EDGAR API client using correct, declaring User-Agent headers.
  - [x] Download filings (10-K, 10-Q, 20-F) for a given ticker up to a 5-year limit to `1_ingest_data/`.
- **2.2 Ingestion Engine (`fa run ingest`)**:
  - [x] Build a deterministic sequential queue manager to execute ingestion jobs.
  - [x] Compute SHA-256 hashes of incoming files, check against `parsed_data.csv`, and skip duplicates.
  - [x] Build a formatting-preserving parser that maintains layout integrity, using BeautifulSoup for HTML files and PyMuPDF (`pymupdf`'s layout mode) for PDF files to preserve text alignment and table spacing.
- **2.3 Chunker & Metadata Identification**:
  - [x] Implement the 5,000-character chunking algorithm and prepend `chunk_id=0` indices.
  - [x] Integrate LLM to detect true document dates, quarters, and types.
  - [x] Rename files to `YYYYMMDD_document_type.md` (and raw equivalent in `3_archived_data/`).
  - [x] Trigger the Curator Agent to update `[TICKER]_extract_learning.md` and `[TICKER]_wiki.md` in root.
- **2.4 Testing & Verification**:
  - [x] Mock the SEC EDGAR API calls to verify downloader functionality.
  - [x] Test sequential job queuing, SHA-256 deduplication hashing, chunking outputs, and renaming logic using temporary directory fixtures (`tmp_path`).

---

## Phase 3: Extraction & Financial Calculations

**Goal**: Process parsed files chunk-by-chunk to extract statements and calculate financial metrics.

- **3.1 Chunk-by-Chunk Agent**:
  - [x] Implement the LLM extraction agent that reads `chunk_id=0` first and requests specific chunks sequentially.
  - [x] Output intermediate chunk-by-chunk notes to `YYYYMMDD_filetype_extracted.md`.
  - [x] **Agentic Refactor (Core Extraction)**: Transition to dedicated agents for structured output:
    - [x] **Balance Sheet Agent**: Extract raw tabular data of assets, liabilities, and equity from financial documents.
    - [x] **Income Statement Agent**: Extract raw tabular revenue, expense, and income lines with standard sign representation.
- **3.2 Task-Specific Extraction & Traceability**:
  - [x] Extract relevant sections (Balance Sheet, Income Statement, Moat indicators, Press release announcements) based on document type.
  - [x] Bind metadata containing `source_file`, `chunk_id`, and `exact_snippet` to every extracted numerical figure for auditing.
- **3.3 Financial Calculation Engine & Rust Boundaries**:
  - [x] Build the Operating/Non-Operating classifier using LLM judgment, central dictionary lookups, and Investopedia web search fallbacks (using `duckduckgo-search`).
  - [x] **Interpretation & Classification Agents**:
    - [x] **Financial Statement Interpretation Agent**: Classify lines as `calculated` (subtotals/totals) or raw items, identify operating vs non-operating items, interpret ambiguous/generic lines, and perform cross-statement mathematical checks.
    - [x] **Diluted Shares Outstanding Agent**: Target basic & diluted shares outstanding with a low-latency 4-turn search.
  - [x] **Derived Metric Calculation Agents**:
    - [x] **Organic Growth Agent**: Extract constant currency adjustments, back out M&A contributions, and calculate organic revenue growth rates.
    - [x] **Operating EBITA Agent**: Adjust operating income by identifying non-recurring adjustments (restructuring, amortization, impairment).
    - [x] **Adjusted Taxes Agent**: Back out tax effects of non-operating adjustments at a statutory tax rate (25%) and inspect footnotes for non-recurring benefits.
  - [x] Seed the central dictionary (`src/resources/dictionary/`) with an initial `index.md` and basic accounting definitions/treatment markdowns.
  - [x] Define strict Pydantic schemas to validate financial data before passing to Rust.
  - [x] Expand the **Rust Core Engine** via PyO3 to calculate Invested Capital, EBITA, Adjusted Taxes, NOPAT, and ROIC schedules.
  - [x] Trigger the Curator Agent to update extraction lessons in `[TICKER]_extract_learning.md`.
  - [x] Propagate audit lineage through all derived metrics calculations.
- **3.4 Testing & Verification**:
  - [x] Write unit tests for PyO3 Rust extension arithmetic schedules (ROIC, NOPAT, WACC) with test tables.
  - [x] Test Pydantic validation schemas under valid/invalid payloads.
  - [x] Verify chunk retrieval and audit lineage tagging metadata outputs.

---

## Phase 4: Longitudinal Synthesis & Historical Trends

**Goal**: Synthesize multi-period metrics and trends into single markdown reports.

- **4.1 Qualitative Trend Synthesis**:
  - [x] Compile analyst views (moat, margins, growth changes over time) into `5_historical_analysis/analyst_views.md`.
  - [x] **Analyst Report Agent**: Refactor qualitative analysis into a multi-turn, interactive reasoning agent that synthesizes analyst views, assesses qualitative trends, and verifies source citations.
  - [x] Track press trends and conference call transcripts in `news_trend.md` and `transcript_trend.md`.
- **4.2 Quantitative Trend Synthesis**:
  - [x] Build the longitudinal financials processor to update `financials_quarter.md` and `financials_annual.md`.
  - [x] Implement Q4 deduction logic (Annual minus Q1-Q3).
  - [x] Trigger the Curator Agent to update qualitative perspectives in `[TICKER]_wiki.md` and analysis lessons in `[TICKER]_analyze_learning.md`.

- **4.3 Testing & Evaluation (Evals)**:
  - [x] Test historical trend compiling and fourth-quarter arithmetic deductions.
  - [x] **Baseline Evaluation Setup**: Establish the initial Golden Dataset for benchmark tickers (e.g. AAPL 2024 JSON) containing ground truth numbers and classifications. Implement basic validation assertions.

---

## Phase 5: Assumptions & Valuation Modeling

**Goal**: Establish DCF assumptions and perform valuation modeling.

- **5.1 Default Assumptions Calculator**:
  - [x] Develop deterministic estimators for base WACC, capital turnover, and growth rates.
- **5.2 Modeler Agent (`fa run model`)**:
  - [x] Leverage historical financials and analyst views to estimate final assumptions.
  - [x] Display the interactive assumptions table to the user for feedback.
  - [x] Save adjustments to `[TICKER]_model_learning.md`.
- **5.3 Financial Model Generation**:
  - [x] Generate the DCF model markdown inside `6_financial_model/`.
  - [x] Output the baseline model JSON (`YYYYMMDD_ticker_0.json`) inside `7_historical_model_json/`.
  - [x] Trigger the Curator Agent to update modeling lessons in `[TICKER]_model_learning.md` and clear feedback.

- **5.4 Testing & Evaluation (Evals)**:
  - [x] Test default assumptions calculations and model state export functions.
  - [x] **Model LLM Evals Pipeline**: Implement programmatic quantitative scorecards (pass/fail thresholds) and qualitative semantic scoring (1-5 scale) using an LLM-as-a-Judge mechanism to evaluate the accuracy of final models.

---

## Phase 6: HTML Viewer & CLI Queries

**Goal**: Construct local user query utilities and the interactive DCF HTML application.

- **6.1 CLI Query & Trace Engine (`fa query`)**:
  - [x] Implement `fa query summary <ticker>`, `fa query assessment <ticker>`, and `fa query valuation <ticker>`.
  - [x] Implement `fa query trace <ticker> <metric> <period>` to render the audit trial/provenance of any metric from raw chunks.
- **6.2 Interactive REPL / Analyst Chat (`fa chat`)**:
  - [x] Implement the interactive console-based session with Sir Pennyworth.
  - [x] Implement the sandboxed math execution engine (`math_solver.py`) using `RestrictedPython` or `SymPy` with AST filtering and timeout guards.
- **6.3 DCF Viewer Server (`fa viewer`)**:
  - [x] Build the zero-dependency interactive HTML browser viewer.
  - [x] Setup a simple Python server to launch the viewer, read from `7_historical_model_json/`, and write back updated override JSON versions (e.g. `YYYYMMDD_ticker_1.json`).
- **6.4 Testing & Regression Evaluation**:
  - [x] Test the viewer server routing, reading JSON files, and writing overrides.
  - [x] Test interactive REPL prompts, mock user inputs, math solver AST filtering, and timeout watchdogs.
  - [x] Run the full end-to-end regression evaluation suite across multiple companies (e.g. AAPL, MSFT) and generate comparative accuracy reports.

- **6.5 CLI Usability & Enhancements**:
  - [x] Re-order CLI commands registry to prioritize active workflows (`use`, `run`, `chat`, `query`, `viewer`, `config`).
  - [x] Enable `fa run edgar` to default to the active ticker workspace, showing an error if none is selected.
  - [x] Enable command-specific welcoming messages using the static version of the pig art.
  - [x] Enhance `fa run ingest` to show the count of raw files and prompt the user for the number of files to process (defaulting to all).
  - [x] Standardize configuration text/vision LLM models to `google/gemma-4-31b-it:free`.
  - [x] In `fa run ingest`, add logs to show which files are ingested and which ones are not (skipped as duplicates or due to limit).
  - [x] In `fa run extract`, show the count of parsed files and prompt the user for the number of files to process (defaulting to all).
  - [x] In `fa run analyze`, show the count of extracted files and process all files by default without prompting (supporting an optional `--limit` flag).
  - [x] In `fa run extract`, add logs to show the verbose chain of thought/pondering text from the LLM while suppressing verbose structured JSON payloads, keeping the CLI output clean and streaming.
  - [x] **Add API provider selection and multi-provider keys**: Added ability to select API provider in config, store provider-specific keys, and dynamically route client requests to Gemini or OpenRouter.
  - [x] **Mistaken command validation check in `fa use`**: Added validation check that warns the user and prompts for confirmation if they mistake a command/subcommand name for a ticker.

Next steps:

- Need to double check how to handle earnings announcement vs 10Q. In particular, the organic growth and EBITA margins are important
