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

*Note: Subdirectories `4_extracted_data/`, `5_historical_analysis/`, and `6_financial_model/` are deprecated as their contents are now consolidated into the blackboard state.*

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
- **Asynchronous Concurrency**: Runs independent sub-agents (e.g., `BalanceSheetAgent` and `IncomeStatementAgent`) concurrently within a stage using Python's `asyncio` (`asyncio.gather`), maintaining status flags to avoid duplicate or colliding work.
- **Sequential Execution Stages:** Organizes execution into sequential stages: `ingest` -> `extract` -> `analyze` -> `model`. The CLI/API supports running these stages individually (e.g., executing only the `extract` stage) or triggering a unified, end-to-end `full-run` of the entire pipeline.
- **Decision & Coordination Loop**:
  1. Read the `workspace_state.json` file.
  2. Evaluate which components are `pending` or `failed` for the targeted stage.
  3. Dynamically spawn the matching specialist sub-agent templates (not locked to a rigid sequential pipeline within a stage).
  4. Coordinate checkout (status set to `running`) and check-in (status set to `completed` or `failed`) locking to ensure no duplicate work.
  5. Run validation checks. If validation fails, prompt the user on the CLI to choose whether to proceed or retry. If retrying, update `arithmetic_errors` and spawn sub-agent templates again with specific error contexts.
  6. Call the `LearningAgent` based on the discretionary trigger criteria (if the task took significantly more or fewer turns than the historical average to succeed).
  7. Once all status flags are `completed` and validation checks pass, finalize calculations, build DCF models, and coordinate writing/curating summaries.

#### 3. Specialist Sub-Agent Templates (`src/agents/extractor_agents/` & `src/agents/modeler_agents/`)

- Standardized, reusable agent templates that are spawned on-demand by the Orchestrator.
- Purely functional behavior: they consume isolated input contexts (like parsed chunks or in-memory blackboard slices passed to them as arguments by the Orchestrator) and return structured Pydantic schemas directly back to the Orchestrator (which handles serialization and disk persistence).
- **High Modularization & Standalone Invocation:** Any sub-agent can be invoked independently as a standalone function/component without depending on or spinning up the entire orchestration pipeline.
- **Graceful Dependency Verification:** If a sub-agent depends on previous data (e.g. `WaccAgent` depending on the latest Balance Sheet, or `OrganicGrowthAgent` depending on prior period revenues), the agent checks for the existence of this data on the blackboard (using the read-only `query_blackboard` tool). If the dependencies do not exist, the agent logs/returns a structured dependency error back to the caller instead of crashing.
- **Turn Limits:** Sub-agents are restricted to strict limits:
  - `BalanceSheetAgent` and `IncomeStatementAgent`: Granted up to **20 turns**.
  - All other specialist sub-agents: Granted up to **10 turns**.
- **Progressive Turn Cost Mechanism & Benchmarking:** A dynamic warning is prepended to the prompt at each turn of the sub-agent, informing it of the current turn count, remaining turns, and historical benchmarks (`last_turn_count`, `average_turn_count`). It warns the agent that each subsequent turn is progressively more expensive to encourage early termination and optimal performance.
- Any sub-agent can write into its own small piece of the blackboard which it checks out first to avoid write collisions. This checkout / check-in logic is handled via a deterministic script/locking helper when the agent starts and finalizes, enabling parallel concurrency and preventing context contamination.
- No direct file I/O: sub-agents do not read or write blackboard/extracted files from or to disk.
- Completely decoupled and pipeline-agnostic: sub-agents have zero awareness of other sub-agents or downstream dependencies.

#### 4. Curation & Learning Sub-Agents (`src/agents/curator_agent.py` & `src/agents/learning_agent.py`)

- **`CuratorAgent`**: A dedicated sub-agent solely responsible for writing and updating the robustly written `[TICKER]_wiki.md` qualitative summary file using all the info compiled on the blackboard. To prevent collisions, there is a check-in / check-out lock mechanism for the wiki. The curator is run either explicitly via CLI or automatically at most weekly.
- **`LearningAgent`**: A dedicated sub-agent responsible for capturing, formatting, and updating run-to-run learnings and feedback lessons directly into the Pydantic Blackboard state (`workspace_state.json`) under the `company_data.learnings` schemas, keeping track of successful search queries, anomalous items, and historical configurations. It runs dynamically based on a sub-agent taking significantly more or fewer turns than the historical average to succeed.
- **Execution Performance Tracking:** The `LearningAgent` (and the checkout helper) is responsible for recording and updating run metrics inside the blackboard for each specific sub-agent type and document type for this company:
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

### Tool Assignment Matrix

| Specialist Sub-Agent Template | Category   | Permitted Tools / Services                                    | Rationale                                                                                  |
| :---------------------------- | :--------- | :------------------------------------------------------------ | :----------------------------------------------------------------------------------------- |
| **`BalanceSheetAgent`**       | Extraction | `find_chunk`, `keyword_search`                                | Scans raw filings to extract assets, liabilities, and equity tables to return to the Orchestrator. |
| **`IncomeStatementAgent`**    | Extraction | `find_chunk`, `keyword_search`                                | Scans raw filings to extract revenue, expenses, and income tables to return to the Orchestrator. |
| **`AnalystReportAgent`**      | Extraction | `find_chunk`, `keyword_search`                                | Scans broker reports to extract moats, margins, and growth views.                          |
| **`OtherDocAgent`**           | Extraction | `find_chunk`, `keyword_search`                                | Scans transcripts, press releases, and other general filings to generate qualitative summaries. |
| **`DilutedSharesAgent`**      | Metrics    | `find_chunk`, `keyword_search`, `query_blackboard`            | Searches share counts tables, footnotes, and conversions in filings; cross-checks shares outstanding. |
| **`OrganicGrowthAgent`**      | Metrics    | `find_chunk`, `keyword_search`, `query_blackboard`            | Searches constant currency and M&A impact disclosures; retrieves prior period revenues.     |
| **`OperatingEbitaAgent`**     | Metrics    | `find_chunk`, `keyword_search`, `access_resources`, `web_search`, `query_blackboard` | Audits non-recurring adjustments; reference to static dictionaries; verifies reported operating income. |
| **`AdjustedTaxesAgent`**      | Metrics    | `find_chunk`, `keyword_search`, `query_blackboard`            | Scans tax rate reconciliation tables and footnotes; retrieves operating income and EBITA adjustments. |
| **`InterpretationAgent`**     | Metrics    | `access_resources`, `web_search`, `query_blackboard`          | Resolves ambiguous/generic lines against dictionaries; performs cross-statement validation checks. |
| **`WaccAgent`**               | Modeling   | `market_data`, `web_search`, `query_blackboard`               | Fetches stock details and computes WACC parameters; queries latest reports for debt/cash details. |
| **`GrowthAgent`**             | Modeling   | `web_search`, `query_blackboard`                              | Formulates growth projections; retrieves historical revenues and margins.                   |
| **`MarginAgent`**             | Modeling   | `web_search`, `query_blackboard`                              | Formulates margin targets; retrieves historical margins and analyst views.                  |
| **`NonOperatingAgent`**       | Modeling   | `query_blackboard`                                            | Queries/extracts the 6 non-operating categories from the latest fanned-in balance sheet state. |
| **`DcfModelingAgent`**        | Modeling   | `query_blackboard`                                            | Sanity-checks and critiques the completed valuation parameters and assumptions.            |
| **`CuratorAgent`**            | Curation   | `query_blackboard`                                            | Solely responsible for writing and updating the `[TICKER]_wiki.md` file.                    |
| **`LearningAgent`**           | Learning   | `query_blackboard`                                            | Responsible for writing and maintaining the run learnings and feedback logs into the blackboard. |

---

## 4. Implementation Roadmap

### Phase 1: Client Provider Separation (Foundation)

- Refactor [llm_client.py](file:///f:/AIML%20projects/financial-analyst-cli/src/services/llm_client.py) to split generic provider logic into dedicated, isolated clients:
  - `src/services/gemini_client.py`: Uses official `google-genai` SDK, native structured outputs, and automatic function calling.
  - `src/services/deepseek_client.py`: Tailors reasoning token parameters and handles thoughts.
  - `src/services/openrouter_client.py`: Standardizes routing and specific headers.

### Phase 2: Blackboard State & Pydantic Micro-Agents

- Define the `WorkspaceContext` (Blackboard) schema and write state load/save utilities under `src/core/blackboard.py`.
- Refactor [income_statement_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_financials_agents/income_statement_agent.py), [balance_sheet_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/agents/extractor_agents/extractor_financials_agents/balance_sheet_agent.py), etc.
- Standardize these micro-agents as callable Python functions with clear Pydantic schemas mapping directly to the Blackboard state.
- Use Gemini's **Structured Outputs** (`response_schema`) to bypass verbose prompt-based JSON schemas.

### Phase 3: Blackboard Orchestrator Integration

- Create the unified `BlackboardOrchestrator` in `src/agents/blackboard_orchestrator.py`.
- **Consolidation Target:** Replace, consolidate, and delete the redundant coordination loops currently residing in:
  - `src/agents/extractor_orchestrator.py` (legacy extraction pipeline)
  - `src/agents/extractor_agents/extractor_financials.py` (legacy financials coordination)
  - `src/agents/analyzer.py` (legacy trend reports and files compilation)
  - `src/agents/modeler_orchestrator.py` (legacy DCF pipeline)
- Implement the consolidated transition loop:
  - Audits the blackboard, executes programmatic validation checks, handles checkout/check-in locking, manages concurrency, and coordinates Wacc/DCF/Curation/Learning runs.

### Phase 4: Interactive Chat & Multi-Company Analytics (Deferred)

- Create the `CrossCompanyChatAgent` CLI commands under `src/cli/commands/chat.py`.
- **Decoupled Chat Reasoning:** Decouple Chat reasoning from pipeline execution. The Chat Agent runs in its own session and is given access to high-level query tools: `read_blackboard(ticker, period)`, `search_wiki(query)`, and a macro-tool `trigger_pipeline_run(ticker)` which programmatically invokes the Deterministic Orchestrator if data is missing or stale.
- The Chat Agent does not spawn individual micro-agents directly, keeping chat latency low and tool routing predictable.

---

## 5. Verification and Testing

- **Modular Test Harnesses**: Write tests verifying each micro-agent independently (e.g., passing a simulated parsed page and verifying the exact structure of the Pydantic response).
- **Blackboard State Tracing**: Ensure that state updates to `workspace_state.json` are written with timestamps and agent-lineage labels, providing an audit log of who changed what value and when.
- **Golden Evaluator Baseline**: Run [test_extractor_orchestrator.py](file:///f:/AIML%20projects/financial-analyst-cli/tests/test_extractor_orchestrator.py) to guarantee that extracted values match evaluations of the golden datasets.
