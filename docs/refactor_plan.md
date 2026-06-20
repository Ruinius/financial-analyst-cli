# Blackboard Refactoring Implementation Plan

This document details the step-by-step implementation plan for refactoring the `financial-analyst-cli` project into a stateful, modular **Micro-Agent Architecture** centered around the **Temporal Blackboard Pattern**.

---

## Phase 1: Client Provider Separation (Foundation)

### Goal
Refactor `src/services/llm_client.py` to decouple the generic provider logic into dedicated, isolated provider clients. This establishes a clean foundation for structured JSON schemas and robust model configuration options.

### Checklist

- [ ] **Create Gemini Client**
  - Path: [gemini_client.py](file:///f:/AIML%20projects/financial-analyst-cli/src/services/gemini_client.py)
  - Implement `GeminiLLMClient` wrapping the official `google-genai` SDK.
  - Support native structured outputs via `response_schema` parameter.
  - Implement automatic function calling / tool binding for Gemini-specific invocations.
- [ ] **Create DeepSeek Client**
  - Path: [deepseek_client.py](file:///f:/AIML%20projects/financial-analyst-cli/src/services/deepseek_client.py)
  - Implement `DeepSeekLLMClient` tailored for DeepSeek API specifications.
  - Configure reasoning token parameters (`max_thinking_tokens`) and manage extraction of thoughts.
- [ ] **Create OpenRouter Client**
  - Path: [openrouter_client.py](file:///f:/AIML%20projects/financial-analyst-cli/src/services/openrouter_client.py)
  - Implement `OpenRouterLLMClient` standardizing the payload structure, routing parameters, and required application headers.
- [ ] **Refactor LLM Client Factory**
  - Path: [llm_client.py](file:///f:/AIML%20projects/financial-analyst-cli/src/services/llm_client.py)
  - Re-purpose the file to act as the primary client manager and factory.
  - Expose a clean `get_llm_client(provider: str, model: str)` function mapping configuration strings to specific client classes.
- [ ] **Verify and Update Tests**
  - Path: [test_llm_clients.py](file:///f:/AIML%20projects/financial-analyst-cli/tests/test_llm_clients.py)
  - Write test coverage for the modularized clients and ensure factory methods instantiate the correct clients.

### Post-Coding Audit
1. [ ] **Provider Isolation Check**: Verify that `src/services/llm_client.py` contains zero endpoint setup logic or provider-specific parameter adjustments.
2. [ ] **Dependency Leaks Check**: Assert that imports for the `google-genai` SDK are restricted to [gemini_client.py](file:///f:/AIML%20projects/financial-analyst-cli/src/services/gemini_client.py) and do not leak into other client modules.
3. [ ] **Execution Validation**: Execute `uv run pytest tests/test_llm_clients.py` and confirm all factory initialization, streaming capabilities, and error handlers pass without issue.

---

## Phase 2: Blackboard State & Pydantic Micro-Agents

### Goal
Implement the central blackboard schema (`WorkspaceContext`) and refactor the specialist sub-extractors, metric agents, and modeling agents to be purely stateless, functional Python callables that read and return Pydantic schemas mapping directly to the blackboard.

### Checklist

- [ ] **Implement Blackboard Pydantic Domain Schema**
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
    - `WorkspaceContext` (Root Blackboard Model)
- [ ] **Write Atomic Storage Manager**
  - Path: [blackboard.py](file:///f:/AIML%20projects/financial-analyst-cli/src/core/blackboard.py)
  - Implement `load_workspace_state(ticker: str) -> WorkspaceContext`.
  - Implement `save_workspace_state(ticker: str, state: WorkspaceContext)` using the **Single-Writer Pattern** with atomic file replacement:
    1. Serialize state into `workspace_state.json.tmp`.
    2. Atomically replace the target file using `os.replace` to prevent state corruption during execution crashes.
- [ ] **Refactor Extraction Sub-Agents**
  - Standardize sub-agents as stateless functions with no file I/O that return Pydantic outputs and strictly enforce turn limits and tool restrictions.
  - [ ] **`MetadataAgent`**: [metadata_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/metadata_agent.py)
    - Tools: `get_first_chunk`, `keyword_search` (10-turn limit).
    - Scans fanned-in documents in the parsed folder to extract company metadata (name, description, fiscal calendar dates, currencies, conversion factors) to establish the prerequisite setup before spawning other agents.
  - [ ] **`BalanceSheetAgent`**: [balance_sheet_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_financials_agents/balance_sheet_agent.py)
    - Tools: `find_chunk`, `keyword_search` (20-turn limit).
  - [ ] **`IncomeStatementAgent`**: [income_statement_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_financials_agents/income_statement_agent.py)
    - Tools: `find_chunk`, `keyword_search` (20-turn limit).
  - [ ] **`AnalystReportAgent`**: [extractor_analyst_report.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_analyst_report.py)
    - Tools: `find_chunk`, `keyword_search` (10-turn limit).
  - [ ] **`OtherDocAgent`**: [extractor_other.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_other.py)
    - Tools: `find_chunk`, `keyword_search` (10-turn limit).
- [ ] **Refactor Metrics Sub-Agents**
  - Refactor agents to rely on `query_blackboard` for read-only state dependencies.
  - [ ] **`DilutedSharesAgent`**: [diluted_shares_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_financials_agents/diluted_shares_agent.py)
    - Tools: `keyword_search`, `query_blackboard` (10-turn limit).
  - [ ] **`OrganicGrowthAgent`**: [organic_growth_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_financials_agents/organic_growth_agent.py)
    - Tools: `keyword_search`, `query_blackboard` (10-turn limit).
  - [ ] **`InterpretationAgent`**: [interpretation_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_financials_agents/interpretation_agent.py)
    - Tools: `access_resources`, `query_blackboard` (10-turn limit).
  - [ ] **`OperatingEbitaAgent`**: [ebita_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_financials_agents/ebita_agent.py)
    - Tools: `keyword_search`, `query_blackboard` (10-turn limit).
  - [ ] **`AdjustedTaxesAgent`**: [tax_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_financials_agents/tax_agent.py)
    - Tools: `keyword_search`, `query_blackboard` (10-turn limit).
- [ ] **Refactor Modeling Sub-Agents**
  - Standardize modeling agents to extract assumptions, execute pre-flight dependency checks, and output to the blackboard.
  - [ ] **`WaccAgent`**: [wacc_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/modeler_agents/wacc_agent.py)
    - Tools: `market_data`, `query_blackboard` (10-turn limit).
    - Checks for latest balance sheet state, fetches ticker pricing, and calculates debt weights and cost of equity.
  - [ ] **`GrowthAgent`**: [growth_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/modeler_agents/growth_agent.py)
    - Tools: `web_search`, `query_blackboard` (10-turn limit).
    - Checks historical summaries and compiles future revenue growth assumptions.
  - [ ] **`MarginAgent`**: [margin_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/modeler_agents/margin_agent.py)
    - Tools: `web_search`, `query_blackboard` (10-turn limit).
    - Analyzes analyst reports and determines short-term and terminal margins.
  - [ ] **`NonOperatingAgent`**: [non_operating_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/modeler_agents/non_operating_agent.py)
    - Tools: `access_resources`, `query_blackboard` (10-turn limit).
    - Reconciles the 6 non-operating bridge items from the latest balance sheet.
  - [ ] **`DcfModelingAgent`**: [dcf_modeling_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/modeler_agents/dcf_modeling_agent.py)
    - Tools: `query_blackboard` (10-turn limit).
    - Reviews calculations, validates assumptions, and formats critique feedback.
- [ ] **Implement Progressive Turn Warning Mechanism**
  - Inject turn instructions containing current counts, remaining allowances, and historical runtimes (`average_turn_count`) to urge optimal, fast sub-agent exit.
- [ ] **Implement Learning Agent**
  - Path: [learning_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/learning_agent.py)
  - Evaluates turn deviation against `average_turn_count` to run discretionary learnings updates. Writes keywords, target chunks, and execution histories back to `company_data.learnings`.

### Post-Coding Audit
1. [ ] **State Deserialization Validation**: Confirm `WorkspaceContext.model_validate_json()` successfully parses complete workspace states without validation errors.
2. [ ] **Stateless Code Inspection**: Check that all refactored sub-agents contain ZERO file operations (`open()`, `json.dump`, `os.path`) referencing `workspace_state.json`.
3. [ ] **Dependency Logic Validation**: Verify that WACC, Growth, and Margin modeling agents gracefully return structured dependency errors (instead of throwing tracebacks or crashing) when queried previous metrics do not exist on the blackboard.
4. [ ] **Atomic Swap Validation**: Check that atomic write triggers yield `workspace_state.json.tmp` files and correctly invoke `os.replace` to replace the final target file.

---

## Phase 3: Blackboard Orchestrator Integration

### Goal
Implement the central pipeline coordinator (`BlackboardOrchestrator`) that manages in-memory check-out/check-in, enforces execution gates, executes multi-document GAAP merge logic, validates arithmetic constraints, coordinates modeling, and modifies the CLI command suite.

### Checklist

- [ ] **Create Blackboard Orchestrator**
  - Path: [blackboard_orchestrator.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/blackboard_orchestrator.py)
  - Implement orchestration supporting full and stage-level execution (`ingest`, `extract`, `analyze`, `model`).
- [ ] **Implement Check-out / Check-in In-Memory Transitions**
  - Prior to agent launch, reservation transitions status flag on blackboard to `running` (committing atomic checkpoint to disk).
  - On sub-agent resolution, releases lock, writes structured payloads, updates status flag to `completed` or `failed`, and atomic commits to disk.
  - On orchestrator restart, scans for dangling `running` items and marks them `failed`/`pending` for safe recovery.
- [ ] **Enforce Execution Gates & Dependencies**
  - Group parallel and sequential tasks inside the async event loop:
    1. **Setup Phase (Sequential)**: Run `metadata_agent` first to populate company metadata (`WorkspaceContext.metadata`). This acts as a blocking gate prerequisite; subsequent agent phases cannot run if company metadata is not successfully completed.
    2. **Extraction Phase (Parallel)**: Launch `balance_sheet`, `income_statement`, `analyst_report`, and `other_doc` concurrently.
    3. **Metrics Level 1 (Parallel)**: Launch `diluted_shares`, `organic_growth`, and `interpretation` concurrently.
    4. **Metrics Level 2 (Sequential)**: Run `operating_ebita` (depends on `interpretation` output).
    5. **Metrics Level 3 (Sequential)**: Run `adjusted_taxes` (depends on `operating_ebita` output).
    6. **Modeling Level 1 (Parallel)**: Launch `wacc`, `growth`, `margin`, and `non_operating` concurrently.
    7. **Modeling Level 2 (Sequential)**: Run `dcf_modeling_agent` (depends on Level 1 modeling inputs).
- [ ] **Implement Multi-Document Period Processing & Merge Policies**
  - Accumulate source documents into `source_files: List[str]`.
  - **GAAP Override**: Structured balance sheet and income statement models from formal filings (10-Q/10-K) overwrite earnings announcement extractions.
  - **Non-GAAP Preservation**: Non-GAAP metrics (constant currency organic growth, operating EBITA, adjusted taxes) extracted from earnings announcements are preserved and not cleared/overwritten when the 10-Q/10-K runs.
  - **Simultaneous Search**: Grant permission to search tools to read both filings concurrently when resolving metric values.
- [ ] **Implement Mathematical Verification Rules**
  - Support relative tolerance `1e-4` and absolute tolerance `$100.0` for float calculations:
    - [ ] **Rule 1**: Total Assets == Total Liabilities + Total Equity.
    - [ ] **Rule 2**: Invested Capital == (Operating Current Assets - Operating Current Liabilities) + (Operating Non-Current Assets - Operating Non-Current Liabilities).
    - [ ] **Rule 3**: Revenue - Cost of Goods Sold - SG&A - R&D == Operating Income.
- [ ] **Implement Concurrency Knobs**
  - Implement `asyncio.Semaphore` configurations to restrict company, document, and phase concurrency to protect LLM API endpoints.
- [ ] **Implement Failure Queue & Recovery Modes**
  - Pushes failures into a sequential queue.
  - [ ] **Non-Interactive Mode (`--non-interactive` flag)**: No stdin query. Auto retries network failures (up to 3 times). Bypasses retries on validation or math issues, marks status `failed`, and halts with exit code `1`.
  - [ ] **Interactive Developer Mode (Default CLI)**: Blocks and requests stdin recovery strategy from user:
    - _Retry_: Re-submits task.
    - _Don't Retry_: Continues pipeline, skipping downstream dependents.
    - _Stop All_: Terminates all active futures and cancels execution.
- [ ] **Refactor CLI Commands & Sub-commands**
  - Modifies CLI entrypoint `src/cli/main.py` and command routing files:
    - [ ] **`fa run extract`**: Spawns orchestrator to resolve pending extraction/metric agents and run math verification.
    - [ ] **`fa run analyze`**: Triggers orchestrator to compile longitudinal financial summary tables.
    - [ ] **`fa run model`**: Coordinates modeling agents, executes Rust (or fallback Python) DCF model, and saves outputs.
    - [ ] **`fa run curate_wiki`**: Runs CuratorAgent to compile `[TICKER]_wiki.md` under write lock.
    - [ ] **`fa use <ticker>` / `fa config init`**: Simplifies setup to initialize only 4 subdirectories (`1_ingest_data/`, `2_parsed_data/`, `3_archived_data/`, `9_scenario_model_json/`) and deletes deprecated directories (`4_extracted_data/`, `5_historical_analysis/`, and `6_financial_model/`).
    - [ ] **Support options**: Integrates `--non-interactive` / `-n` and `--agent <agent_name>` / `-a <agent_name>` globally.
    - [ ] **`fa query` commands**: Streamlines `summary`, `assessment`, and `valuation` to read directly from `workspace_state.json` for speed. Simplifies `trace` to return execution status and timestamps.
- [ ] **Verify against Evaluators**
  - Ensure all golden evaluations (`tests/test_extractor_orchestrator.py`, etc.) pass.

### Post-Coding Audit
1. [ ] **Execution Loop Integration Test**: Verify that the deprecated linear files (`extractor_orchestrator.py`, `extractor_financials.py`, `analyzer.py`, `modeler_orchestrator.py`) have been removed and that `uv run pytest tests/` runs successfully using the new coordinator.
2. [ ] **Multi-Document Merge Check**: Process an earnings release containing non-GAAP items and a subsequent 10-Q/10-K. Verify that GAAP figures overwrite EA details, but non-GAAP attributes (Organic Growth, Adjusted Taxes, Operating EBITA) are preserved.
3. [ ] **Arithmetic Logs Check**: Verify that triggering a balance sheet or income statement math validation failure writes details into the period's `arithmetic_errors` field and correctly marks the task state as `failed`.
4. [ ] **Recovery Prompt Audit**: Run in `--non-interactive` mode, inject a validation failure, and confirm the pipeline halts with exit code `1` immediately without blocking on user input.

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
