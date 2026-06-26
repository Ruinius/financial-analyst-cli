import logging
import json
import contextvars
from typing import List, Callable, Dict, Any
from types import SimpleNamespace
from src.core.exceptions import LLMError
from src.services.llm_client import ChatSession, LLMClient

logger = logging.getLogger(__name__)

# Context variable to store execution metrics of the most recent agent execution loop run.
# Stores a tuple of: (turn_count, run_logs)
last_agent_run = contextvars.ContextVar("last_agent_run", default=None)


def run_agent_loop(
    client: LLMClient,
    system_prompt: str,
    initial_prompt: str,
    tools: List[Callable],
    max_turns: int = 10,
    model: str = None,
    temperature: float = 0.1,
    average_turn_count: float = None,
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

    def get_turn_warning(turn_num: int) -> str:
        remaining = max_turns - turn_num + 1
        parts = [
            f"Turn {turn_num} of {max_turns}",
            f"Remaining turn allowance: {remaining}",
        ]
        if average_turn_count is not None:
            parts.append(
                f"Historical average runs for this task: {average_turn_count:.1f} turns"
            )
        return f"\n\n[Turn Progress: {' | '.join(parts)}]"

    # Start Turn 1
    initial_prompt_with_warning = initial_prompt
    if max_turns > 0:
        initial_prompt_with_warning += get_turn_warning(1)

    response = chat.send_message(initial_prompt_with_warning)

    # Check for native AFC finalization (e.g. Gemini)
    if getattr(chat, "finalized", False) is True:
        history = chat.get_history()
        turn_count = sum(1 for msg in history if msg.get("role") == "assistant")
        lines = []
        for msg in history:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        run_logs = "\n\n".join(lines)
        last_agent_run.set((turn_count, run_logs))
        return chat.finalized_args, history

    finalized_args = None
    finalized = False

    for turn in range(max_turns):
        if getattr(chat, "finalized", False) is True:
            finalized_args = chat.finalized_args
            finalized = True
            break

        # If we are on the last turn and not finalized, send a warning
        if turn == max_turns - 1 and not finalized:
            warning = (
                f"\n\nCRITICAL: This is your final turn (turn {max_turns} of {max_turns}). "
                "You must call the 'finalize' tool immediately with your current best estimates."
            )
            if average_turn_count is not None:
                warning += (
                    f" Historical average runtime: {average_turn_count:.1f} turn(s)."
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
            next_turn_num = turn + 2
            if next_turn_num < max_turns:
                # Add warning to the last tool response so it is visible to the agent
                tool_responses[-1]["content"] = str(
                    tool_responses[-1]["content"]
                ) + get_turn_warning(next_turn_num)

            response = chat.send_message("", tool_responses=tool_responses)

        # 2. Process Plain Text Responses (non-tool calls)
        else:
            # Check if the text contains a manual tool call string representation (fallback parsing helper)
            from src.utils.markdown_helper import extract_json_from_text

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
            next_turn_num = turn + 2
            if next_turn_num < max_turns:
                prompt_instruction += get_turn_warning(next_turn_num)

            response = chat.send_message(prompt_instruction)

    # Final fallback check if finalization happened during loop exit
    if not finalized and getattr(chat, "finalized", False) is True:
        finalized_args = chat.finalized_args
        finalized = True

    # Capture execution metrics in context variable unconditionally before exiting
    history = chat.get_history()
    turn_count = sum(1 for msg in history if msg.get("role") == "assistant")
    lines = []
    for msg in history:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")
        lines.append(f"{role}: {content}")
    run_logs = "\n\n".join(lines)
    last_agent_run.set((turn_count, run_logs))

    if not finalized:
        raise LLMError(
            f"Agent failed to finalize execution within the limit of {max_turns} turns."
        )

    return finalized_args, history
