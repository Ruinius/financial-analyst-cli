# AGENTS.md

Welcome to the `financial-analyst-cli` project.

## Project Structure
- [AGENTS.md](file:///f:/AIML projects/financial-analyst-cli/AGENTS.md): Architectural patterns, module boundaries, and documentation standards.
- [.gitignore](file:///f:/AIML projects/financial-analyst-cli/.gitignore): Ignored files configuration.
- [.pre-commit-config.yaml](file:///f:/AIML projects/financial-analyst-cli/.pre-commit-config.yaml): Git pre-commit hooks configuration (linters, secret prevention checks).
- [Cargo.toml](file:///f:/AIML projects/financial-analyst-cli/Cargo.toml): Cargo configuration for the Rust Core calculation engine.
- [docs/architecture.md](file:///f:/AIML projects/financial-analyst-cli/docs/architecture.md): System architecture, folder structure, and software design decisions.
- [docs/cli_spec.md](file:///f:/AIML projects/financial-analyst-cli/docs/cli_spec.md): CLI command hierarchy, options, parameters, and user experience specification.
- [docs/requirements.md](file:///f:/AIML projects/financial-analyst-cli/docs/requirements.md): Scope of capabilities and product requirements translated from financial-analyst-skills.
- [docs/roadmap.md](file:///f:/AIML projects/financial-analyst-cli/docs/roadmap.md): Six-phase development plan for implementing the Financial Analyst CLI.
- [LICENSE](file:///f:/AIML projects/financial-analyst-cli/LICENSE): MIT License.
- [main.py](file:///f:/AIML projects/financial-analyst-cli/main.py): Application entry point.
- [pyproject.toml](file:///f:/AIML projects/financial-analyst-cli/pyproject.toml): Project metadata and dependencies (managed via `uv`), including Maturin build-backend configuration.
- [README.md](file:///f:/AIML projects/financial-analyst-cli/README.md): Project overview and setup instructions.
- [scripts/](file:///f:/AIML projects/financial-analyst-cli/scripts): Temporary directory containing copied pipeline and calculation scripts from the old `financial-analyst-skills` repository. These scripts should not be used as-is and are only here to serve as reference ideas.
  - [calculate_calculations.py](file:///f:/AIML projects/financial-analyst-cli/scripts/calculate_calculations.py): Derived financial metrics calculation engine.
  - [calculate_modeling.py](file:///f:/AIML projects/financial-analyst-cli/scripts/calculate_modeling.py): Intrinsic value and WACC valuation engine.
  - [generate_json.py](file:///f:/AIML projects/financial-analyst-cli/scripts/generate_json.py): Model JSON generator.
  - [organize.py](file:///f:/AIML projects/financial-analyst-cli/scripts/organize.py): Processed document organization and unit harmonization.
  - [process_classification.py](file:///f:/AIML projects/financial-analyst-cli/scripts/process_classification.py): PDF classification script.
  - [transform_and_append.py](file:///f:/AIML projects/financial-analyst-cli/scripts/transform_and_append.py): Tiger-Transformer output append logic.
  - [markdown_parser.py](file:///f:/AIML projects/financial-analyst-cli/scripts/markdown_parser.py): Markdown table extraction helpers.
  - [market_data.py](file:///f:/AIML projects/financial-analyst-cli/scripts/market_data.py): Yahoo Finance market data and ticker checker.
  - [simple_frontend_server.py](file:///f:/AIML projects/financial-analyst-cli/scripts/simple_frontend_server.py): Local scenario server and viewer host.
- [tmp/](file:///f:/AIML projects/financial-analyst-cli/tmp): Temporary logs, scratchpads, and execution scripts.
- [src/](file:///f:/AIML projects/financial-analyst-cli/src): Application source package.
  - [src/cli/](file:///f:/AIML projects/financial-analyst-cli/src/cli): Sub-commands and main CLI definitions.
    - [src/cli/main.py](file:///f:/AIML projects/financial-analyst-cli/src/cli/main.py): Primary Typer entry point and command router.
    - [src/cli/commands/config.py](file:///f:/AIML projects/financial-analyst-cli/src/cli/commands/config.py): Commands for config initialization (`init`) and masked printing (`show`).
    - [src/cli/commands/use.py](file:///f:/AIML projects/financial-analyst-cli/src/cli/commands/use.py): Workspace switcher command that updates active ticker and initializes 8 folders.
  - [src/core/](file:///f:/AIML projects/financial-analyst-cli/src/core): Settings, custom exception classes, and Pydantic schemas.
    - [src/core/config.py](file:///f:/AIML projects/financial-analyst-cli/src/core/config.py): Settings model definition, loading/saving utilities, and API key masking.
    - [src/core/exceptions.py](file:///f:/AIML projects/financial-analyst-cli/src/core/exceptions.py): Custom exception classes (e.g. ConfigError, WorkspaceError).
  - [src/pipeline/](file:///f:/AIML projects/financial-analyst-cli/src/pipeline): Execution runner stages (ingest, extract, historical, model).
    - [src/pipeline/queue.py](file:///f:/AIML projects/financial-analyst-cli/src/pipeline/queue.py): Safe job queue and exponential back-off retry manager.
    - [src/pipeline/ingester.py](file:///f:/AIML projects/financial-analyst-cli/src/pipeline/ingester.py): File parsing, deduplication, chunking, and LLM metadata identification.
    - [src/pipeline/analyzer.py](file:///f:/AIML projects/financial-analyst-cli/src/pipeline/analyzer.py): Longitudinal trend synthesis, analyst view compiling, and Q4 deduction engine.
  - [src/services/](file:///f:/AIML projects/financial-analyst-cli/src/services): SEC client, LLM wrapper, web search, and AST-sandboxed math solver.
    - [src/services/edgar_client.py](file:///f:/AIML projects/financial-analyst-cli/src/services/edgar_client.py): SEC EDGAR download API client.
    - [src/services/llm_client.py](file:///f:/AIML projects/financial-analyst-cli/src/services/llm_client.py): Unified client for text & vision LLMs.
  - [src/rust_core/lib.rs](file:///f:/AIML projects/financial-analyst-cli/src/rust_core/lib.rs): Rust module with PyO3 bindings for financial and mathematical calculations.
  - [src/rust_core/fallback.py](file:///f:/AIML projects/financial-analyst-cli/src/rust_core/fallback.py): Pure Python fallback for calculations when Rust library is not compiled.
  - [src/rust_core/__init__.py](file:///f:/AIML projects/financial-analyst-cli/src/rust_core/__init__.py): Hybrid import loader for calculation engine.
  - [src/viewer/index.html](file:///f:/AIML projects/financial-analyst-cli/src/viewer/index.html): Interactive zero-dependency web viewer template.
  - [src/resources/dictionary/](file:///f:/AIML projects/financial-analyst-cli/src/resources/dictionary): Central accounting glossary and classification dictionary containing definition markdowns and valuation treatment guidelines.
    - [index.md](file:///f:/AIML projects/financial-analyst-cli/src/resources/dictionary/index.md): Index registry of all tracked accounting items.
    - [revenue.md](file:///f:/AIML projects/financial-analyst-cli/src/resources/dictionary/revenue.md): Revenue definitions and treatment.
    - [operating_income.md](file:///f:/AIML projects/financial-analyst-cli/src/resources/dictionary/operating_income.md): Operating income definitions and treatment.
    - [cash.md](file:///f:/AIML projects/financial-analyst-cli/src/resources/dictionary/cash.md): Cash and equivalents definitions and treatment.
  - [src/utils/](file:///f:/AIML projects/financial-analyst-cli/src/utils): CLI output formatting and filesystem helpers.
    - [src/utils/formatting.py](file:///f:/AIML projects/financial-analyst-cli/src/utils/formatting.py): Rich terminal formatting helpers and Sir Pennyworth speech bubbles.
- [tests/](file:///f:/AIML projects/financial-analyst-cli/tests): Test suite folder.
  - [tests/test_config.py](file:///f:/AIML projects/financial-analyst-cli/tests/test_config.py): Unit and integration tests for CLI commands, key masking, settings logic, and folder initialization.
  - [tests/test_edgar.py](file:///f:/AIML projects/financial-analyst-cli/tests/test_edgar.py): Unit tests for the SEC EDGAR client and submissions retrieval.
  - [tests/test_ingester.py](file:///f:/AIML projects/financial-analyst-cli/tests/test_ingester.py): Unit tests for layout-preserving parsing, file hashing, chunking, and metadata identification.
  - [tests/test_extractor.py](file:///f:/AIML projects/financial-analyst-cli/tests/test_extractor.py): Unit tests for Pydantic validation schemas, classification, arithmetic schedules, and audit trail lineage.
  - [tests/test_analyzer.py](file:///f:/AIML projects/financial-analyst-cli/tests/test_analyzer.py): Unit tests for qualitative views compiling, longitudinal financial trends, and Q4 deduction logic.
  - [tests/data/golden_aapl_2024.json](file:///f:/AIML projects/financial-analyst-cli/tests/data/golden_aapl_2024.json): Golden evaluation baseline dataset for AAPL.



## Architectural Patterns & Guidelines
- **Tooling**: Always use `uv` for Python-related tasks.
- **Execution**: Run Python scripts/tools using `uv run`.
- **Hybrid Build**: Compile the Rust extension module using `maturin develop` before running Python.
- **Commands**: Preferred pattern is `uv run python <file>.py` or `uv run <command>`.
- **OS/Shell**: Windows with PowerShell (`pwsh`).
