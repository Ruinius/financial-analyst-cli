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

## A Personal Growth Journey

This project is a milestone in my personal developer and AI alignment journey:

- **January 2026 — [Tiger-Cafe](https://github.com/Ruinius/tiger-cafe)**: I started by building a modern web application, diving deep into React, FastAPI, and full-stack development.
- **March 2026 — [Financial Analyst Skills](https://github.com/Ruinius/financial-analyst-skills)**: I transitioned into AI agent design, mapping out high-quality financial analysis concepts and domain-specific skills.
- **June 2026 — Financial Analyst CLI**: Now, I'm building this robust CLI workspace (`fa`) to merge structured agentic pipelines, local developer environments, and high-performance Rust calculations.

I am constantly learning and growing. I am incredibly grateful for any comments, feedback, or outreach—please feel free to open issues, start discussions, or connect!

---

## Table of Contents

- [A Personal Growth Journey](#a-personal-growth-journey)
- [Core Features](#core-features)
- [Installation & Setup](#installation--setup)
- [First-Time Configuration](#first-time-configuration)
- [Workspace Directory Structure](#workspace-directory-structure)
- [Command Line Interface (CLI) Reference](#command-line-interface-cli-reference)
  - [fa run](#1-fa-run-pipeline-orchestration)
  - [fa chat](#2-fa-chat-interactive-analyst-shell)
  - [fa query](#3-fa-query-data-display)
  - [fa use](#4-fa-use-workspace-switching)
  - [fa viewer](#5-fa-viewer-interactive-dcf-viewer)
  - [fa config](#6-fa-config-settings-management)
- [Architecture](#architecture)
- [License](#license)

---

## Core Features

1. **Structured Ingestion & Parsing**: Automated retrieval of filings (10-K, 10-Q, 20-F) from SEC EDGAR, layout-preserved markdown parsing, duplicate hashing, and smart LLM-driven date/quarter identification.
2. **Auditable Metric Extraction**: Extract Balance Sheet and Income Statement line items. Every data point is tagged with trace metadata (`source_file`, `chunk_id`, `exact_snippet`) for absolute auditing.
3. **Hybrid Rust-Python Engine**: Perform performance-critical calculations (Invested Capital, NOPAT, EBITA, WACC, and ROIC schedules) in Rust via PyO3 bindings with strict Pydantic payload verification.
4. **Self-Healing Company Context**: Company-specific extraction and mapping contexts that automatically heal and improve on successive pipeline runs.
5. **Interactive REPL / Analyst Shell (`fa chat`)**: Talk directly to Sir Pennyworth. Probe extracted financial metrics, execute custom math formulas in a sandboxed execution environment, and audit statements.
6. **Zero-Dependency DCF Viewer**: Start a local viewer server to dynamically tune DCF assumptions and save custom scenarios back to the workspace.

---

## Installation & Setup

This project uses a hybrid architecture consisting of a Python CLI and a compiled Rust computation core.

### Prerequisites

1. **Python**: Python >= 3.12 (recommend managing via `uv`).
2. **uv**: This project uses `uv` for package management. Install it via `pip install uv` or follow instructions on [astral.sh/uv](https://astral.sh/uv).
3. **Rust Toolchain**: To compile the Rust core modules, you must have Rust and `cargo` installed (via [rustup.rs](https://rustup.rs/)).

### Environment Initialization

Clone this repository and run the following in your shell:

```powershell
# Create a virtual environment and sync dependencies
uv venv
.venv\Scripts\activate
uv sync

# Setup pre-commit linting and checks
uv run pre-commit install

# Run the project entry point
uv run python main.py
```

#### Optional: High-Performance Rust Engine
The CLI ships with a pure Python fallback. However, for maximum calculation performance, you can optionally build the Rust extension module:

```powershell
# Ensure you have Rust installed via rustup.rs
uv pip install maturin
uv run maturin develop
```

---

## First-Time Configuration

When you execute `fa` for the first time, Sir Pennyworth guides you through an interactive configuration setup:

1. **User Identity**: Full name, email, and project name (crucial for declaring SEC EDGAR user-agent headers).
2. **LLM API Credentials**: Setup OpenRouter, Gemini, OpenAI, or other keys.
3. **Model Selection**: Select your preferred text and vision LLMs.
4. **Workspace Path**: Specify a directory where company analyses will be run.

---

## Workspace Directory Structure

Setting up a workspace for a company ticker (e.g., `AAPL` or `MSFT`) initializes the following directory structure:

- **`1_ingest_data/`**: Raw documents (10-Ks, 10-Qs, earnings transcripts, analyst reports, press releases, etc.) and `edgar_downloads.csv`.
- **`2_parsed_data/`**: Markdown conversions of raw files (`YYYYMMDD_filetype.md`) and a `parsed_data.csv` index.
- **`3_archived_data/`**: Archived original files.
- **`4_extracted_data/`**: Parsed metrics, statement summaries, and audit trail metadata.
- **`5_historical_analysis/`**: Generated reports summarizing qualitative moats (`analyst_views.md`), transcripts (`transcript_trend.md`), and quantitative trends (`financials_quarter.md`, `financials_annual.md`).
- **`6_company_context/`**: Customizable self-healing accounting contexts (`ingest_context.md`, `extract_context.md`, `model_context.md`).
- **`7_financial_model/`**: Markdown representations of DCF models.
- **`8_historical_model_json/`**: JSON model states for import/export in the interactive viewer.

---

## Command Line Interface (CLI) Reference

### 1. `fa run` (Pipeline Orchestration)

Execute sequentially structured pipeline steps:

```powershell
# Fetch filings from SEC EDGAR
uv run fa run edgar AAPL --years 5

# Parse and chunk ingested raw files
uv run fa run ingest

# Extract financial statements and audit details
uv run fa run extract

# Synthesize multi-period metrics and qualitative trends
uv run fa run historical

# Generate DCF model projections
uv run fa run model
```

### 2. `fa chat` (Interactive Analyst Shell)

Start an interactive shell with Sir Pennyworth to ask questions, run calculations with a sandboxed Python solver, and examine financial metrics:

```powershell
uv run fa chat AAPL
```

### 3. `fa query` (Data Display)

Query analysis tables, qualitative assessments, and trace audit trails:

```powershell
# Show summary profile and historical financial statement metrics (with console sparklines)
uv run fa query summary AAPL

# Show qualitative assessments
uv run fa query assessment AAPL

# Show WACC inputs, projected cash flows, and intrinsic values
uv run fa query valuation AAPL

# Trace the exact raw file provenance/source text of a metric
uv run fa query trace AAPL Revenue 2025
```

### 4. `fa use` (Workspace Switching)

Switch the active workspace directory dynamically:

```powershell
uv run fa use AAPL
```

### 5. `fa viewer` (Interactive DCF Viewer)

Start the local web server to launch the zero-dependency interactive HTML model viewer:

```powershell
uv run fa viewer --port 3000 --host 127.0.0.1
```

### 6. `fa config` (Settings Management)

Initialize or display active configuration properties:

```powershell
# Interactively update your configurations and initialize directories
uv run fa config init

# Display current configuration profile
uv run fa config show
```

---

## Repository Structure & Architecture

The codebase is organized as a hybrid Python-Rust application:

* **`src/`**: Contains the active application source code, including sub-commands (`cli/`), execution pipeline steps (`pipeline/`), external API clients and sandboxed execution tools (`services/`), PyO3 Rust bindings (`rust_core/`), accounting classification dictionaries (`resources/`), and console/file utilities (`utils/`).
* **`scripts/`**: Contains legacy reference scripts from the old `financial-analyst-skills` repository. **Note:** Do not run these as-is; they serve strictly as inspiration/reference.
* **`tmp/`**: Dedicated local directory for temporary developer logs, scratchpads, and execution scripts.
* **`docs/`**: Full project specification, requirements, and design documents.

For deeper details on modular clients, Pydantic validation structures, the central dictionary, and core design decisions, refer to the [System Architecture Document](docs/architecture.md) and the agent guidelines in [AGENTS.md](AGENTS.md).

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
