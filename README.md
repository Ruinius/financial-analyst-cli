# Financial Analyst CLI (fa)

> [!NOTE]
> This is a personal project designed for automating high-quality financial analysis, qualitative assessments, and valuation modeling, powered by LLMs. It acts as a CLI orchestrator inspired by and built around the concepts in [financial-analyst-skills](https://github.com/Ruinius/financial-analyst-skills).

The interface is hosted by **Sir Pennyworth**, a greedy financial analyst pig with dollar-sign eyes who guides you through configuration, analyses, and hunting for maximum returns.

```text
    ◢◣       ◢◣   <-- Ears
   ┌┴┴───────┴┴┐
   │  $     $  │   <-- Dollar sign eyes (greedy)
   │    (oo)   │   <-- Snout
   │   ╘═══╛   │
   └───────────┘
```

---

## Table of Contents

- [Core Features](#core-features)
- [Installation & Setup](#installation--setup)
- [First-Time Configuration](#first-time-configuration)
- [Workspace Directory Structure](#workspace-directory-structure)
- [Command Line Interface (CLI) Reference](#command-line-interface-cli-reference)
  - [fa run](#1-fa-run-pipeline-orchestration)
  - [fa query](#2-fa-query-data-display)
  - [fa viewer](#3-fa-viewer-interactive-dcf-viewer)
  - [fa config](#4-fa-config-settings-management)
- [Architecture](#architecture)
- [Related Projects](#related-projects)
- [License](#license)

---

## Core Features

1. **Ticker Insights & Overview**: Fetch company profile details (sector, industry, description) and summarize recent news and market sentiment.
2. **Financial Statements Analysis**: Retrieve multi-year Income Statements, Balance Sheets, and Cash Flow Statements. Automatically compute margins, leverage ratios, and ROIC.
3. **Valuation Models**:
   - **Discounted Cash Flow (DCF)**: Calculate intrinsic value using custom revenue growth projections, terminal growth rates, and Weighted Average Cost of Capital (WACC).
   - **Comparable Analysis (Comps)**: Price-to-Earnings (P/E), Price-to-Sales (P/S), and EV/EBITDA comparisons against direct competitors.
4. **Technical & Market Data**: Generate moving averages (SMA/EMA) and core technical indicators (RSI, MACD) to summarize current market trends.
5. **Interactive DCF Viewer**: Launch a zero-dependency HTML dashboard to load and tune financial model assumptions, saving custom iterations directly back to your workspace.
6. **Report Generation**: Export structured markdown reports and print terminal-optimized tables via `rich`.

---

## Installation & Setup

This project is built using a modern hybrid architecture consisting of a Python CLI and a Rust performance/calculation core.

### Prerequisites

1. **Python**: Ensure you have Python >= 3.14 installed.
2. **uv**: This project uses `uv` for Python package and environment management. If you do not have it, follow the [uv installation instructions](https://github.com/astral-sh/uv#installation).
3. **Rust Toolchain**: To compile the Rust core modules, you must have Rust and `cargo` installed. You can install them via [rustup](https://rustup.rs/).

### Environment Initialization

Clone this repository and run the following in your shell:

```powershell
# Create a virtual environment and sync dependencies
uv venv

# Build the Rust extension module using Maturin
uv pip install maturin
uv run maturin develop

# Setup pre-commit linting and secret checks
uv run pre-commit install

# Run the project entry point
uv run python main.py
```


---

## First-Time Configuration

When you execute `fa` for the first time, Sir Pennyworth will guide you through an interactive setup process:

1. **LLM API Credentials**: Setup OpenRouter, OpenAI, or Gemini API keys.
2. **Model Selection**: Select your preferred text and vision LLM models. By default, it integrates with OpenRouter, defaulting to the Gemma model (e.g., `google/gemma-4-31b-it`).
3. **Workspace Path**: Specify a workspace directory.

> [!IMPORTANT]
> To avoid context bloat and keep analyses clean, use a separate workspace directory for each company. It is recommended to name the directory after the company's ticker symbol (e.g., `AAPL` or `MSFT`).

---

## Workspace Directory Structure

Setting up a workspace initializes the following 7 subfolders and instruction templates:

*   **`1_ingest_data/`**: Place raw documents (10-Ks, 10-Qs, earnings transcripts, analyst reports, etc.) here.
*   **`2_summarized_data/`**: Raw documents are parsed, summarized into Markdown format (`YYYYMMDD_filetype.md`), and indexed in `summarized_data_list.md`.
*   **`3_archived_data/`**: Raw files are archived here (`YYYYMMDD_filetype.pdf`) after being successfully processed.
*   **`4_historical_analysis/`**: Contains generated reports summarizing qualitative moats, margins, capital efficiency, and ROIC trends.
*   **`5_company_specific_rules/`**: Customizable accounting rules (e.g., `operating_income.md`, `invested_capital.md`) that direct how metrics are extracted and analyzed.
*   **`6_financial_model/`**: Contains the final markdown representation of the DCF and valuation models.
*   **`7_historical_model_json/`**: Stores financial model JSON objects (`YYYYMMDD_ticker_N.json`) for import into the interactive viewer.

---

## Command Line Interface (CLI) Reference

The CLI commands are structured as follows:

### 1. `fa run` (Pipeline Orchestration)

Executes the end-to-end data pipeline on documents in your workspace.

```powershell
# Run the complete pipeline
uv run fa run

# Options
# --ticker, -t           Limit processing to a specific stock ticker
# --phase, -p            Run a specific phase only:
#                          - 1 / classify : Document Classification
#                          - 2 / extract  : Financial Data Extraction
#                          - 3 / calculate: Financial Calculations
#                          - 4 / organize : Move raw files & write summaries
#                          - 5 / assess   : Qualitative Assessment
#                          - 6 / model    : Financial DCF/Comps Modeling
#                          - 7 / json     : Export model state JSON
# --skip-quality-gate    Skip the metrics verification check
# --postrun              Perform self-improvement and run curation updates
```

### 2. `fa query` (Data Display)

Interrogate and view analysis results in the console.

```powershell
# Show summary profile and historical financial statement metrics
uv run fa query summary <ticker>

# Show qualitative assessments (moats, margin trajectory, confidence)
uv run fa query assessment <ticker>

# Show WACC, DCF assumptions, cash flow projections, and intrinsic value
uv run fa query valuation <ticker>
```

### 3. `fa viewer` (Interactive DCF Viewer)

Launches the interactive local web application to adjust DCF assumptions in real-time.

```powershell
uv run fa viewer --port 3000 --host 127.0.0.1
```

### 4. `fa config` (Settings Management)

Configure settings and manage active workspace structures.

```powershell
# Interactively update your configurations and initialize directories
uv run fa config init

# Display the current configuration profiles (with sensitive keys masked)
uv run fa config show
```

---

## Architecture

For more details on modular clients, Pydantic data modeling, and codebase organization, refer to the [System Architecture Document](docs/architecture.md).

---

## Related Projects

*   [financial-analyst-skills](https://github.com/Ruinius/financial-analyst-skills): The repository containing the financial analysis concepts and skill definitions that inspire the layout and automation pipeline of this project.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
