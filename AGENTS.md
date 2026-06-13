# AGENTS.md

Welcome to the `financial-analyst-cli` project.

## Project Structure

- AGENTS.md: Architectural patterns, module boundaries, and documentation standards.
- .gitignore: Ignored files configuration.
- .pre-commit-config.yaml: Git pre-commit hooks configuration (linters, secret prevention checks).
- .jules/: Run learnings and vulnerability post-mortems.
  - .jules/bolt.md: Learning from file I/O bottleneck in financial line item extraction.
  - .jules/sentinel.md: Learnings and preventions from path traversal vulnerabilities in local viewer server.
- Cargo.toml: Cargo configuration for the Rust Core calculation engine.
- docs/architecture.md: System architecture, folder structure, and software design decisions.
- docs/agentic_refactor.md: Plan and agent specification for transitioning to the multi-agent financial extraction system.
- docs/cli_spec.md: CLI command hierarchy, options, parameters, and user experience specification.
- docs/requirements.md: Scope of capabilities and product requirements translated from financial-analyst-skills.
- docs/roadmap.md: Six-phase development plan for implementing the Financial Analyst CLI.
- LICENSE: MIT License.
- main.py: Application entry point.
- pyproject.toml: Project metadata and dependencies (managed via `uv`), including Maturin build-backend configuration.
- README.md: Project overview and setup instructions.
- tmp/: Temporary logs, scratchpads, and execution scripts.
- src/: Application source package.
  - src/cli/: Sub-commands and main CLI definitions.
    - src/cli/main.py: Primary Typer entry point and command router.
    - src/cli/commands/config.py: Commands for config initialization (`init`), masked printing (`show`), and direct parameter updating (`set`).
    - src/cli/commands/use.py: Workspace switcher command that updates active ticker and initializes 7 folders.
  - src/core/: Settings, custom exception classes, and Pydantic schemas.
    - src/core/config.py: Settings model definition, loading/saving utilities, and API key masking.
    - src/core/exceptions.py: Custom exception classes (e.g. ConfigError, WorkspaceError).
  - src/pipeline/: Execution runner stages (ingest, extract, historical, model).
    - src/pipeline/queue.py: Safe job queue and exponential back-off retry manager.
    - src/pipeline/ingester.py: File parsing, deduplication, chunking, and LLM metadata identification.
    - src/pipeline/curator_agent.py: Curator agent for summarizing learnings and refining qualitative bull/bear views.
    - src/pipeline/document_types.json: Mapping definitions for supported financial report types.
    - src/pipeline/extractor_orchestrator.py: Orchestrates document parsing, metadata processing, and routing of extraction jobs to document-type sub-extractors.
    - src/pipeline/extractor_agents/: Folder containing all document sub-extractors and agents.
      - src/pipeline/extractor_agents/extractor_financials.py: Sub-extractor coordinator specialized for 10-K, 10-Q, 20-F, and earnings announcements.
      - src/pipeline/extractor_agents/extractor_analyst_report.py: Sub-extractor specialized for analyst reports.
      - src/pipeline/extractor_agents/extractor_transcript.py: Sub-extractor specialized for transcripts.
      - src/pipeline/extractor_agents/extractor_other.py: Sub-extractor specialized for all other document types.
      - src/pipeline/extractor_agents/extractor_financials_agents/: Nested directory for the sub-agents.
        - income_statement_agent.py: Agent specialized in Income Statement extraction.
        - balance_sheet_agent.py: Agent specialized in Balance Sheet extraction.
        - interpretation_agent.py: Agent specialized in interpreting line item classification.
        - diluted_shares_agent.py: Agent specialized in basic and diluted shares.
        - organic_growth_agent.py: Agent specialized in simple and organic revenue growth.
        - ebita_agent.py: Agent specialized in Operating EBITA adjustments and calculations.
        - tax_agent.py: Agent specialized in Adjusted Taxes adjustments and calculations.
    - src/pipeline/analyzer.py: Longitudinal trend synthesis, analyst view compiling, and Q4 deduction engine.
  - src/services/: SEC client, LLM wrapper, web search, and AST-sandboxed math solver.
    - src/services/edgar_client.py: SEC EDGAR download API client.
    - src/services/llm_client.py: Unified client for text & vision LLMs.
    - src/services/market_data.py: Yahoo Finance market data and ticker checker.
  - src/rust_core/lib.rs: Rust module with PyO3 bindings for DCF financial modeling.
  - src/rust_core/fallback.py: Pure Python fallback for DCF modeling when Rust library is not compiled.
  - src/rust_core/**init**.py: Hybrid import loader for the DCF modeling engine.
  - src/viewer/index.html: Interactive zero-dependency web viewer template.
  - src/resources/dictionary/: Central accounting glossary and classification dictionary containing definition markdowns and valuation treatment guidelines.
    - income_statement.md: Table mapping of typical income statement line items.
    - balance_sheet.md: Table mapping of typical balance sheet line items.
  - src/utils/: CLI output formatting, math utilities, and filesystem helpers.
    - src/utils/formatting.py: Rich terminal formatting helpers and Sir Pennyworth speech bubbles.
    - src/utils/tools.py: Universal utility tools (keyword context finding, markdown appenders, editors).
    - src/utils/math.py: Pure Python financial calculations utility module (EBITA, Invested Capital, Tax Rates, ROIC).

- tests/: Test suite folder.
  - tests/test_analyzer.py: Unit tests for qualitative views compiling, longitudinal financial trends, and Q4 deduction logic.
  - tests/test_chat.py: Unit tests for interactive chat and assistant behavior.
  - tests/test_config.py: Unit and integration tests for CLI commands, key masking, settings logic, and folder initialization.
  - tests/test_edgar.py: Unit tests for the SEC EDGAR client and submissions retrieval.
  - tests/test_extractor_orchestrator.py: Unit tests for Pydantic validation schemas, classification, arithmetic schedules, and audit trail lineage.
  - tests/test_formatting.py: Unit tests for terminal formatting, rich output rendering, and animations.
  - tests/test_ingester.py: Unit tests for layout-preserving parsing, file hashing, chunking, and metadata identification.
  - tests/test_markdown_table_validator.py: Unit tests for markdown table syntax validation.
  - tests/test_math_solver.py: Unit tests for the AST-sandboxed mathematical equation solver.
  - tests/test_modeler.py: Unit tests for DCF modeling, WACC calculation, and intrinsic valuation.
  - tests/test_query.py: Unit tests for database query parsing and execution.
  - tests/test_viewer.py: Unit tests for local scenario server and viewer page routing.
  - tests/data/golden_aapl_2024.json: Golden evaluation baseline dataset for AAPL.

## Architectural Patterns & Guidelines

- **Tooling**: Always use `uv` for Python-related tasks.
- **Execution**: Run Python scripts/tools using `uv run`.
- **Hybrid Build**: Compile the Rust extension module using `maturin develop` before running Python.
- **Commands**: Preferred pattern is `uv run python <file>.py` or `uv run <command>`.
- **OS/Shell**: Windows with PowerShell (`pwsh`).
- **Test Focus:** always run E2E and backend tests for non-trivial modifications. We need to ensure tests pass before committing.
- **Manual CLI Tests**: Never directly use the CLI to run manual tests. Always ask the user instead.
- **Multi-Agent Extraction Pattern**: Unstructured extraction tasks delegate to specialized agents (e.g., Balance Sheet, Income Statement, Interpretation, Diluted Shares, Organic Growth, Operating EBITA, Adjusted Taxes, Analyst Report) running within structured loop boundaries (4-5 turns limit). Categorized results are validated using Pydantic schemas before running deterministic financial calculation schedules in Rust.
