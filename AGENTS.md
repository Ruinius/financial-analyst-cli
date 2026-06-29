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
- docs/architecture.md: System architecture, folder structure, micro-agent definitions, tool permissions registry, and design decisions.
- docs/blackboard_design.md: Detailed schema, evolution history, lifecycle, and storage specifications for the blackboard state.
- docs/cli_spec.md: CLI command hierarchy, options, parameters, and user experience specification.
- docs/litellm_refactor.md: Architectural evaluation of migrating LLM service layer to LiteLLM (pros, cons, and hybrid migration strategy).
- docs/requirements.md: Scope of capabilities and product requirements translated from financial-analyst-skills.
- docs/roadmap.md: Seven-phase development and refactoring roadmap for the Financial Analyst CLI.
- LICENSE: MIT License.
- main.py: Application entry point.
- pyproject.toml: Project metadata and dependencies (managed via `uv`), including Maturin build-backend configuration.
- README.md: Project overview and setup instructions.
- tmp/: Temporary logs, scratchpads, and execution scripts.
- src/: Application source package.
  - src/cli/: Sub-commands and main CLI definitions.
    - src/cli/main.py: Primary Typer entry point and command router, including the 'fa run' callback executing the full pipeline.
    - src/cli/commands/config.py: Commands for config initialization (`init`), masked printing (`show`), and direct parameter updating (`set`).
    - src/cli/commands/use.py: Workspace switcher command that updates active ticker and initializes 7 folders.
  - src/core/: Settings, custom exception classes, and Pydantic schemas.
    - src/core/config.py: Settings model definition, loading/saving utilities, and API key masking.
    - src/core/exceptions.py: Custom exception classes (e.g. ConfigError, WorkspaceError, LLMError).
    - src/core/blackboard.py: Blackboard domain schemas (Pydantic models) and atomic load/save state managers.
  - src/agents/: Execution runner stages (ingest, extract, analyze, model).
    - src/agents/agent_executor.py: Unified agent execution loop coordinator for native and simulated tool calling.
    - src/agents/blackboard_orchestrator.py: Coordinates stateful execution of pipeline stages and task status transitions by delegating to modular stage files.
    - src/agents/orchestrator_pipelines/: Directory containing modular pipeline execution stage files.
      - __init__.py: Package initialization file.
      - ingest.py: Stage execution logic for parsing and document ingestion, containing the parser and Ingester class.
      - extract.py: Stage execution logic for extraction and financial metric sub-agents.
      - analyze.py: Stage execution logic for longitudinal trends synthesis.
      - model.py: Stage execution logic for WACC, growth, margin assumptions and running the DCF calculation.
    - src/agents/curator_agent.py: Curator agent for summarizing learnings and refining qualitative bull/bear views.
    - src/agents/learning_agent.py: Learning agent for capturing run learnings and discretionary blackboard updates.
    - src/agents/extractor_agents/: Folder containing all document sub-extractors and agents.
      - src/agents/extractor_agents/extractor_analyst_report.py: Sub-extractor specialized for analyst reports.
      - src/agents/extractor_agents/metadata_agent.py: Sub-extractor specialized for both company-wide and document-level metadata extraction.
      - src/agents/extractor_agents/extractor_other.py: Sub-extractor specialized for all other document types.
      - src/agents/extractor_agents/extractor_financials_agents/: Nested directory for the sub-agents.
        - income_statement_agent.py: Agent specialized in Income Statement extraction.
        - balance_sheet_agent.py: Agent specialized in Balance Sheet extraction.
        - interpretation_agent.py: Agent specialized in interpreting line item classification.
        - diluted_shares_agent.py: Agent specialized in basic and diluted shares.
        - organic_growth_agent.py: Agent specialized in simple and organic revenue growth.
        - ebita_agent.py: Agent specialized in Operating EBITA adjustments and calculations.
        - tax_agent.py: Agent specialized in Adjusted Taxes adjustments and calculations.

    - src/agents/modeler_agents/: Directory containing specialized modeling agents.
      - wacc_agent.py: Agent specialized in WACC calculation and beta de-levering/re-levering.
      - growth_agent.py: Agent specialized in estimating future revenue growth rates (near-term, mid-term Year 5, terminal).
      - margin_agent.py: Agent specialized in estimating future EBITA margins (base, Year 5 target, terminal).
      - non_operating_agent.py: Agent specialized in extracting the 6 non-operating categories from the latest balance sheet.
      - dcf_modeling_agent.py: Agent specialized in reviewing and sanity-checking valuation parameters, currency, shares outstanding, and outputting comments/critiques.
  - src/services/: SEC client, LiteLLM wrapper, web search, and AST-sandboxed math solver.
    - src/services/edgar_client.py: SEC EDGAR download API client.
    - src/services/llm_client.py: Consolidated LiteLLM client implementation (`LiteLLMClient`, `LiteLLMChatSession`) and client factory `get_llm_client`.
    - src/services/market_data.py: Yahoo Finance market data and ticker checker.
    - src/services/ddg_search.py: DuckDuckGo search service.
    - src/services/safe_math_solver.py: AST-sandboxed mathematical equation solver.
    - src/services/queue.py: Safe job queue and exponential back-off retry manager.
  - src/rust_core/lib.rs: Rust module with PyO3 bindings for DCF financial modeling.
  - src/rust_core/fallback.py: Pure Python fallback for DCF modeling when Rust library is not compiled.
  - src/rust_core/__init__.py: Hybrid import loader for the DCF modeling engine.
  - src/viewer/index.html: Interactive zero-dependency web viewer template.
  - src/resources/document_types.json: Mapping definitions for supported financial report types.
  - src/resources/dictionary/: Central accounting glossary and classification dictionary containing definition markdowns and valuation treatment guidelines.
    - income_statement.md: Table mapping of typical income statement line items.
    - balance_sheet.md: Table mapping of typical balance sheet line items.
  - src/tools/: Reusable agent tools package.
    - src/tools/find_chunk.py: Tool to extract chunk content by ID.
    - src/tools/keyword_search.py: Tool to find occurrences of keywords.
    - src/tools/investopedia_search.py: Investopedia search tool.
    - src/tools/access_resources.py: Tool to safely look up static markdown dictionary templates.
    - src/tools/query_blackboard.py: Core helper to query the in-memory blackboard state.
  - src/utils/: CLI output formatting, math utilities, and filesystem helpers.
    - src/utils/formatting.py: Rich terminal formatting helpers and Sir Pennyworth speech bubbles.
    - src/utils/markdown_helper.py: Markdown append/edit utilities, table validation, and JSON text parsing helpers.
    - src/utils/financial_math.py: Pure Python financial calculations utility module (EBITA, Invested Capital, Tax Rates, ROIC).
    - src/utils/pig_animation.py: Sir Pennyworth pig snout and ear console animation helper.

- tests/: Test suite folder. Most of the test suite structure mirrors the project structure (specifically `src/`) to test the corresponding modules. Key files and configurations include:
  - tests/conftest.py: Central reusable mock fixtures (`mock_workspace`, `temp_workspace_env`, `block_network_calls`).
  - tests/data/: Test data directory.
    - tests/data/golden_aapl_2024.json: Golden evaluation baseline dataset for AAPL.

## Architectural Patterns & Guidelines

- **Hybrid Build**: Compile the Rust extension module using `maturin develop` before running Python.
- **Test Focus**: Always run E2E and backend tests for non-trivial modifications. We need to ensure tests pass before committing.
- **Manual CLI Tests**: Never directly use the CLI to run manual tests. Always ask the user instead.
- **Multi-Agent Extraction Pattern**: Unstructured extraction tasks delegate to specialized agents (e.g., Balance Sheet, Income Statement, Interpretation, Diluted Shares, Organic Growth, Operating EBITA, Adjusted Taxes, Analyst Report) running within structured loop boundaries (4-5 turns limit). Categorized results are validated using Pydantic schemas before running deterministic financial calculation schedules in Rust.
- **Lazy CLI Module Imports**: To ensure fast sub-command responsiveness (e.g., `fa use`), heavy service and pipeline dependencies (`litellm`, `EdgarClient`, `Ingester`, `PromptSession`) must be lazily loaded via module `__getattr__` hooks or inside handler functions rather than imported at top-level.
