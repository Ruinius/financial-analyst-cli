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
   - When set, the system automatically initializes the 4 folders (`1_ingest_data/`, `2_parsed_data/`, `3_archived_data/`, `9_scenario_model_json/`) in that directory if they do not exist.

## 3. Command Hierarchy

```bash
fa [COMMAND] [ARGS] [OPTIONS]
```

### 3.1 Global Options for `fa run`

All pipeline commands (`fa run extract`, `fa run analyze`, `fa run model`, `fa run curate_wiki`) support the following new options:

- `--non-interactive` / `-n`: Disables all stdin blocking prompts. Safe for headless execution. Enables automatic retries on LLM/API errors, bypasses retries on validation or quality issues, and aborts with exit code `1` on validation failures.
- `--agent <agent_name>` / `-a <agent_name>`: Bypasses the full stage pipeline and executes a single targeted sub-agent directly (e.g. `fa run extract --agent balance_sheet`), validating its prerequisite inputs on the blackboard first.

### 3.2 `fa run` Subcommands (Pipeline Orchestration)

#### `fa run edgar <ticker>`
Downloads raw financial filings for a specific company from the SEC EDGAR system.
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
  - Converts PDFs/HTML to alignment-preserved markdown with simplified headers.
  - Moves raw files to `3_archived_data/` and saves markdown to `2_parsed_data/` using deterministic naming (`raw_path.stem`).
  - No LLM operations or metadata identification calls are executed during this stage.

#### `fa run extract`
Extracts financial statement data and qualitative metrics using the Blackboard Orchestrator.
- **Options**:
  - `--ticker`, `-t`: Limit extraction to this ticker.
- **Execution**:
  - Runs once across fanned-in documents via the event loop.
  - First executes `MetadataAgent` to extract company-wide and document-level metadata, updating `workspace_state.json` and `parsed_data.csv`.
  - Sequentially and concurrently runs parallel sub-extractors (Balance Sheet, Income Statement, Diluted Shares, Organic Growth, Operating EBITA, Adjusted Taxes, Interpretation, Analyst Report, and Other Doc agents) to populate structured data schemas.
  - Passes outputs to the Rust core engine to calculate NOPAT, ROIC, and invested capital.
  - Triggers LLM-based quality validations (`check_balance_sheet_quality`, `check_income_statement_quality`) to audit extracted table formatting and positive/negative signs.
  - Atomic checkpoints are written to `workspace_state.json` inside the company workspace.

#### `fa run analyze`
Synthesizes longitudinal quarterly and annual data trends.
- **Options**:
  - `--ticker`, `-t`: Limit trend synthesis to this ticker.
- **Execution**:
  - Compiles fanned-in extracted period metrics into longitudinal trend summary tables directly inside `workspace_state.json` (under `company_data.quarterly_financials` and `company_data.yearly_financials`).

#### `fa run model`
Proposes valuation assumptions and generates DCF projections.
- **Options**:
  - `--ticker`, `-t`: Limit modeling to this ticker.
- **Execution**:
  - Spawns modeling agents (WACC, Growth, Margin, and Non-Operating agents) to formulate Cost of Capital parameters, growth projections, target margins, and non-operating categories.
  - Runs calculations using the fallback or Rust DCF modeling engine and writes assumptions and projection years directly to `workspace_state.json`.

#### `fa run curate_wiki`
Invokes the `CuratorAgent` to curating qualitative views.
- **Options**:
  - `--ticker`, `-t`: Limit curation to this ticker.
- **Execution**:
  - Invokes `CuratorAgent` to compile fanned-in data, historical trends, and model outputs into the robust qualitative views (Bull & Bear perspectives) in `[TICKER]_wiki.md` under write lock.

#### `fa chat <ticker>`
Opens an interactive analyst shell/REPL with Sir Pennyworth for ad-hoc queries, direct statement auditing, and manual model updates.
- **Arguments**:
  - `ticker` (Required, e.g. `AAPL`)
- **Execution**:
  - Starts an interactive terminal chat session with Sir Pennyworth.
  - The agent has access to a sandboxed Python execution tool (`safe_math_solver.py`) to perform custom mathematical computations over blackboard data variables.
  - The agent can browse parsed chunks, query tables, run calculations, and dynamically update assumptions.

---

### 3.3 `fa query` Subcommand Group
Reads and prints parsed historical data and projections directly from the blackboard database.

- **`fa query summary <ticker>`**
  - Displays company profile and historical metric tables (Revenue, EBITA, NOPAT, ROIC) from `workspace_state.json`.
- **`fa query assessment <ticker>`**
  - Renders qualitative assessments (moat, margin, growth trajectories) with confidence values.
- **`fa query valuation <ticker>`**
  - Shows cost of capital metrics (WACC inputs), projected 10-year cash flows, and calculated intrinsic value.
- **`fa query trace <ticker>`**
  - Displays execution timestamps, source files, and completion statuses of all agents in the pipeline.

---

### 3.4 `fa viewer` Command
Launches the zero-dependency interactive local web viewer.

- **Options**:
  - `--port`, `-p`: Port to run the server on (Default: `3000`).
  - `--host`, `-h`: Host to bind the server to (Default: `127.0.0.1`).
- **Execution**:
  - Loads and displays active data from `workspace_state.json`.
  - Renders an interactive browser UI where users can adjust DCF levers and write updated scenario models to `9_scenario_model_json/`.

---

### 3.5 `fa config` Subcommand Group
Views or mutates settings.

- **`fa config init`**
  - Interactively initializes credentials, directories, and LLM providers.
- **`fa config show`**
  - Displays current config (including provider-specific models and active text model) with sensitive API keys masked (e.g. `sk-...abcd`).
- **`fa config set [--provider PROVIDER] [--openrouter-key KEY] [--gemini-key KEY] [--deepseek-key KEY] [--gemini-model MODEL] [--openrouter-model MODEL] [--deepseek-model MODEL]`**
  - Directly updates configuration parameters such as the active API provider, API keys, or provider-specific models without running the interactive wizard.

---

### 3.6 `fa use <ticker>` Command
Dynamically switch the active workspace to the folder for the specified company ticker.
- **Arguments**:
  - `ticker` (Required, e.g. `AAPL`)
- **Execution**:
  - Updates the active workspace path in configuration to point to the directory named after the company's ticker.
  - Automatically initializes **4 folders** (`1_ingest_data/`, `2_parsed_data/`, `3_archived_data/`, `9_scenario_model_json/`) in that directory if they do not exist.
  - Loads corresponding company contexts/learnings from the root files.

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
