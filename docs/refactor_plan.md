# Blackboard Refactoring Implementation Plan

This document details the step-by-step implementation plan for refactoring the `financial-analyst-cli` project into a stateful, modular **Micro-Agent Architecture** centered around the **Temporal Blackboard Pattern**.

---

## Phase 1: Client Provider Separation (Foundation)

### Goal

Refactor `src/services/llm_client.py` to decouple the generic provider logic into dedicated, isolated provider clients. This establishes a clean foundation for structured JSON schemas and robust model configuration options.

### Checklist

- [x] **Create Gemini Client**
  - Path: [gemini_client.py](file:///f:/AIML%20projects/financial-analyst-cli/src/services/gemini_client.py)
  - Implement `GeminiLLMClient` wrapping the official `google-genai` SDK.
  - Support native structured outputs via `response_schema` parameter.
  - Implement automatic function calling / tool binding for Gemini-specific invocations.
- [x] **Create DeepSeek Client**
  - Path: [deepseek_client.py](file:///f:/AIML%20projects/financial-analyst-cli/src/services/deepseek_client.py)
  - Implement `DeepSeekLLMClient` tailored for DeepSeek API specifications.
  - Configure reasoning token parameters (`max_thinking_tokens`) and manage extraction of thoughts.
- [x] **Create OpenRouter Client**
  - Path: [openrouter_client.py](file:///f:/AIML%20projects/financial-analyst-cli/src/services/openrouter_client.py)
  - Implement `OpenRouterLLMClient` standardizing the payload structure, routing parameters, and required application headers.
- [x] **Refactor LLM Client Factory**
  - Path: [llm_client.py](file:///f:/AIML%20projects/financial-analyst-cli/src/services/llm_client.py)
  - Re-purpose the file to act as the primary client manager and factory.
  - Expose a clean `get_llm_client(provider: str, model: str)` function mapping configuration strings to specific client classes.
- [x] **Verify and Update Tests**
  - Path: [test_llm_clients.py](file:///f:/AIML%20projects/financial-analyst-cli/tests/test_llm_clients.py)
  - Write test coverage for the modularized clients and ensure factory methods instantiate the correct clients.

### Post-Coding Audit

1. [x] **Provider Isolation Check**: Verify that `src/services/llm_client.py` contains zero endpoint setup logic or provider-specific parameter adjustments.
2. [x] **Dependency Leaks Check**: Assert that imports for the `google-genai` SDK are restricted to [gemini_client.py](file:///f:/AIML%20projects/financial-analyst-cli/src/services/gemini_client.py) and do not leak into other client modules.
3. [x] **Execution Validation**: Execute `uv run pytest tests/test_llm_clients.py` and confirm all factory initialization, streaming capabilities, and error handlers pass without issue.

---

## Phase 2: Blackboard State & Pydantic Micro-Agents

### Goal

Implement the central blackboard schema (`WorkspaceContext`) and refactor the specialist sub-extractors, metric agents, and modeling agents to be purely stateless, functional Python callables that read and return Pydantic schemas mapping directly to the blackboard.

### Phase 2.1: Blackboard Core & Persistence Layer

- [x] **Implement Blackboard Pydantic Domain Schema**
  - Path: [blackboard.py](file:///f:/AIML%20projects/financial-analyst-cli/src/core/blackboard.py)
  - Implement all Pydantic models defined in the [Blackboard Design Specification](file:///f:/AIML%20projects/financial-analyst-cli/docs/blackboard_design.md#L31-L335):
    - `LineItem`: Line item name, value, operating status, calculated status, and category.
    - `CompanyMetadata`: Fiscal boundaries, currency configurations, adr_ratio, fx_rate.
    - `AgentExecutionMetrics`: Total runs, last turn count, average turn count.
    - `ExtractAgentLearning`: Ingest status, successful and avoid keywords/chunks, execution metrics.
    - `DocumentTypeLearnings`: Learnings categorized for balance sheet, income statement, diluted shares, organic growth, EBITA, and tax.
    - `LearningsSchema`: Annual filing, quarterly filing, and earnings announcement learnings.
    - `HistoricalFinancialSummary`: Longitudinal trends flat report table rows.
    - `HistoricalAnalystView`: Consolidated qualitative analyst outlook rows.
    - `CompanyLevelData`: Self-learning schemas, longitudinal financial summary tables, and analyst views.
    - `ExtractedFinancialData`: Sub-agent target values (revenue, margins, shares, taxes, ROIC, invested capital) and raw tables.
    - `AnalystReportExtraction`: Moat, margin, and growth outlooks.
    - `OtherExtraction`: Press release and general document summaries.
    - `ExtractedOtherData`: Merged analyst reports and general other document models.
    - `ModelAssumptions`: WACC, beta, risk free, growth, margin assumptions, non-operating bridge items, capital structures.
    - `DCFProjectionYear`: Years 1-10 projections table columns.
    - `BaseFinancialModel`: Model assumptions, projections list, valuation outputs.
    - `TemporalBlackboard`: Period-specific statements, sub-agent lock-states, structured contents, and arithmetic logs.
    - `RawDocumentState`: Tracks ingest statuses and sha256 checksums per source file.
    - `WorkspaceContext` (Root Blackboard Model) - including `metadata_status`, `analyzer_status`, and `curator_status` process statuses.
- [x] **Write Atomic Storage Manager**
  - Path: [blackboard.py](file:///f:/AIML%20projects/financial-analyst-cli/src/core/blackboard.py)
  - Implement `load_workspace_state(ticker: str) -> WorkspaceContext`.
  - Implement `save_workspace_state(ticker: str, state: WorkspaceContext)` using the **Single-Writer Pattern** with atomic file replacement:
    1. Serialize state into `workspace_state.json.tmp`.
    2. Atomically replace the target file using `os.replace` to prevent state corruption during execution crashes.

### Phase 2.2: Stateless Extractor Sub-Agents

- Standardize sub-agents as stateless functions with no file I/O that return Pydantic outputs and strictly enforce turn limits and tool restrictions:
  - [x] **`MetadataAgent`**: [metadata_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/metadata_agent.py)
    - Tools: `get_first_chunk`, `keyword_search` (10-turn limit).
    - Mandatory Input Context: `list of parsed document filenames`.
    - Scans fanned-in documents in the parsed folder to extract company metadata (name, description, fiscal calendar dates, currencies, conversion factors) to establish the prerequisite setup before spawning other agents.
  - [x] **`BalanceSheetAgent`**: [balance_sheet_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_financials_agents/balance_sheet_agent.py)
    - Tools: `find_chunk`, `keyword_search`, `check_balance_sheet_quality` (20-turn limit).
    - Mandatory Input Context: `target document filename, company metadata, agent learnings`.
  - [x] **`IncomeStatementAgent`**: [income_statement_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_financials_agents/income_statement_agent.py)
    - Tools: `find_chunk`, `keyword_search`, `check_income_statement_quality` (20-turn limit).
    - Mandatory Input Context: `target document filename, company metadata, agent learnings`.
  - [x] **`AnalystReportAgent`**: [extractor_analyst_report.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_analyst_report.py)
    - Tools: `find_chunk`, `keyword_search` (10-turn limit).
    - Mandatory Input Context: `target document filename, company metadata, agent learnings`.
  - [x] **`OtherDocAgent`**: [extractor_other.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_other.py)
    - Tools: `find_chunk`, `keyword_search` (10-turn limit).
    - Mandatory Input Context: `target document filename, company metadata, agent learnings`.

### Phase 2.3: Stateless Metrics Sub-Agents

- Refactor agents to rely on `query_blackboard` for read-only state dependencies:
  - [x] **`DilutedSharesAgent`**: [diluted_shares_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_financials_agents/diluted_shares_agent.py)
    - Tools: `keyword_search`, `query_blackboard` (10-turn limit).
    - Mandatory Input Context: `company metadata, income_statement, 10-Q/10-K filename, earnings announcement filename`.
  - [x] **`OrganicGrowthAgent`**: [organic_growth_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_financials_agents/organic_growth_agent.py)
    - Tools: `keyword_search`, `query_blackboard` (10-turn limit).
    - Mandatory Input Context: `company metadata, income_statement, 10-Q/10-K filename, earnings announcement filename`.
  - [x] **`InterpretationAgent`**: [interpretation_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_financials_agents/interpretation_agent.py)
    - Tools: `access_resources`, `query_blackboard` (10-turn limit).
    - Mandatory Input Context: `company metadata, income_statement, balance_sheet`.
  - [x] **`OperatingEbitaAgent`**: [ebita_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_financials_agents/ebita_agent.py)
    - Tools: `keyword_search`, `query_blackboard` (10-turn limit).
    - Mandatory Input Context: `company metadata, income_statement, 10-Q/10-K filename, earnings announcement filename`.
  - [x] **`AdjustedTaxesAgent`**: [tax_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_financials_agents/tax_agent.py)
    - Tools: `keyword_search`, `query_blackboard` (10-turn limit).
    - Mandatory Input Context: `company metadata, income_statement, 10-Q/10-K filename, earnings announcement filename`.

### Phase 2.4: Stateless Modeler Sub-Agents

- Standardize modeling agents to extract assumptions, execute pre-flight dependency checks, and output to the blackboard:
  - [x] **`WaccAgent`**: [wacc_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/modeler_agents/wacc_agent.py)
    - Tools: `market_data`, `query_blackboard` (10-turn limit).
    - Mandatory Input Context: `company metadata, latest temporal period slice`.
    - Checks for latest balance sheet state, fetches ticker pricing, and calculates debt weights and cost of equity.
  - [x] **`GrowthAgent`**: [growth_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/modeler_agents/growth_agent.py)
    - Tools: `web_search`, `query_blackboard` (10-turn limit).
    - Mandatory Input Context: `latest temporal period slice, company metadata, trend tables`.
    - Checks historical summaries and compiles future revenue growth assumptions.
  - [x] **`MarginAgent`**: [margin_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/modeler_agents/margin_agent.py)
    - Tools: `web_search`, `query_blackboard` (10-turn limit).
    - Mandatory Input Context: `latest temporal period slice, company metadata, trend tables`.
    - Analyzes analyst reports and determines short-term and terminal margins.
  - [x] **`NonOperatingAgent`**: [non_operating_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/modeler_agents/non_operating_agent.py)
    - Tools: `access_resources`, `query_blackboard` (10-turn limit).
    - Mandatory Input Context: `latest temporal period slice`.
    - Queries/extracts the 6 non-operating categories from the latest fanned-in balance sheet state.
  - [x] **`DcfModelingAgent`**: [dcf_modeling_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/modeler_agents/dcf_modeling_agent.py)
    - Tools: `query_blackboard` (10-turn limit).
    - Mandatory Input Context: `company metadata, latest temporal period slice, model assumptions`.
    - Reviews calculations, validates assumptions, and formats critique feedback.

### Phase 2.5: Curator, Learning, and Turn Warning Mechanisms

- [x] **Implement Progressive Turn Warning Mechanism**
  - Inject turn instructions containing current counts, remaining allowances, and historical runtimes (`average_turn_count`) to urge optimal, fast sub-agent exit.
- [x] **Implement Curator Agent**
  - Path: [curator_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/curator_agent.py)
  - Tools: `query_blackboard` (10-turn limit).
  - Mandatory Input Context: `company metadata, complete WorkspaceContext`.
  - Solely responsible for writing and updating the `[TICKER]_wiki.md` file using compiled blackboard data under write lock.
- [x] **Implement Learning Agent**
  - Path: [learning_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/learning_agent.py)
  - Tools: `query_blackboard`.
  - Mandatory Input Context: `target sub-agent name, document type, turn counts/run logs`.
  - Evaluates turn deviation against `average_turn_count` to run discretionary learnings updates. Writes keywords, target chunks, and execution histories back to `company_data.learnings`.

### Phase 2.6: Post-Coding Audit (Phase 2)

1. [x] **State Deserialization Validation**: Confirm `WorkspaceContext.model_validate_json()` successfully parses complete workspace states without validation errors.
2. [x] **Stateless Code Inspection**: Check that all refactored sub-agents contain ZERO file operations (`open()`, `json.dump`, `os.path`) referencing `workspace_state.json`.
3. [x] **Dependency Logic Validation**: Verify that WACC, Growth, and Margin modeling agents gracefully return structured dependency errors (instead of throwing tracebacks or crashing) when queried previous metrics do not exist on the blackboard.
4. [x] **Atomic Swap Validation**: Check that atomic write triggers yield `workspace_state.json.tmp` files and correctly invoke `os.replace` to replace the final target file.

---

## Phase 3: Blackboard Orchestrator Integration

### Goal

Implement the central pipeline coordinator (`BlackboardOrchestrator`) that manages in-memory check-out/check-in, enforces execution gates, executes multi-document GAAP merge logic, validates arithmetic constraints, coordinates modeling, and modifies the CLI command suite.

### Phase 3.1: Orchestration Core & Lifecycle Transitions

- [x] **Create Blackboard Orchestrator**
  - Path: [blackboard_orchestrator.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/blackboard_orchestrator.py)
  - Implement orchestration supporting full and stage-level execution (`ingest`, `extract`, `analyze`, `model`).
- [x] **Implement Check-out / Check-in In-Memory Transitions**
  - Prior to agent launch, reservation transitions status flag on blackboard to `running` (committing atomic checkpoint to disk).
  - On sub-agent resolution, releases lock, writes structured payloads, updates status flag to `completed` or `failed`, and atomic commits to disk.
  - On orchestrator restart, scans for dangling `running` items and marks them `failed`/`pending` for safe recovery.
- [x] **Implement Single Agent Execution Capability**
  - Add logic in [blackboard_orchestrator.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/blackboard_orchestrator.py) to check and support the `agent` parameter (e.g. `--agent <agent_name>` / `-a <agent_name>`).
  - Only execute the targeted specialist agent, verifying its input prerequisite dependencies first.

### Phase 3.2: Execution Gating & Concurrency Control

- [x] **Enforce Execution Gates & Dependencies**
  - Group parallel and sequential tasks inside the async event loop:
    1. **Setup Phase (Sequential)**: Run `metadata_agent` first to populate company metadata (`WorkspaceContext.metadata`). This acts as a blocking gate prerequisite; subsequent agent phases cannot run if company metadata is not successfully completed.
    2. **Extraction Phase (Parallel)**: Launch `balance_sheet`, `income_statement`, `analyst_report`, and `other_doc` concurrently.
    3. **Metrics Level 1 (Parallel)**: Launch `diluted_shares`, `organic_growth`, and `interpretation` concurrently.
    4. **Metrics Level 2 (Parallel)**: Launch `operating_ebita` (depends on `interpretation` output) and `adjusted_taxes` (depends on `interpretation` output; uses `operating_ebita` if available, but it's optional) concurrently.
    5. **Modeling Level 1 (Parallel)**: Launch `wacc`, `growth`, `margin`, and `non_operating` concurrently.
    6. **Modeling Level 2 (Sequential)**: Run `dcf_modeling_agent` (depends on Level 1 modeling inputs).
- [x] **Implement Concurrency Knobs**
  - Implement `asyncio.Semaphore` configurations to restrict company, document, and phase concurrency to protect LLM API endpoints.

### Phase 3.3: Merge Policies & Arithmetic Checks

- [x] **Implement Multi-Document Period Processing & Merge Policies**
  - Accumulate source documents into `source_files: List[str]`.
  - **GAAP Override**: Structured balance sheet and income statement models from formal filings (10-Q/10-K) overwrite earnings announcement extractions.
  - **Non-GAAP Preservation**: Non-GAAP metrics (constant currency organic growth, operating EBITA, adjusted taxes) extracted from earnings announcements are preserved and not cleared/overwritten when the 10-Q/10-K runs.
  - **Simultaneous Search**: Grant permission to search tools to read both filings concurrently when resolving metric values.
- [x] **Implement Quality Audit & Validation Checks**
  - Integrate robust LLM-based quality audit tools `check_balance_sheet_quality` and `check_income_statement_quality` inside the sub-agents before finalizing.
  - Ensure any quality check warnings or failures are logged and handled.
  - If a sub-agent fails its quality audit checks and runs out of execution turns, the Orchestrator marks the task state as `failed`.

### Phase 3.4: Recovery Queue & CLI Restructuring

- [x] **Implement Failure Queue & Recovery Modes**
  - Pushes failures into a sequential queue.
  - [x] **Non-Interactive Mode (`--non-interactive` flag)**: No stdin query. Auto retries network failures (up to 3 times). Bypasses retries on validation or quality issues, marks status `failed`, and halts with exit code `1`.
  - [x] **Interactive Developer Mode (Default CLI)**: Blocks and requests stdin recovery strategy from user:
    - _Retry_: Re-submits task.
    - _Don't Retry_: Continues pipeline, skipping downstream dependents.
    - _Stop All_: Terminates all active futures and cancels execution.
- [x] **Refactor CLI Commands & Sub-commands**
  - Modifies CLI entrypoint `src/cli/main.py` and command routing files:
    - [x] **`fa run extract`**: Spawns orchestrator to resolve pending extraction/metric agents and run quality validation.
    - [x] **`fa run analyze`**: Triggers orchestrator to compile longitudinal financial summary tables.
    - [x] **`fa run model`**: Coordinates modeling agents, executes Rust (or fallback Python) DCF model, and saves outputs.
    - [x] **`fa run curate_wiki`**: Runs CuratorAgent to compile `[TICKER]_wiki.md` under write lock.
    - [x] **`fa use <ticker>` / `fa config init`**: Simplifies setup to initialize only 4 subdirectories (`1_ingest_data/`, `2_parsed_data/`, `3_archived_data/`, `9_scenario_model_json/`) and deletes deprecated directories (`4_extracted_data/`, `5_historical_analysis/`, and `6_financial_model/`).
    - [x] **Support options**: Integrates `--non-interactive` / `-n` and `--agent <agent_name>` / `-a <agent_name>` globally.
    - [x] **`fa query` commands**: Streamlines `summary`, `assessment`, and `valuation` to read directly from `workspace_state.json` for speed. Simplifies `trace` to return execution status and timestamps.

### Phase 3.5: Orchestrator Pipeline Modularization & Maintenance

- [x] **Create Orchestrator Pipelines Directory**
  - Path: [src/agents/orchestrator_pipelines/](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/orchestrator_pipelines)
  - Modularize the monolithic `BlackboardOrchestrator` execution stages (`ingest`, `extract`, `analyze`, `model`) and full pipelines into separate files within this package to enhance maintainability.
  - Simplify [blackboard_orchestrator.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/blackboard_orchestrator.py) to delegate to these modular files.

### Phase 3.6: Test Suite Refactoring

- [ ] **Establish Modular Test Layout**:
  - Reorganize directory structure to mirror the `src/` modular layout, performing the following moves and deletions:
    - [NEW] `tests/conftest.py`: Establish central, reusable mock fixtures (`mock_workspace`, `mock_llm_client`, base settings fixtures).
    - [NEW] `tests/agents/`: Group unit and LLM-interaction tests for individual specialist sub-agents.
      - [NEW] `test_wacc_agent.py`: Split out from `test_modeler.py`.
      - [NEW] `test_growth_agent.py`: Split out from `test_modeler.py`.
      - [NEW] `test_margin_agent.py`: Split out from `test_modeler.py`.
      - [NEW] `test_non_operating_agent.py`: Split out from `test_modeler.py`.
      - [NEW] `test_dcf_modeling_agent.py`: Split out from `test_modeler.py`.
      - [NEW] `test_balance_sheet_agent.py`: Split out from `test_extractor_orchestrator.py`.
      - [NEW] `test_income_statement_agent.py`: Split out from `test_extractor_orchestrator.py`.
      - [NEW] `test_analyst_report_agent.py`: Split out from `test_extractor_orchestrator.py`.
      - [NEW] `test_metadata_agent.py`: Split out from `test_extractor_orchestrator.py`.
      - [NEW] `test_other_doc_agent.py`: Split out from `test_extractor_orchestrator.py`.
      - [MOVE/RENAME] `tests/test_analyzer.py` -> `tests/agents/test_analyzer.py`
      - [MOVE/RENAME] `tests/test_indexer.py` -> `tests/agents/test_indexer.py`
      - [MOVE/RENAME] `tests/test_ingester.py` -> `tests/agents/test_ingester.py`
    - [NEW] `tests/agents/orchestrator_pipelines/`: Group unit and integration tests for modular orchestrator pipeline files (`ingest.py`, `extract.py`, `analyze.py`, `model.py` stage controllers), avoiding monolithic test files.
      - [NEW] `test_pipeline_ingest.py`: Specialized tests for the ingestion pipeline stage.
      - [NEW] `test_pipeline_extract.py`: Specialized tests for the extraction pipeline stage.
      - [NEW] `test_pipeline_analyze.py`: Specialized tests for the analysis pipeline stage.
      - [NEW] `test_pipeline_model.py`: Specialized tests for the modeling pipeline stage.
    - [NEW] `tests/core/`: Keep blackboard and config tests.
      - [MOVE/RENAME] `tests/test_blackboard.py` -> `tests/core/test_blackboard.py`
      - [MOVE/RENAME] `tests/test_config.py` -> `tests/core/test_config.py`
    - [NEW] `tests/services/`: Move LLM, SEC EDGAR, DDG, and math solver tests.
      - [MOVE/RENAME] `tests/test_llm_clients.py` -> `tests/services/test_llm_clients.py`
      - [MOVE/RENAME] `tests/test_edgar.py` -> `tests/services/test_edgar.py`
      - [MOVE/RENAME] `tests/test_safe_math_solver.py` -> `tests/services/test_safe_math_solver.py`
    - [NEW] `tests/utils/`: Move utilities, terminal layout, and formatting tests.
      - [MOVE/RENAME] `tests/test_formatting.py` -> `tests/utils/test_formatting.py`
      - [MOVE/RENAME] `tests/test_markdown_table_validator.py` -> `tests/utils/test_markdown_table_validator.py`
    - [NEW] `tests/cli/`: Move interactive and query command tests.
      - [MOVE/RENAME] `tests/test_chat.py` -> `tests/cli/test_chat.py`
      - [MOVE/RENAME] `tests/test_query.py` -> `tests/cli/test_query.py`
      - [MOVE/RENAME] `tests/test_viewer.py` -> `tests/cli/test_viewer.py`
    - [DELETE] Remove original monolithic root files once all contents have been successfully migrated:
      - `tests/test_modeler.py`
      - `tests/test_extractor_orchestrator.py`
      - `tests/agents/test_blackboard_orchestrator.py` (split and moved to core lifecycle and pipeline tests)
- [ ] **Decouple Integration & Unit Testing**:
  - Restructure tests so that pure logic / formula functions (e.g., WACC calculation capping, Pydantic schemas validation) do not require heavy disk or LLM mocks.
  - Simplify coordinator/integration testing inside `tests/agents/test_extractor_orchestrator.py` and `tests/agents/test_modeler_orchestrator.py`.
- [ ] **Verify Execution**:
  - Assert that all 124 tests continue to pass under the new structure and execution latency is optimized.

### Phase 3.7: Legacy Agent Code Cleanup

- [ ] **Deprecate and Remove Legacy Agent Orchestration Code**
  - Delete legacy linear pipeline controllers:
    - [DELETE] [extractor_orchestrator.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_orchestrator.py)
    - [DELETE] [extractor_financials.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_financials.py)
    - [DELETE] [analyzer.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/analyzer.py)
    - [DELETE] [modeler.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/modeler.py)
    - [DELETE] [modeler_orchestrator.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/modeler_orchestrator.py)
  - Ensure all CLI command definitions route through the new blackboard orchestrator pipeline.

### Phase 3.8: Post-Coding Audit (Phase 3)

1. [ ] **Execution Loop Integration Test**: Verify that the deprecated linear files (`extractor_orchestrator.py`, `extractor_financials.py`, `analyzer.py`, `modeler_orchestrator.py`) have been removed and that `uv run pytest tests/` runs successfully using the new coordinator.
2. [ ] **Multi-Document Merge Check**: Process an earnings release containing non-GAAP items and a subsequent 10-Q/10-K. Verify that GAAP figures overwrite EA details, but non-GAAP attributes (Organic Growth, Adjusted Taxes, Operating EBITA) are preserved.
3. [ ] **Validation Logs Check**: Verify that a sub-agent running out of turns with quality audit check failures writes details into the period's `arithmetic_errors` field and correctly marks the task state as `failed`.
4. [ ] **Recovery Prompt Audit**: Run in `--non-interactive` mode, inject a quality validation failure, and confirm the pipeline halts with exit code `1` immediately without blocking on user input.

---

## Phase 4: Interactive Chat & Multi-Company Analytics (Deferred)

### Goal

Establish cross-company indexing and enable a natural-language query interface querying flat tables indexed from workspace states.

### Checklist

- [ ] **Synchronize Workspace JSON to Global JSON Index**
  - Write a lightweight indexer to extract flat metrics from `workspace_state.json` files and compile them into a global `workspaces/workspace_index.json` registry file.
- [ ] **Create Chat Command Suite**
  - Path: [chat.py](file:///f:/AIML%20projects/financial-analyst-cli/src/cli/commands/chat.py)
  - Create standard interactive chat loop commands (`fa chat`).
- [ ] **Expose Read-Only Query Tools to Chat Agent**
  - Bind `read_blackboard(ticker, period)`, `search_wiki(query)`, and `trigger_pipeline_run(ticker)` to the chat session.
- [ ] **Write Integration Tests**
  - Path: [test_chat.py](file:///f:/AIML%20projects/financial-analyst-cli/tests/test_chat.py)
  - Verify chat tool routing, cross-company comparisons, and missing data backfill triggering.

### Post-Coding Audit

1. [ ] **Sync Execution Audit**: Verify that running the indexer successfully extracts flat records from `workspace_state.json` and writes them into `workspaces/workspace_index.json`.
2. [ ] **Read-Only Bounds Check**: Confirm that query tools bound to the chat loop are strictly read-only and prevent the chat model from modifying any values inside the company-specific blackboard JSON files.
3. [ ] **Comparison Verification**: Assert that cross-company comparison prompts (e.g., identifying highest organic growth rates) correctly query the consolidated JSON index or read fanned-out JSON states, yielding accurate comparisons.
