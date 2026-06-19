# Refactoring Design: Micro-Agent Architecture

This document specifies the target architecture, backlog, and plan for refactoring the Financial Analyst CLI from a rigid linear pipeline into a stateful, modular **Micro-Agent Architecture**.

## 1. Context & Motivation

The current architecture operates as a linear, hardcoded Python pipeline:
- **Linear Orchestration**: [extractor_orchestrator.py](file:///f:/AIML%20projects/financial-analyst-cli/src/pipeline/extractor_orchestrator.py) relies on static conditional statements (`if is_financial: ... elif is_analyst: ...`) to coordinate extraction.
- **Verbose Loop Boilerplate**: Sub-agents like [income_statement_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/pipeline/extractor_agents/extractor_financials_agents/income_statement_agent.py) run manual `for` loops inside Python, parsing raw text responses for JSON commands, appending to lists, and managing state transitions.
- **Context Pollution**: Large files force agents to query multiple contexts without isolation of state.

### Target Vision: Focus on Autonomous Pipeline & LLMWiki Generation

Our immediate refactoring focus is strictly on the **Autonomous Pipeline Mode**.

By automating document scanning, extraction, and modeling, the pipeline will continually populate and refine the **LLMWiki**—a comprehensive local Markdown database consisting of:
- `[TICKER]_wiki.md`: Curated, clean qualitative views (Bull & Bear perspectives).
- `[TICKER]_extract_learning.md` / `_analyze_learning.md` / `_model_learning.md`: Structured historical audit logs and lessons.
- `4_extracted_data/` and other output directories: Well-structured markdown tables containing standardized, extracted line items and calculated metrics.

This rich markdown foundation serves as the database that the **Interactive Chat Mode** will query down the road to answer multi-company questions.

---

## 2. Proposed Architecture

```mermaid
graph TD
    %% Trigger & Scanner
    TimeTrigger([Cron / Time Trigger]) --> AutoPipeline[Autonomous Input Scanner]
    FileDump([File dumped in 1_input_data/]) --> AutoPipeline
    AutoPipeline --> Supervisor[Supervisor / Orchestrator Agent]

    %% The Blackboard State
    subgraph Blackboard (Shared Workspace Context)
        WorkspaceDB[(Workspace JSON Database)]
        StatusFlags[Task Completion & Validation State]
        ExtractedValues[Extracted Financials & Metrics]
    end

    %% Supervisor Loop
    Supervisor <-->|1. Read Status / 3. Update Flags| StatusFlags

    %% Parallel Micro-Agents
    subgraph Specialist Micro-Agents (Tools)
        IS[Income Statement Agent]
        BS[Balance Sheet Agent]
        OG[Organic Growth Agent]
        Tax[Tax Agent]
        Wacc[WACC Modeler Agent]
    end

    %% Blackboard Handoffs
    Supervisor -->|Invoke Tool| IS
    Supervisor -->|Invoke Tool| BS
    Supervisor -->|Invoke Tool| OG
    Supervisor -->|Invoke Tool| Tax
    Supervisor -->|Invoke Tool| Wacc

    IS -->|Write Raw Items| ExtractedValues
    BS -->|Write Raw Items| ExtractedValues
    OG -->|Write Rates| ExtractedValues
    Tax -->|Write Tax Details| ExtractedValues
    Wacc -->|Write Cost of Capital| ExtractedValues

    %% Output Compilation (LLMWiki)
    Supervisor -->|4. Finalize / Curate| TickerWiki[[LLMWiki: TICKER_wiki.md, etc.]]
```

### Components

#### 1. The Blackboard Schema (`WorkspaceContext`)
The Blackboard acts as a structured domain model for a single target company workspace.
- **Specification**: Detailed Pydantic schemas, state transitions, validation rules, and local storage formats are defined in the dedicated design document: [blackboard_design.md](file:///f:/AIML%20projects/financial-analyst-cli/docs/blackboard_design.md).
- **Core Entities**:
  - `GlobalMetadata`: Tracks company-wide config constants (reporting currency, default unit).
  - `FinancialModel`: Tracks valuation parameters (WACC Cost of Capital, margins, DCF assumptions).
  - `TemporalReport`: Tracks period-specific statement items and status flags (e.g. `balance_sheet_status = "completed"`).

#### 2. Supervisor Orchestrator Agent (`src/pipeline/supervisor_orchestrator.py`)
- Coordinates the pipeline dynamically based on the Blackboard state.
- **Decision Loop**:
  1. Read `workspace_state.json`.
  2. If tasks in a `TemporalReport` are `pending` or `failed`, spawn the matching micro-agents (in parallel if possible).
  3. Once sub-agents complete, write outputs to the Blackboard and mark tasks `completed`.
  4. Run validation checks. If validation fails (e.g., balance sheet mismatch), set `arithmetic_errors` and trigger the sub-agent again with error details (reconciliation loop).
  5. Once all flags are `completed` and validation passes, compile the final report, compute deterministic DCF models, and update **LLMWiki**.

#### 3. Micro-Agents (`src/pipeline/extractor_agents/` & `src/pipeline/modeler_agents/`)
- Pure-functional inputs/outputs: consumes specific portions of the document and outputs a structured Pydantic schema matching its specialist task.
- Zero awareness of downstream agents—they only know their immediate input and the target Blackboard structure they must write to.

---

## 3. Implementation Roadmap

### Phase 1: Client Provider Separation (Foundation)
- Refactor [llm_client.py](file:///f:/AIML%20projects/financial-analyst-cli/src/services/llm_client.py) to split generic provider logic into dedicated, isolated clients:
  - `src/services/gemini_client.py`: Uses official `google-genai` SDK, native structured outputs, and automatic function calling.
  - `src/services/deepseek_client.py`: Tailors reasoning token parameters and handles thoughts.
  - `src/services/openrouter_client.py`: Standardizes routing and specific headers.

### Phase 2: Blackboard State & Pydantic Micro-Agents
- Define the `WorkspaceContext` (Blackboard) schema and write state load/save utilities under `src/core/blackboard.py`.
- Refactor [income_statement_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/pipeline/extractor_agents/extractor_financials_agents/income_statement_agent.py), [balance_sheet_agent.py](file:///f:/AIML%20projects/financial-analyst-cli/src/pipeline/extractor_agents/extractor_financials_agents/balance_sheet_agent.py), etc.
- Standardize these micro-agents as callable Python functions with clear Pydantic schemas mapping directly to the Blackboard state.
- Use Gemini's **Structured Outputs** (`response_schema`) to bypass verbose prompt-based JSON schemas.

### Phase 3: Agentic Supervisor Decision Loop (Autonomous Focus)
- Create the `SupervisorAgent` in `src/pipeline/supervisor_orchestrator.py`.
- Connect the Supervisor's prompt logic to check status flags on the Blackboard and execute micro-agents sequentially or concurrently.
- Replace the legacy control flow in [extractor_orchestrator.py](file:///f:/AIML%20projects/financial-analyst-cli/src/pipeline/extractor_orchestrator.py).

### Phase 4: Interactive Chat & Multi-Company Analytics (Deferred)
- Create the `CrossCompanyChatAgent` CLI commands under `src/cli/commands/chat.py`.
- Give the Chat Agent tool access to query/search the accumulated LLMWiki files and the Blackboard historical databases.

---

## 4. Verification and Testing

- **Modular Test Harnesses**: Write tests verifying each micro-agent independently (e.g., passing a simulated parsed page and verifying the exact structure of the Pydantic response).
- **Blackboard State Tracing**: Ensure that state updates to `workspace_state.json` are written with timestamps and agent-lineage labels, providing an audit log of who changed what value and when.
- **Golden Evaluator Baseline**: Run [test_extractor_orchestrator.py](file:///f:/AIML%20projects/financial-analyst-cli/tests/test_extractor_orchestrator.py) to guarantee that extracted values match evaluations of the golden datasets.
