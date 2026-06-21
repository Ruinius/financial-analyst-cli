# Refactoring Design: Micro-Agent Architecture

This document specifies the target architecture, backlog, and plan for refactoring the Financial Analyst CLI from a rigid linear pipeline into a stateful, modular **Micro-Agent Architecture**.

## 1. Context & Motivation

The current architecture operates as a linear, hardcoded Python pipeline:

- **Linear Orchestration**: [extractor_orchestrator.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_orchestrator.py) relies on static conditional statements (`if is_financial: ... elif is_analyst: ...`) to coordinate extraction.
- **Verbose Loop Boilerplate**: Sub-agents like [income_statement_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_financials_agents/income_statement_agent.py) run manual `for` loops inside Python, parsing raw text responses for JSON commands, appending to lists, and managing state transitions.
- **Context Pollution**: Large files force agents to query multiple contexts without isolation of state.

### Target Vision: Focus on Blackboard Orchestrator & LLMWiki Generation

Our immediate refactoring focus is strictly on the **User-Triggered Blackboard Orchestrator**.

By centering on the blackboard state, a single central orchestrator can be triggered or activated by the user. Rather than running a hardcoded sequential pipeline, the orchestrator inspects the current blackboard state and spawns template-based specialist sub-agents dynamically to complete missing or failed sections.

In the future state, individual markdown files inside `4_extracted_data/`, `5_historical_analysis/`, and `6_financial_model/` are entirely replaced by the structured Blackboard state (`workspace_state.json`). Furthermore, `[TICKER]_extract_learning.md`, `[TICKER]_analyze_learning.md`, `[TICKER]_model_learning.md`, and `[TICKER]_folder_index.md` are also replaced by and consolidated into the Blackboard.

Only a single markdown file is retained in the root:

- `[TICKER]_wiki.md`: Curated, clean qualitative views (Bull & Bear perspectives) that must be robustly and comprehensively written.

The simplified local workspace directory structure consists of:

- `[TICKER]_wiki.md`: Curated, robustly written qualitative views.
- `workspace_state.json`: The single source of truth blackboard containing all fanned-in extracted financials, longitudinal trends, DCF assumptions, and consolidated historical run learnings / audit logs (stored at the root of the company's workspace).
- `1_ingest_data/`: Raw downloaded filings and source documents.
- `2_parsed_data/`: Cleaned, layout-preserving parsed markdown files.
- `3_archived_data/`: Archived exact raw documents.
- `9_scenario_model_json/` (previously `7_historical_model_json/`): Structured JSON representations of model projections and scenario models used by the interactive web viewer.

_Note: Subdirectories `4_extracted_data/`, `5_historical_analysis/`, and `6_financial_model/` are deprecated as their contents are now consolidated into the blackboard state._

This rich blackboard database and markdown wiki foundation serve as the database that the **Interactive Chat Mode** will query down the road to answer multi-company questions.

---

## 2. Proposed Architecture

```mermaid
graph TD
    %% Trigger & Activation
    UserTrigger([User Activation / CLI Trigger]) --> Orchestrator[Blackboard Orchestrator]
    TimeTrigger([Cron / Time Trigger]) --> Orchestrator

    %% The Blackboard State
    subgraph Blackboard (Shared Workspace Context)
        WorkspaceDB[(Workspace JSON Database: workspace_state.json)]
        StatusFlags[Task Completion & Validation State]
        ExtractedValues[Extracted Financials & Metrics]
        Learnings[Run Learnings & Lessons]
    end

    %% Orchestrator Loop
    Orchestrator <-->|1. Read Status / 3. Update Flags| StatusFlags

    %% Parallel Sub-Agent Templates
    subgraph Specialist Sub-Agent Templates
        IS[Income Statement Agent]
        BS[Balance Sheet Agent]
        OG[Organic Growth Agent]
        Tax[Tax Agent]
        Wacc[WACC Modeler Agent]
    end

    %% Blackboard Handoffs
    Orchestrator -->|Spawn Sub-Agent Template| IS
    Orchestrator -->|Spawn Sub-Agent Template| BS
    Orchestrator -->|Spawn Sub-Agent Template| OG
    Orchestrator -->|Spawn Sub-Agent Template| Tax
    Orchestrator -->|Spawn Sub-Agent Template| Wacc

    IS -->|Write Raw Items| ExtractedValues
    BS -->|Write Raw Items| ExtractedValues
    OG -->|Write Rates| ExtractedValues
    Tax -->|Write Tax Details| ExtractedValues
    Wacc -->|Write Cost of Capital| ExtractedValues

    %% Curation & Learning Sub-Agents
    Orchestrator -->|Spawn Curation Sub-Agent| CuratorAgent[Curator Agent]
    Orchestrator -->|Spawn Learning Sub-Agent| LearningAgent[Learning Agent]

    CuratorAgent -->|4. Update Robust Qualitative Views| TickerWiki[[[TICKER]_wiki.md]]
    LearningAgent -->|5. Maintain Lessons & Logs| Learnings
```

### Components

#### 1. The Blackboard Schema (`WorkspaceContext`)

The Blackboard acts as a structured domain model for a single target company workspace.

- **Specification**: Detailed Pydantic schemas, state transitions, validation rules, and local storage formats are defined in the dedicated design document: [blackboard_design.md](file:///f:/AIML%20projects/financial-analyst-cli/docs/blackboard_design.md).
- **Core Entities**:
  - `GlobalMetadata`: Tracks company-wide config constants (reporting currency, default unit).
  - `FinancialModel`: Tracks valuation parameters (WACC Cost of Capital, margins, DCF assumptions).
  - `TemporalBlackboard`: Tracks period-specific statement items and status flags (e.g. `balance_sheet_status = "completed"`).
  - `CompanyLevelData`: Stores run-to-run lessons and logging context compiled dynamically by the `LearningAgent` (replaces separate learning markdown files).

#### 2. Blackboard Orchestrator (`src/agents/blackboard_orchestrator.py` or `supervisor_orchestrator.py`)

- Audits the blackboard as a whole and is responsible for starting up and coordinating sub-agents.
- Triggered by responding either to an automated event trigger (e.g., cron or time-based execution) or direct user activation.
- **Asynchronous Concurrency & The Single-Writer Pattern**: Runs independent sub-agents (e.g., `BalanceSheetAgent` and `IncomeStatementAgent`) concurrently within a stage using Python's `asyncio`. It coordinates in-memory state checkout (transition of task status to `running`) and check-in (transition to `completed`/`failed` upon task completion) and performs atomic writes to disk, ensuring that concurrent executions do not create file race conditions.
- **Sequential Execution Stages:** Organizes execution into sequential stages: `ingest` -> `extract` -> `analyze` -> `model`. The CLI/API supports running these stages individually (e.g., executing only the `extract` stage) or triggering a unified, end-to-end `full-run` of the entire pipeline.
- **Decision & Coordination Loop**:
  1. Read the `workspace_state.json` file.
  2. Evaluate which components are `pending` or `failed` for the targeted stage.
  3. Dynamically spawn the matching specialist sub-agent templates (not locked to a rigid sequential pipeline within a stage).
  4. Manage in-memory state status checks and write state checkpoints atomically.
  5. Run validation checks. If validation fails and CLI is in default interactive mode, prompt the developer on the CLI to choose whether to proceed or retry. In non-interactive mode (`--non-interactive`), log the validation failure, bypass retries, and fail-fast with a non-zero exit code.
  6. Call the `LearningAgent` based on the discretionary trigger criteria (if the task took significantly more or fewer turns than the historical average to succeed).
  7. Once all status flags are `completed` and validation checks pass, finalize calculations, build DCF models, and coordinate writing/curating summaries.

#### 3. Specialist Sub-Agent Templates (`src/agents/extractor_agents/` & `src/agents/modeler_agents/`)

- Standardized, reusable agent templates that are spawned on-demand by the Orchestrator.
- Purely functional behavior: they consume isolated input contexts (like parsed chunks or in-memory blackboard slices passed to them as arguments by the Orchestrator) and return structured Pydantic schemas directly back to the Orchestrator (which handles serialization and disk persistence).
- **High Modularization & Standalone Invocation:** Any sub-agent can be invoked independently as a standalone function/component without depending on or spinning up the entire orchestration pipeline.
- **Graceful Dependency Verification:** If a sub-agent depends on previous data (e.g. `WaccAgent` depending on the latest Balance Sheet, or `OrganicGrowthAgent` depending on prior period revenues), the agent checks for the existence of this data on the blackboard (using the read-only `query_blackboard` tool). If the dependencies do not exist, the agent logs/returns a structured dependency error back to the caller instead of crashing.
- **Multi-Source Tool Execution:** The entire document is NEVER passed directly as context to a sub-agent prompt. Instead, specialist metrics agents (`OrganicGrowthAgent`, `OperatingEbitaAgent`, `AdjustedTaxesAgent`) are granted permission to search _both_ the 10-Q/10-K and the earnings announcement files simultaneously via their search tool (`keyword_search`), allowing them to query and reconcile GAAP and non-GAAP details across both files for that period.
- **Turn Limits:** Sub-agents are restricted to strict limits:
  - `BalanceSheetAgent` and `IncomeStatementAgent`: Granted up to **20 turns**.
  - All other specialist sub-agents: Granted up to **10 turns**.
- **Progressive Turn Cost Mechanism & Benchmarking:** A dynamic warning is prepended to the prompt at each turn of the sub-agent, informing it of the current turn count, remaining turns, and historical benchmarks (`last_turn_count`, `average_turn_count`). It warns the agent that each subsequent turn is progressively more expensive to encourage early termination and optimal performance.
- **Purely Stateless**: Sub-agents have no write access to the disk or the main `workspace_state.json` file. All status updates, locking, and merging of their structured output into the blackboard are managed solely by the Orchestrator in memory.
- No direct file I/O: sub-agents do not read or write blackboard/extracted files from or to disk.
- Completely decoupled and pipeline-agnostic: sub-agents have zero awareness of other sub-agents or downstream dependencies.

#### 4. Curation & Learning Sub-Agents (`src/agents/curator_agent.py` & `src/agents/learning_agent.py`)

- **`CuratorAgent`**: A dedicated sub-agent solely responsible for writing and updating the robustly written `[TICKER]_wiki.md` qualitative summary file using all the info compiled on the blackboard. The CuratorAgent writes to the wiki file via an Orchestrator-controlled in-memory lock to prevent write collisions. The curator is run either explicitly via CLI or automatically at most weekly.
- **`LearningAgent`**: A dedicated sub-agent responsible for capturing, formatting, and updating run-to-run learnings and feedback lessons directly into the Pydantic Blackboard state (`workspace_state.json`) under the `company_data.learnings` schemas, keeping track of successful search queries, anomalous items, and historical configurations. It runs dynamically based on a sub-agent taking significantly more or fewer turns than the historical average to succeed.
- **Execution Performance Tracking**: The `LearningAgent` (via the Orchestrator's status logger) is responsible for recording and updating run metrics inside the blackboard for each specific sub-agent type and document type for this company:
  - **Total completed runs** (`total_runs`).
  - **Most recent number of turns taken** (`last_turn_count`).
  - **Average number of turns taken** (`average_turn_count`).

---

## 3. Sub-Agent Templates & Tool Permissions

To support decoupled execution, we establish a strict tool permission registry. Sub-agents are only granted access to the minimal set of tools needed for their operational boundaries.

### Core Tool / Service Catalog

1. **`find_chunk`**: Retrieves the contents of a specific document chunk by its ID.
2. **`keyword_search`**: Searches the parsed document chunks for instances of specific keywords and context.
3. **`access_resources`**: Safely looks up static markdown resources (e.g., central accounting glossaries/dictionaries in the codebase).
4. **`web_search`**: Runs external web queries targeting accounting standards and guidelines (e.g., Investopedia).
5. **`market_data`**: Service API to pull current stock prices, market capitalizations, beta values, and other trading data (e.g., Yahoo Finance).
6. **`query_blackboard`**: Allows a specialist sub-agent to query specific sections of the active blackboard state (such as company metadata, historical reports, or other periods' extracted metrics) in a read-only manner.
7. **`get_first_chunk`**: Retrieves the first chunk of a target parsed document (typically containing document metadata, file header registry, and introduction).

| Specialist Sub-Agent Template | Category   | Permitted Tools / Services             | Mandatory Input Context                                                                | Rationale                                                                                                                |
| :---------------------------- | :--------- | :------------------------------------- | :------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------- |
| **`Ingester`**                | Ingestion  | None                                   | Active Ticker                                                                          | Parses, hashes, and chunks raw documents, running initial LLM metadata identification.                                   |
| **`MetadataAgent`**           | Setup      | `get_first_chunk`, `keyword_search`    | list of parsed document filenames                                                      | Runs once across all parsed documents to extract company name, description, fiscal boundaries, and currency definitions. |
| **`BalanceSheetAgent`**       | Extraction | `find_chunk`, `keyword_search`, `check_balance_sheet_quality`         | target document filename, company metadata, agent learnings                            | Scans raw filings to extract assets, liabilities, and equity tables to return to the Orchestrator.                       |
| **`IncomeStatementAgent`**    | Extraction | `find_chunk`, `keyword_search`, `check_income_statement_quality`         | target document filename, company metadata, agent learnings                            | Scans raw filings to extract revenue, expenses, and income tables to return to the Orchestrator.                         |
| **`AnalystReportAgent`**      | Extraction | `find_chunk`, `keyword_search`         | target document filename, company metadata, agent learnings                            | Scans broker reports to extract moats, margins, and growth views.                                                        |
| **`OtherDocAgent`**           | Extraction | `find_chunk`, `keyword_search`         | target document filename, company metadata, agent learnings                            | Scans transcripts, press releases, and other general filings to generate qualitative summaries.                          |
| **`DilutedSharesAgent`**      | Metrics    | `keyword_search`, `query_blackboard`   | company metadata, income_statement, 10-Q/10-K filename, earnings announcement filename | Searches share counts tables, footnotes, and conversions in filings; extracts basic and diluted shares.                  |
| **`OrganicGrowthAgent`**      | Metrics    | `keyword_search`, `query_blackboard`   | company metadata, income_statement, 10-Q/10-K filename, earnings announcement filename | Searches constant currency and M&A impact disclosures; extracts organic revenue growth.                                  |
| **`InterpretationAgent`**     | Metrics    | `access_resources`, `query_blackboard` | company metadata, income_statement, balance_sheet                                      | Resolves ambiguous/generic lines against dictionaries; performs cross-statement validation checks.                       |
| **`OperatingEbitaAgent`**     | Metrics    | `keyword_search`, `query_blackboard`   | company metadata, income_statement, 10-Q/10-K filename, earnings announcement filename | Extracts operating income and audits non-recurring adjustments to calculate clean Operating EBITA.                       |
| **`AdjustedTaxesAgent`**      | Metrics    | `keyword_search`, `query_blackboard`   | company metadata, income_statement, 10-Q/10-K filename, earnings announcement filename | Scans tax rate reconciliation tables and footnotes; calculates adjusted taxes and tax rate.                              |
| **`Analyzer`**                | Analysis   | `query_blackboard`                     | WorkspaceContext reports dictionary                                                    | Compiles longitudinal trend tables (yearly and quarterly) and updates the blackboard.                                    |
| **`WaccAgent`**               | Modeling   | `market_data`, `query_blackboard`      | company metadata, latest temporal period slice                                         | Fetches stock details and computes WACC parameters; queries latest reports for debt/cash details.                        |
| **`GrowthAgent`**             | Modeling   | `web_search`, `query_blackboard`       | latest temporal period slice, company metadata, trend tables                           | Formulates growth projections; retrieves historical revenues and margins.                                                |
| **`MarginAgent`**             | Modeling   | `web_search`, `query_blackboard`       | latest temporal period slice, company metadata, trend tables                           | Formulates margin targets; retrieves historical margins and analyst views.                                               |
| **`NonOperatingAgent`**       | Modeling   | `access_resources`, `query_blackboard` | latest temporal period slice                                                           | Queries/extracts the 6 non-operating categories from the latest fanned-in balance sheet state.                           |
| **`DcfModelingAgent`**        | Modeling   | `query_blackboard`                     | company metadata, latest temporal period slice, model assumptions                      | Sanity-checks and critiques the completed valuation parameters and assumptions.                                          |
| **`CuratorAgent`**            | Curation   | `query_blackboard`                     | company metadata, complete WorkspaceContext                                            | Solely responsible for writing and updating the `[TICKER]_wiki.md` file.                                                 |
| **`LearningAgent`**           | Learning   | `query_blackboard`                     | target sub-agent name, document type, turn counts/run logs                             | Responsible for writing and maintaining the run learnings and feedback logs into the blackboard.                         |

---

## 4. Verification and Testing

- **Modular Test Harnesses**: Write tests verifying each micro-agent independently (e.g., passing a simulated parsed page and verifying the exact structure of the Pydantic response).
- **Blackboard State Tracing**: Ensure that state updates to `workspace_state.json` are written with timestamps and agent-lineage labels, providing an audit log of who changed what value and when.
- **Golden Evaluator Baseline**: Run [test_extractor_orchestrator.py](file:///f:/AIML%20projects/financial-analyst-cli/tests/test_extractor_orchestrator.py) to guarantee that extracted values match evaluations of the golden datasets.

## 5. Concurrency, Execution Gates & Fault-Tolerance Specification

To support parallel agent execution via `asyncio` while ensuring data consistency and smooth developer interaction, the Orchestrator implements the following specification:

### 1. Blocking Gates & Execution Modes

There are four distinct execution modes:

- **a. Full Pipeline Run**:
  - Enforces the following exact execution and dependency order:
    1. **Setup Phase (Sequential)**:
       - `metadata_agent` runs once across all parsed documents to extract company name, description, fiscal dates, currencies, and conversion rates, populating the root `WorkspaceContext.metadata`. This acts as a blocking gate prerequisite; no other agents can be spawned if the metadata has not been successfully populated.
    2. **Extraction Phase (Parallel)**:
       - `balance_sheet`, `income_statement`, `analyst_report`, and `other_doc` execute in parallel across fanned-in documents.
    3. **Metrics Phase**:
       - **Level 1 (Parallel)**: `diluted_shares`, `organic_growth`, and `interpretation` execute in parallel.
       - **Level 2 (Sequential)**: `operating_ebita` runs sequentially (depends on `interpretation` output).
       - **Level 3 (Sequential)**: `adjusted_taxes` runs sequentially (depends on `operating_ebita` output).
    4. **Modeling Phase**:
       - **Level 1 (Parallel)**: `wacc`, `growth`, `margin`, and `non_operating` execute in parallel.
       - **Level 2 (Sequential)**: `dcf_modeling_agent` runs last (depends on all Level 1 modeling outputs).
- **b. Specific Phase Run**:
  - Runs a specific phase (e.g. `extraction`) in single or batch mode across tickers.
  - No blocking gates exist within the run, but the orchestrator validates prerequisite states (e.g. company metadata must be completed, and parsed files must exist for extraction).
- **c. Specific Agent Run**:
  - Runs a single target agent (e.g. `balance_sheet`) in single or batch mode.
  - No gates exist, but prerequisite states are checked first.
- **Prerequisite Enforcement**:
  - If any prerequisite checks fail, the run immediately terminates before initiating any LLM API calls, preventing unnecessary cost or state pollution.

### 2. Concurrency Configuration & Parallelism

To optimize execution throughput while managing LLM rate limits:

- **Company Independence**: Companies are processed by separate orchestrator instances and run concurrently without cross-ticker blockages.
- **Document Independence**: Within a ticker's extraction and metrics phases, separate documents (quarterly, annual, announcements) execute concurrently.
- **Concurrency Knobs**: The orchestrator supports configurable concurrency limits (via environment variables or command-line flags) at three levels:
  - By Company (number of concurrent tickers)
  - By Document (number of concurrent documents per ticker)
  - By Phase (number of concurrent sub-agents running within a phase)

### 3. Asynchronous Failure and Reconciliation Queue (Fix E)

When a concurrently running sub-agent fails (e.g. API error) or a quality validation fails post-LLM extraction:

- **Failure Queue**: Failed tasks are pushed into a sequential **Prompt Failure Queue**.
- **Headless / Non-Interactive Mode (`--non-interactive` flag)**:
  - The CLI execution does not block or query stdin.
  - The Orchestrator automatically retries the failed task up to a configurable retry limit (e.g. 3 times) to handle transient network/API issues. For validation or quality checks reporting failures, it does not retry (it bypasses retries), immediately marks the task state as `failed` on the Blackboard, skips downstream tasks dependent on that value, and exits with a non-zero status code.
- **Interactive User Mode (Default CLI)**:
  - The queue processes failures sequentially, prompting the user on the CLI with three options:
    1. **Retry**: Re-run the failed agent task (useful for transient API errors or tweaking feedback).
    2. **Don't Retry**: Continue the pipeline run, keeping the failed flag on the blackboard and bypassing downstream steps dependent on this value.
    3. **Stop All Agents**: Immediately terminate all running and queued tasks in the orchestrator, cancelling pending `asyncio` futures.

---

## 6. CLI Command & Option Modifications

Transitioning from a rigid linear pipeline to a state-driven Blackboard model changes several CLI commands and options in the `fa` command suite:

### 1. New Global Options for `fa run`

All pipeline commands (`fa run extract`, `fa run analyze`, `fa run model`, `fa run curate_wiki`) support the following new options:

- `--non-interactive` / `-n`: Disables all stdin blocking prompts. Safe for headless environments, CI/CD, and cron runs. It enables up to 3 automatic retries on LLM/API errors, bypasses retries for validation errors, and aborts with exit code `1` on validation failures.
- `--agent <agent_name>` / `-a <agent_name>`: Bypasses the full stage pipeline and executes a single targeted sub-agent directly (e.g., `fa run extract --agent balance_sheet`), checking its prerequisite inputs on the blackboard first.

### 2. Streamlined Folder Setup (`fa use <ticker>` and `fa config init`)

- Initializing a workspace now creates only **4 subdirectories** instead of 7:
  - `1_ingest_data/`
  - `2_parsed_data/`
  - `3_archived_data/`
  - `9_scenario_model_json/` (renamed from `7_historical_model_json/`)
- _Note: Subdirectories `4_extracted_data/`, `5_historical_analysis/`, and `6_financial_model/` are deprecated as their contents are consolidated into `workspace_state.json`._

### 3. Consolidated Execution behavior of `fa run` Commands

- **`fa run extract`**: Reads `workspace_state.json`. Identifies pending/failed extraction or metric tasks for fanned-in documents. Spawns only the corresponding specialist sub-agents concurrently, writes structured outputs directly to `workspace_state.json`, and triggers quality validations.
- **`fa run analyze`**: Updates longitudinal yearly/quarterly financial tables directly inside `workspace_state.json` instead of writing flat files to a historical folder.
- **`fa run model`**: Spawns modeling agents (WACC, Growth, Margin, Non-Operating) to write valuation assumptions directly into `workspace_state.json` and runs the fallback or Rust DCF engine.
- **`fa run curate_wiki`**: Invokes the `CuratorAgent` to digest fanned-in data, historical trends, and model outputs from the Blackboard, writing/curating the robust qualitative views (Bull & Bear perspectives) in `[TICKER]_wiki.md`. This is run explicitly after modeling has finalized, preventing high LLM token costs during assumption tweaks/model iterations.

### 4. Simplified Query Commands (`fa query`)

- **`fa query summary` / `assessment` / `valuation`**: These read their structured data directly from the root `workspace_state.json` file, drastically improving query latency compared to parsing legacy markdown files.
- **`fa query trace`**: Deprecated or simplified. Because individual item `AuditLinkage` tracking is removed, this command will query and display the source report, calculation statuses, and execution timestamps from the blackboard rather than exact chunk snippets or text offsets.
