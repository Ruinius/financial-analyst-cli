# Refactoring Ideas

- Need to ask Gemini to map out the current full pipeline, and which agent runs what and outputs what in detail. This should be part of the docs.

- Consider refactor everything into micro-agents. Start the micro-agents architecture, so the main chat function can call any agent as a tool.

## Planned Refactor: Deconstruct LLM Client into Dedicated Provider Clients

To maximize maintainability and allow each model to run in its most optimized mode, we plan to refactor `src/services/llm_client.py` and extract provider-specific logic into standalone client implementations.

### Target Architecture

1. **`src/services/llm_client.py` (Base & Factory)**:
   - Contains common interface definitions and/or a factory method to instantiate the correct client based on active settings.
2. **`src/services/gemini_client.py`**:
   - Uses the native Google API or official SDK (`google-genai`) instead of the OpenAI compatibility layer.
   - Leverages native `system_instruction` parameter mapping.
   - Utilizes native structured outputs (`response_schema`) for Pydantic schemas, eliminating regular expression parsing for JSON.
   - Tailors streaming loops to use Google's native candidate structures.

3. **`src/services/deepseek_client.py`**:
   - Implements native reasoning token parsing (`reasoning_content`) and displays thoughts in an `italic dim` format.
   - Encapsulates DeepSeek's custom thinking parameter logic (`"thinking": {"type": "enabled"}`).

4. **`src/services/openrouter_client.py`**:
   - Configures specific HTTP headers (`HTTP-Referer`, `X-Title`) required by the OpenRouter API.
   - Handles multi-model routing and reasoning configurations.

### Key Maintainability Benefits

- **Zero Side Effects**: Modifying Gemini API version or parameters will not impact DeepSeek or OpenRouter code paths.
- **Isolated Testing**: Standard client unit tests can be written and run in modular fashion per client.
- **Direct Parameter Alignment**: Eliminates "leaky abstractions" where unsupported parameters (like thinking toggles) are passed to incompatible APIs.
- **Clean Error Handling**: Provider-specific rate limit codes and exceptions are handled in their own dedicated boundaries.
