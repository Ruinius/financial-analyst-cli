# LiteLLM Architectural Refactor & Migration Plan

This document outlines the evaluation, refactoring principles, API key management architecture, code impact analysis, and step-by-step plan for performing a complete, zero-bloat migration of the `financial-analyst-cli` LLM service layer to **LiteLLM**.

---

## 1. Executive Summary & Strategy

The application is transitioning entirely to LiteLLM as the standard LLM integration layer. All legacy provider-specific wrapper modules (`gemini_client.py`, `deepseek_client.py`, `openrouter_client.py`) and complex fallback mechanisms will be completely purged to ensure a lean, best-practice architecture without code bloat.

---

## 2. Core Refactoring Principles

1. **Full LiteLLM Standardization**: All LLM interactions (generation, structured Pydantic extraction, streaming, and tool calling) will route exclusively through LiteLLM's standard completion interfaces (`litellm.completion` / `litellm.acompletion`).
2. **Zero Code Bloat & No Fallbacks**: No legacy fallback branches, dual-engine feature flags, or backwards-compatibility shims will be retained.
3. **Complete Legacy Deletion**: Dedicated client files for individual providers will be deleted from `src/services/`.

---

## 3. API Key Management Architecture

LiteLLM provides flexible API key management. For `financial-analyst-cli`, we utilize **Explicit Parameter Passing (`api_key=...`)** integrated with our Pydantic configuration model (`src/core/config.py`).

### Key Resolution Mechanics:
- **CLI Configuration (Primary)**: `LiteLLMClient` will resolve credentials from `Settings` (`settings.gemini_api_key`, `settings.openrouter_api_key`, `settings.deepseek_api_key`, or `settings.primary_llm_api_key`) and explicitly pass `api_key=...` into `litellm.completion()`.
- **Automatic Environment Fallback**: If an explicit key is omitted, LiteLLM automatically inspects standard environment variables (`GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`) based on the target model string prefix (`gemini/...`, `deepseek/...`, `openrouter/...`).

---

## 4. Code Impact Analysis: What Code is Replaced

### 4.1. Core Service Layer (`src/services/llm_client.py`) *(~80% Replaced)*
- **`OpenAICompatibleClient` Purged**: Hand-written `httpx` HTTP streaming sessions, SSE chunk parsing (`data: [DONE]`), manual thinking token extraction (`reasoning_content`), and manual retry loops are completely replaced by `litellm.completion(..., stream=True)`.
- **`SimulatedChatSession` Purged**: Manual string formatting that injects tool descriptions into system prompts and forces models to reply with custom JSON strings is replaced by passing standard Python tools directly into LiteLLM (`tools=[...]`).
- **`generate_structured()` Simplified**: Manual JSON schema string formatting and regex extraction (`extract_json_from_text`) is replaced by LiteLLM's native structured outputs (`response_format=response_schema`).
- **Provider Subclasses Deleted**: Provider-specific SDK logic in external files (`gemini_client.py`, `deepseek_client.py`, `openrouter_client.py`) is deleted entirely.

### 4.2. Agent Executor Layer (`src/agents/agent_executor.py`) *(~25% Simplified)*
While `agent_executor.py` retains core financial domain logic (turn budgets, turn metrics, executing local Python tool callables), LiteLLM allows us to purge several redundant branches:
- **Removal of Provider-Specific Hacks (Lines 63-75)**: Eliminates special checks like `getattr(chat, "finalized", False)` that were added specifically to handle Gemini's unique SDK behavior versus simulated sessions.
- **Elimination of String Tool Parsing Fallbacks (Lines 153-175)**: Removes manual JSON regex parsing (`extract_json_from_text`) on assistant plain text responses. Because LiteLLM standardizes function calling across Gemini, DeepSeek, and OpenRouter, tool calls arrive reliably as structured tool objects.

---

## 5. Step-by-Step Refactoring Plan

### Step 1: Dependency Management
- **Add LiteLLM**: Install `litellm` using `uv add litellm`.
- **Clean Unused SDKs**: Remove `google-genai` from `pyproject.toml` if not required by other modules.

### Step 2: Delete Legacy Provider Clients
Permanently delete the following provider-specific modules from `src/services/`:
- `[DELETE]` `src/services/gemini_client.py`
- `[DELETE]` `src/services/deepseek_client.py`
- `[DELETE]` `src/services/openrouter_client.py`

### Step 3: Refactor Core Service Layer (`src/services/llm_client.py`)
- **Purge Legacy Classes**: Remove `OpenAICompatibleClient`, `SimulatedChatSession`, and legacy provider imports.
- **Implement `LiteLLMClient(LLMClient)`**:
  - Map configuration settings (`settings.api_provider`, API keys, model names) to standard LiteLLM provider model identifiers (e.g., `gemini/gemini-3.1-flash-lite`, `deepseek/deepseek-v4-flash`, `openrouter/google/gemma-4-31b-it`).
  - Implement `.generate()` utilizing `litellm.completion(..., stream=True)` with Rich console streaming formatting.
  - Implement `.generate_structured()` utilizing LiteLLM's native Pydantic structured output validation (`response_format=response_schema`).
- **Implement `LiteLLMChatSession(ChatSession)`**:
  - Wrap LiteLLM native tool-calling capabilities (`tools=[...]`) to provide structured agentic interaction loops.
- **Simplify Factory**: Update `get_llm_client(provider, model)` to directly instantiate and return `LiteLLMClient`.

### Step 4: Clean Agent Execution Loops (`src/agents/agent_executor.py`)
- Remove provider-specific finalization checks (`getattr(chat, "finalized", False)`).
- Clean up redundant JSON string fallback parsing for tool calls to rely cleanly on LiteLLM tool structures.

### Step 5: Refactor Test Suite (`tests/services/test_llm_clients.py`)
- Remove unit test mocks targeting `httpx` endpoints and Google GenAI SDK objects.
- Mock `litellm.completion` to verify response parsing, structured extraction, and streaming logic under `LiteLLMClient`.

### Step 6: Sync Project Documentation & Architecture Maps
- **Update `AGENTS.md`**: Reflect the deletion of legacy provider files and document `llm_client.py` as the consolidated LiteLLM client layer under Project Structure.
- **Update `docs/architecture.md`**: Update directory layout diagrams and component flows to accurately represent LiteLLM integration.

---

## 6. Verification Plan

### Automated Tests
- Run unit tests: `uv run pytest tests/services/test_llm_clients.py`
- Run full test suite: `uv run pytest`

### Manual Verification
- Run a sample CLI command (`fa run` or `fa chat`) to confirm proper client initialization and LiteLLM model routing without errors.
