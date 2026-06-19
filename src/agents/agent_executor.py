import logging
import json
from typing import List, Callable, Dict, Any
from types import SimpleNamespace
from src.core.exceptions import LLMError
from src.services.llm_client import ChatSession, LLMClient

logger = logging.getLogger(__name__)


def run_agent_loop(
    client: LLMClient,
    system_prompt: str,
    initial_prompt: str,
    tools: List[Callable],
    max_turns: int = 10,
    model: str = None,
    temperature: float = 0.1,
) -> tuple[Dict[str, Any], list]:
    """
    Executes a structured turn-based agent execution loop.
    Supports both native tool use / function calling (via GeminiChatSession)
    and simulated tool use (via SimulatedChatSession).

    Returns:
      (finalize_arguments: dict, chat_history: list)
    """
    chat: ChatSession = client.create_chat(
        system_prompt=system_prompt,
        tools=tools,
        model=model,
        temperature=temperature,
    )

    # Dictionary to map function name to callable function
    tool_map = {t.__name__: t for t in tools}

    response = chat.send_message(initial_prompt)

    finalized_args = None
    finalized = False

    for turn in range(max_turns):
        # If we are on the last turn and not finalized, send a warning
        if turn == max_turns - 1 and not finalized:
            warning = (
                f"\n\nCRITICAL: This is your final turn (turn {max_turns} of {max_turns}). "
                "You must call the 'finalize' tool immediately with your current best estimates."
            )
            response = chat.send_message(warning)

        # 1. Process Tool Invocations
        if isinstance(
            response, list
        ):  # List of tool call requests (namespaces or FunctionCalls)
            tool_responses = []
            for call in response:
                name = getattr(call, "name", None)
                # Arguments could be a dict or a structure (e.g. Map-like for native calls)
                args = getattr(call, "args", {})
                if not isinstance(args, dict):
                    try:
                        args = dict(args)
                    except Exception:
                        args = {}

                logger.info(f"Agent executing tool: {name} with args: {args}")

                if name == "finalize":
                    finalized_args = args
                    finalized = True
                    # Still run the local finalize function if registered to perform cleanup/updates
                    if name in tool_map:
                        try:
                            tool_map[name](**args)
                        except Exception as e:
                            logger.error(f"Error in finalize tool call execution: {e}")
                    break

                if name in tool_map:
                    try:
                        # Call the tool function with its unpacked arguments
                        result = tool_map[name](**args)
                        tool_responses.append({"name": name, "content": str(result)})
                    except Exception as e:
                        logger.error(f"Error executing tool '{name}': {e}")
                        tool_responses.append({"name": name, "content": f"Error: {e}"})
                else:
                    tool_responses.append(
                        {"name": name, "content": f"Error: Unknown tool '{name}'."}
                    )

            if finalized:
                break

            # Send tool execution results back to the chat session
            response = chat.send_message("", tool_responses=tool_responses)

        # 2. Process Plain Text Responses (non-tool calls)
        else:
            # Check if the text contains a manual tool call string representation (fallback parsing helper)
            from src.utils.tools import extract_json_from_text

            json_str = extract_json_from_text(response)
            if json_str:
                try:
                    action = json.loads(json_str)
                    tool_name = action.get("tool")
                    tool_args = action.get("arguments", {})
                    if tool_name == "finalize":
                        finalized_args = tool_args
                        finalized = True
                        if tool_name in tool_map:
                            tool_map[tool_name](**tool_args)
                        break

                    # Convert this to simple namespace and loop again to process it
                    call = SimpleNamespace(name=tool_name, args=tool_args)
                    response = [call]
                    continue
                except Exception:
                    pass

            if finalized:
                break

            # If it returned text but did not call finalize, prompt it to use tools
            prompt_instruction = (
                "Your response did not execute a tool or call 'finalize'. "
                "Please call one of the available tools or call 'finalize' if you are ready."
            )
            response = chat.send_message(prompt_instruction)

    if not finalized:
        raise LLMError(
            f"Agent failed to finalize execution within the limit of {max_turns} turns."
        )

    return finalized_args, chat.get_history()
