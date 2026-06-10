# Command Line Interface (CLI) Specification

This document details the command-line interface structure, arguments, options, and user experience for the Financial Analyst CLI (`fa`).

The CLI is built using [Typer](https://typer.tiangolo.com/) to provide robust auto-completion, typed parameters, and clear help documentation.

---

## 1. The AI Character: Sir Pennyworth

The CLI is hosted by **Sir Pennyworth**, a greedy financial analyst pig with dollar-sign eyes. Sir Pennyworth guides the user through configuration, execution, and queries, searching for value and return on invested capital with a sophisticated, polite, and humorous persona.

### Visual Representation (ASCII Art)
Sir Pennyworth appears at CLI startup and during key pipeline transition points:

```text
    ◢◣       ◢◣   <-- Ears
   ┌┴┴───────┴┴┐
   │  $     $  │   <-- Dollar-sign eyes (greedy for returns)
   │    (oo)   │   <-- Snout
   │   ╘═══╛   │
   └───────────┘
```

### Personality Guidelines
- **Sophisticated & Polite**: Uses phrases like "indubitably," "splendid choice, my dear fellow," "my good sir/madam," and "truffle-hunting for value."
- **Pig/Wealth Puns**: Subtle references to "piggy banks," "bringing home the bacon," and "saving every penny."
- **Rigorous & Exact**: Sir Pennyworth values precise metrics above all else. He detests errors in operating classification.

---

## 2. Configuration & Initialization

### 2.1 First-Time Configuration Flow
If no settings are found on startup, or if the user runs `fa config init`, Sir Pennyworth triggers the configuration sequence:

```text
"Greetings! I am Sir Pennyworth, your financial concierge. Before we begin our financial trufflings, we must establish our settings."
```

The CLI prompts for:
1. **User Identity**:
   - **Full Name** (e.g., Jane Doe)
   - **Email Address** (e.g., jane.doe@example.com)
   - **Project Name** (e.g., Value_Investing_2026)
   > [!WARNING]
   > The SEC EDGAR API requires a declaring User-Agent containing your name/email. Providing invalid credentials can cause connection blocks.
2. **API Credentials**:
   - Primary LLM API Key (supports OpenRouter, OpenAI, Anthropic, Gemini, Fireworks AI, etc.).
3. **Model Selection**:
   - Text-to-Text Model ID (e.g., `google/gemma-4-31b-it:free`).
   - Vision-to-Text Model ID (for PDF charts and tables).
   - *Alternative*: Option to select a unified multimodal model (e.g., **Gemma**) natively handling both tasks.
4. **Workspace Path**:
   - Active directory folder path.
   - When set, the system automatically initializes the 8 subfolders (`1_ingest_data/` through `8_historical_model_json/`) and generates boilerplate instructions in each.

---

## 3. Command Hierarchy

```bash
fa [COMMAND] [ARGS] [OPTIONS]
```

### 3.1 `fa run` Subcommands (Pipeline Orchestration)

#### `fa run edgar`
Downloads financial filings for a specific company from the SEC EDGAR system.
- **Arguments**:
  - `ticker` (Required, e.g. `AAPL`)
- **Options**:
  - `--years`, `-y`: Number of years to go back (Default: `5`. Hard limit: `5` years).
- **Execution**: Downloads all raw `10-K`, `10-Q`, and `20-F` filings for the company to `1_ingest_data/`.

#### `fa run ingest`
Ingests, hashes, parses, and structures raw filings from `1_ingest_data/`.
- **Options**:
  - `--ticker`, `-t`: Limit ingestion to this ticker.
- **Execution**:
  - Validates file hashes against `parsed_data.csv` to prevent duplicates.
  - Converts PDFs/HTML to alignment-preserved markdown.
  - Moves raw files to `3_archived_data/` and saves markdown to `2_parsed_data/`.
  - Chunks into 5,000-character blocks, prepending chunk index table as `chunk_id=0`.
  - Prompts LLM to identify the filing date and document type, renaming files to `YYYYMMDD_document_type.md`.
  - Updates `6_company_context/ingest_context.md`.

#### `fa run extract`
Extracts financial statement data and qualitative metrics.
- **Options**:
  - `--ticker`, `-t`: Limit extraction to this ticker.
- **Execution**:
  - Scans `2_parsed_data/` and targets unextracted files.
  - Commands LLM to read chunks one-by-one based on the `chunk_id=0` index.
  - Appends chunk-by-chunk notes to `YYYYMMDD_filetype_extracted.md`.
  - Extracts balance sheets, income statements, revenues, share counts.
  - Performs LLM-driven operating vs non-operating classification and calculates NOPAT, ROIC, and EBITA.
  - Updates `6_company_context/extract_context.md`.

#### `fa run historical`
Synthesizes longitudinal quarterly and annual data trends.
- **Options**:
  - `--ticker`, `-t`: Limit trend synthesis to this ticker.
- **Execution**:
  - Updates `5_historical_analysis/analyst_views.md`, `news_trend.md`, `transcript_trend.md`, `financials_quarter.md`, and `financials_annual.md`.
  - Deduces missing Q4 data from annual figures if possible.

#### `fa run model`
Proposes valuation assumptions and generates DCF projections.
- **Options**:
  - `--ticker`, `-t`: Limit modeling to this ticker.
- **Execution**:
  - Proposes defaults (`base_WACC`, `base_growth_rate`, etc.).
  - Renders assumption table for user approval/feedback.
  - Writes markdown projection report to `7_financial_model/` and JSON representation to `8_historical_model_json/` as `YYYYMMDD_ticker_0.json`.

---

#### `fa chat`
Opens an interactive analyst shell/REPL with Sir Pennyworth for ad-hoc queries, direct statement auditing, and manual model updates.
- **Arguments**:
  - `ticker` (Required, e.g. `AAPL`)
- **Execution**:
  - Starts an interactive terminal chat session with Sir Pennyworth.
  - The agent has access to a sandboxed Python execution tool to perform custom mathematical computations.
  - The agent can browse parsed chunks, query tables, run calculations, and dynamically update assumptions.

---

### 3.2 `fa query` Subcommand Group
Reads and prints parsed historical data and projections.

- **`fa query summary <ticker>`**
  - Displays company profile and historical metric tables (Revenue, EBITA, NOPAT, ROIC) from `5_historical_analysis/`.
- **`fa query assessment <ticker>`**
  - Renders qualitative assessments (moat, margin, growth trajectories) with confidence values.
- **`fa query valuation <ticker>`**
  - Shows cost of capital metrics (WACC inputs), projected 10-year cash flows, and calculated intrinsic value.
- **`fa query trace <ticker> <metric> <period>`**
  - Retrieves the full audit trail for the specified metric (e.g. `Revenue` or `EBITA`) and period (e.g. `2025` or `2025-Q2`).
  - Displays the source filename, chunk ID, and the exact matching text snippet with high relevance metrics.

---

### 3.3 `fa viewer` Command
Launches the zero-dependency interactive local web viewer.

- **Options**:
  - `--port`, `-p`: Port to run the server on (Default: `3000`).
  - `--host`, `-h`: Host to bind the server to (Default: `127.0.0.1`).
- **Execution**:
  - Scans and loads JSON files from `8_historical_model_json/`.
  - Renders an interactive browser UI where users can adjust DCF levers and write updated models back to the workspace.

---

### 3.4 `fa config` Subcommand Group
Views or mutates settings.

- **`fa config init`**
  - Interactively initializes credentials, directories, and LLM providers.
- **`fa config show`**
  - Displays current config with sensitive API keys masked (e.g. `sk-...abcd`).

---

### 3.5 `fa use` Command
Dynamically switch the current active workspace to the folder for the specified company ticker.
- **Arguments**:
  - `ticker` (Required, e.g. `AAPL`)
- **Execution**:
  - Updates the active workspace path in configuration to point to the directory named after the company's ticker.
  - Automatically initializes the 8 folders (`1_ingest_data/` to `8_historical_model_json/`) in that directory if they do not exist.
  - Loads the corresponding self-healing company contexts.

---

## 4. Console UX & Themes

- **Colors**:
  - **Rose/Pink** (`#FFB6C1`): Sir Pennyworth's ASCII art and dialogue headers.
  - **Green**: Values showing capital creation (e.g. ROIC > WACC), positive growth, and successful commands.
  - **Red**: Negative indicators (e.g. ROIC < WACC, value destruction), and command errors.
  - **Yellow/Gold**: User inputs, confirmations, and warnings.
- **Spinners**: Displayed during long-running queue processes (e.g. "Ingesting filings...").
- **Tables**: Use the `rich` library to render clean borders, headers, and formatted currency/percentages.
- **Charts & Sparklines**: Use Unicode sparklines or simple horizontal bar charts directly in the terminal to visualize trends like Revenue growth and ROIC vs WACC comparison.
