# System Architecture

This document describes the high-level architecture, directory layout, and data flow of the Financial Analyst CLI (`fa`).

---

## 1. High-Level Architecture

The system is designed as a modular Python CLI that delegates heavy financial computations to a high-performance Rust core engine. It utilizes LLM services for unstructured parsing, information extraction, and qualitative assessments.

```mermaid
graph TD
    CLI[CLI Entrypoint: Typer] --> Runner[Pipeline Runner / Queue Manager]
    CLI --> Chat[Interactive REPL / Chat]
    Runner --> Ingest[Ingestion Engine]
    Runner --> Extract[Extraction Engine]
    Runner --> Historical[Historical Analyzer]
    Runner --> Model[Valuation Modeler]

    Ingest --> PDFParser[PDF/HTML Parsers]
    Extract --> Classifier[Operating Line-Item Classifier]
    Extract --> LLM[LLM API Services]
    Model --> RustCore[Rust Core Engine: PyO3 Bindings]

    Chat --> LLM
    Chat --> MathSolver[Sandboxed Math Solver]

    ViewerServer[Simple Frontend Server] --> HTMLViewer[HTML DCF Viewer]
```

---

## 2. Directory Structure

The repository is structured as a hybrid Python-Rust application using `maturin` to build PyO3-based Rust extensions.

```
financial-analyst-cli/
├── docs/                           # Project documentation
│   ├── architecture.md
│   ├── cli_spec.md
│   ├── requirements.md
│   └── roadmap.md
├── src/                            # Application source code
│   ├── __init__.py
│   ├── cli/                        # Typer CLI commands definition
│   │   ├── __init__.py
│   │   ├── commands/               # Sub-commands (run, query, config, viewer, chat)
│   │   └── main.py
│   ├── core/                       # Shared models, settings, and constants
│   │   ├── __init__.py
│   │   ├── config.py               # Credentials & active workspace configurations
│   │   ├── exceptions.py           # Custom exception classes
│   │   └── models.py               # Pydantic schemas for verification
│   ├── services/                   # External API clients
│   │   ├── __init__.py
│   │   ├── edgar_client.py         # SEC EDGAR download API client
│   │   ├── llm_client.py           # Unified client for text & vision LLMs
│   │   ├── web_search.py           # Fallback search for accounting classifications
│   │   └── math_solver.py          # Sandboxed Python execution for custom calculations
│   ├── pipeline/                   # Sequential pipeline orchestration
│   │   ├── __init__.py
│   │   ├── queue.py                # Safe job queue & retry manager
│   │   ├── ingester.py             # File ingestion, hashing & chunking
│   │   ├── extractor.py            # LLM data extraction & financial formatting
│   │   ├── analyzer.py             # Historical synthesis & trend tracking
│   │   └── modeler.py              # Assumption processing & model generation
│   ├── rust_core/                  # Rust performance critical calculation engine
│   │   └── lib.rs                  # PyO3 bindings for financial math (WACC, DCF, ROIC)
│   ├── viewer/                     # HTML viewer code
│   │   └── index.html              # Zero-dependency interactive web viewer
│   ├── resources/                  # Static assets and reference documentation
│   │   └── dictionary/             # Central accounting classification guidelines
│   │       ├── index.md            # Registry index of all tracked financial line items
│   │       ├── revenue.md          # Revenue definitions and treatment
│   │       ├── operating_income.md # Operating income treatment
│   │       └── ...                 # Other individual line item markdowns
│   └── utils/                      # Formatting and filesystem utilities
│       ├── __init__.py
│       ├── formatting.py           # Rich-based console output utilities
│       └── filesystem.py           # Custom CSV and markdown mutation helpers
├── Cargo.toml                      # Cargo manifest for Rust module
├── pyproject.toml                  # uv / maturin configuration
└── main.py                         # Root entry point delegating to src/cli/main.py
```

---

## 3. Data Pipeline Flow

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI as Typer CLI
    participant Queue as Queue Manager
    participant Ingest as Ingester
    participant Extract as Extractor
    participant Hist as Historical Analyzer
    participant Model as Modeler
    participant Rust as Rust Core

    User->>CLI: fa run edgar
    CLI->>User: Downloads SEC PDF/HTML files to 1_ingest_data

    User->>CLI: fa run ingest
    CLI->>Queue: Feed files
    Queue->>Ingest: Process sequentially
    Ingest->>Ingest: Check duplicates (hash check)
    Ingest->>Ingest: Convert formatting-preserved Markdown
    Ingest->>Ingest: Save to 2_parsed_data, raw to 3_archived_data
    Ingest->>Ingest: Chunk (5000 chars) & prepend table
    Ingest->>User: LLM identifies date/type, renames files & updates CSV

    User->>CLI: fa run extract
    CLI->>Queue: Feed parsed files
    Queue->>Extract: Process sequentially
    Extract->>Extract: Read chunk_id=0, fetch chunks one-by-one
    Extract->>Extract: Extract qualitative statements / balance sheets
    Extract->>Extract: Classify operating vs non-operating
    Extract->>Extract: Compute ROIC, EBITA, NOPAT
    Extract->>User: Save outputs to 4_extracted_data & context to 6_company_context

    User->>CLI: fa run historical
    CLI->>Queue: Feed extracted data
    Queue->>Hist: Synthesize trends
    Hist->>Hist: Build analyst views, news trends, financials_annual/quarter
    Hist->>User: Save to 5_historical_analysis

    User->>CLI: fa run model
    CLI->>Model: Calculate default assumptions
    Model->>Rust: Compute DCF base indicators
    Model->>User: Present assumptions table for feedback
    Model->>User: Output 7_financial_model markdown & 8_historical_model_json
```

---

## 4. Key Architectural Decisions

1. **Deterministic Job Queue**:
   To avoid race conditions and resource leaks during file processing and LLM calls, all pipeline commands (`ingest`, `extract`, `historical`) feed into a centralized queue runner. Jobs are completed sequentially with exponential back-off retries.
2. **Hybrid Python-Rust Framework**:
   All core arithmetic (discounting cash flows, compounding, WACC calculation, ROIC schedules) is written in Rust (`src/rust_core/lib.rs`) for performance, safety, and correctness, compiled as a Python C-extension. Python handles orchestration, file operations, LLM prompts, and CLI interactions.
   Pydantic schemas validate all payloads crossed between Python and Rust to maintain strict structural contracts.
3. **Chunked LLM Processing**:
   To avoid context bloat and high API costs, files are split into 5,000-character chunks. The LLM only receives `chunk_id=0` (the character inventory index) and pulls subsequent chunks one-by-one as needed.
4. **Self-Healing Company Context**:
   The `6_company_context/` directory contains company-specific guidelines (`ingest_context.md`, `extract_context.md`, `model_context.md`) compiled automatically by the LLM during runs. These files capture fiscal mappings, statement layout preferences, and custom account classifications to ensure future runs align with the specific company.
5. **Interactive Zero-Dependency HTML Viewer**:
   The viewer command (`fa viewer`) launches a local server hosting a self-contained HTML page. This app reads JSON data from `8_historical_model_json/`, runs DCF projections client-side, lets the user play with assumptions dynamically, and saves updated projections directly back to the workspace.
6. **Auditable Traceability**:
   All metrics in the data lake (down to individual cells) must contain strict metadata properties tracking their provenance (`source_file`, `chunk_id`, `exact_snippet`). This ensures all calculated valuations can be verified in a single query, preventing model hallucination.
7. **Interactive Shell with Sandboxed Execution**:
   To move beyond static pipelines, `fa chat` implements a stateful conversational loop. It exposes a math solver tool (`math_solver.py`) that executes mathematical Python code in a safe sandbox to perform ad-hoc quantitative operations over extracted data.
