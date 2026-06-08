# Command Line Interface (CLI) Specification

This document details the command line interface structure, arguments, options, and overall user experience for the Financial Analyst CLI, built to orchestrate the pipeline from `financial-analyst-skills`.

The CLI is built using [Typer](https://typer.tiangolo.com/) to provide robust auto-completion, typed parameters, and clear help documentation.

---

## The AI Character: Sir Pennyworth

The CLI is hosted by **Sir Pennyworth**, a greedy financial analyst pig with dollar-sign eyes. Sir Pennyworth guides the user through configuration, execution, and query processes, constantly hunting for maximum returns and cost-cutting opportunities with a touch of humor.

### Visual Representation (ASCII Art)

Whenever the CLI is launched or performing key steps, Sir Pennyworth appears:

```text
    ◢◣       ◢◣   <-- Ears
   ┌┴┴───────┴┴┐
   │  $     $  │   <-- Dollar sign eyes (greedy)
   │    (oo)   │   <-- Snout
   │   ╘═══╛   │
   └───────────┘
```

### Personality Guidelines

- **Sophisticated & Polite**: Uses words like "indubitably," "capital, my dear fellow," "my good sir/madam," and "splendid."
- **Pig/Wealth Puns**: Occasional subtle references to "piggy banks," "truffle-hunting for value," "saving pennies," and "bacon-saving decisions."
- **Helpful & Precise**: Sir Pennyworth takes financial analysis extremely seriously, ensuring metrics are accurate and well-organized.

---

## First-Time Configuration Flow

When `fa` is executed for the very first time (or if no configuration is detected), the application automatically enters the **First-Time Configuration Flow** guided by Sir Pennyworth.

```text
"Greetings! I am Sir Pennyworth. Before we begin our financial trufflings, we must establish our settings."
```

The flow prompts the user for:

1. **LLM API Credentials**:
   - The user's API Key (e.g., OpenRouter, OpenAI, or Gemini key).

2. **Model Selection**:
   - The user must specify:
     - A **text-to-text model** (e.g., `google/gemma-2-9b-it`).
     - A **vision-to-text model** (for processing charts/scans).
   - _Alternative_: The user can choose to use the default **Gemma** model, which is natively multi-modal and handles both text and vision tasks.

3. **Workspace Path**:
   - The user must specify the location for their active workspace.
   - **CRITICAL WORKSPACE REMINDER (Always displayed)**:
     > [!IMPORTANT]
     > Each workspace should only contain one company to reduce potential context bloat. Ideally name the workspace directory after the company's ticker symbol (e.g., `AAPL` or `MSFT`), which serves as a convenient unique identifier.

4. **Workspace Directory Initialization**:
   - When a workspace is selected or initialized, Sir Pennyworth automatically checks for and creates the following structured folders along with instruction-bearing files:
     - `1_ingest_data/`: Where the user dumps PDFs of 10-Q, 10-K, analyst reports, press releases, and transcripts. If the AI agent accesses the SEC API or other external APIs, the raw data will also be downloaded directly to this directory.
     - `2_summarized_data/`: Where all raw files in `1_ingest_data/` are parsed and summarized into markdown-friendly files. They are renamed to the format `YYYYMMDD_filetype` (e.g., `20240315_10K.md`). A `summarized_data_list.md` catalog is maintained in this directory to list all processed files, their description, and status.
     - `3_archived_data/`: Where raw files are moved after processing and summarizing. They are renamed to match the corresponding summarized filename (e.g., `20240315_10K.pdf`) while retaining their original file extension.
     - `4_historical_analysis/`: Where combined historical statement analyses are saved. These markdown documents cover topics such as EBITDA margin trends, invested capital, capital efficiency, and qualitative evolution over time.
     - `5_company_specific_rules/`: Where accounting and metrics definition rules (e.g., `invested_capital.md`, `operating_income.md`) reside. During historical analysis, the AI agent makes a best-guess definition and creates these markdown files. The user can customize them, and the AI agent will strictly respect these rules in future runs.
     - `6_financial_model/`: Where the markdown representation of the generated DCF/financial model lives.
     - `7_historical_model_json/`: Where JSON outputs of the financial models are saved as `YYYYMMDD_ticker_0.json`. Users can load these using the HTML viewer and save newer iterations (e.g., `YYYYMMDD_ticker_1.json`).

---

## Command Hierarchy

```bash
fa [COMMAND] [ARGS] [OPTIONS]
```

### 1. `run` Command (Pipeline Orchestration)

Executes the skills pipeline on documents in the configured data directories.

- **`fa run`**
  - Reads unprocessed raw PDFs and documents from the `1_ingest_data/` directory.
  - Summarizes each processed document to `2_summarized_data/` in `YYYYMMDD_filetype.md` format, and appends/updates metadata in `summarized_data_list.md`.
  - Moves the original raw files to `3_archived_data/` renaming them to `YYYYMMDD_filetype.pdf` to retain original form.
  - Performs historical statement analysis (e.g. EBITDA margins, capital efficiency, etc.) and outputs to `4_historical_analysis/`.
  - Uses and initializes definition rules in `5_company_specific_rules/` (e.g., `invested_capital.md` and `operating_income.md`).
  - Generates the markdown version of the financial valuation model in `6_financial_model/`.
  - Exports the initial JSON model representation (`YYYYMMDD_ticker_0.json`) to `7_historical_model_json/`.
  - Options:
    - `--ticker`, `-t`: Limit processing to documents matching this ticker.
    - `--phase`, `-p`: Run a specific phase only:
      - `1` / `classify`: Document Classification (reads from `1_ingest_data/`)
      - `2` / `extract`: Financial Data Extraction
      - `3` / `calculate`: Financial Calculations
      - `4` / `organize`: Document Organization (moves to `3_archived_data/`, writes to `2_summarized_data/`)
      - `5` / `assess`: Qualitative Assessment (writes to `4_historical_analysis/`)
      - `6` / `model`: Financial Modeling (writes to `6_financial_model/`)
      - `7` / `json`: Model JSON Generation (writes to `7_historical_model_json/`)
    - `--skip-quality-gate`: Skip the upstream metrics quality check between calculation and organization.
    - `--postrun`: Perform postrun self-improvement and example curation after execution.

### 2. `query` Command Group

Retrieves and displays processed financial analysis data from the workspace directories.

- **`fa query summary <ticker>`**
  - Displays the company profile and the calculated historical financial metrics summary table (Revenue, EBITA, Tax Rate, Invested Capital, NOPAT, ROIC, and Organic Growth) by reading from `4_historical_analysis/`.
- **`fa query assessment <ticker>`**
  - Displays the qualitative assessments (economic moat, EBITA margin trajectory, organic growth trajectory) with their bullet rationales and confidence ratings by reading from `4_historical_analysis/`.
- **`fa query valuation <ticker>`**
  - Displays the calculated WACC details (beta, risk-free rate, equity risk premium, cost of debt/equity), DCF assumptions, 10-year projected cash flows, terminal value, and calculated intrinsic value per share by reading from `6_financial_model/`.

### 3. `viewer` Command

Serves the interactive zero-dependency DCF HTML viewer.

- **`fa viewer`**
  - Launches `tools/simple_frontend_server.py` to serve the interactive valuation viewer.
  - The viewer scans and loads JSON models from `7_historical_model_json/` (e.g., `YYYYMMDD_ticker_0.json`) and enables the user to modify assumptions and save updated versions back to the same folder as `YYYYMMDD_ticker_1.json`, etc.
  - Options:
    - `--port`: Port to listen on (default: `3000`).
    - `--host`: Host address to bind to (default: `127.0.0.1`).

### 4. `config` Command Group

Manages settings, API credentials, and active workspaces.

- **`fa config init`**
  - Interactively configures paths to the directories, API keys (Yahoo Finance, OpenRouter/OpenAI/Gemini keys), and standard LLM configurations. When a new workspace path is set, automatically initializes the 7 workspace subfolders (`1_ingest_data/` to `7_historical_model_json/`) with instructions.
- **`fa config show`**
  - Prints the current system settings, path locations, active workspace, and API configurations (with sensitive API keys masked).

---

## Terminal Formatting & UX

- **Character Prompts**: Sir Pennyworth will introduce outputs and summarize results.
- **Tables**: Use the `rich` library to render clean, readable tables for financial statements and DCF projection flows.
- **Progress Indicators**: Show active spinners and progress bars during multi-step PDF text extraction and LLM qualitative assessments.
- **Color Theme**:
  - Pink/Rose accent colors for Sir Pennyworth's dialogue/ASCII art.
  - Green for positive trends, ROIC exceeding WACC, intrinsic value above current price, and successful steps.
  - Red for negative trends, ROIC below cost of capital, intrinsic value below current price, and errors/failed checks.
  - Yellow/Gold for warnings, highlights, and values requiring user double-checks.
