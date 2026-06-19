import logging
from src.tools.keyword_search import (
    find_keyword_contexts as orchestrator_find_keyword_contexts,
)
from src.agents.agent_executor import run_agent_loop

logger = logging.getLogger(__name__)


def run_diluted_shares_agent(
    content: str,
    extractor,
    income_statement_content: str = "",
    is_quarterly: bool = True,
) -> tuple[float, float]:
    from src.agents.extractor_orchestrator import clean_val

    # Load extraction learnings
    learning_context = extractor.get_extract_context()

    focus_period = (
        "fiscal quarter (three months)"
        if is_quarterly
        else "fiscal year (twelve months)"
    )
    sys_prompt = (
        "You are Sir Pennyworth, a precise financial analyst. Your goal is to find the exact basic and diluted shares outstanding in the document.\n"
        f"Specifically, we are focused on the {focus_period} time period. Ensure you find the shares outstanding corresponding to this focused period.\n"
        "Rules:\n"
        "1. You have a maximum of 4 turns. Search for keyword contexts first (hint: potential first keywords to search for include 'diluted', 'share', 'basic').\n"
        "2. When you find the values, call 'finalize' with the basic and diluted shares. You must express the values as float strings in millions of shares, formatted with two decimal places (e.g., '280.00' for 280 million shares, or '283.13' for 283,125,000 shares). Do not write 'million' or include commas in the values."
    )

    user_content = (
        "Start searching for basic and diluted shares outstanding. Remember, you have up to 4 turns. "
        "(Hint: try searching for keywords like 'diluted', 'share', or 'basic' first)."
    )
    if learning_context:
        user_content += f'\n\nHere is the active company extraction learning context to guide your extraction decision logic:\n"""\n{learning_context}\n"""'
    if income_statement_content:
        user_content += f'\n\nHere is the already extracted Income Statement for your reference:\n"""\n{income_statement_content}\n"""'

    # Define tools as inner functions
    def find_keyword_contexts(keywords: list, window: int = 200) -> str:
        """Search the document content for occurrences of keywords within a window of characters."""
        return str(orchestrator_find_keyword_contexts(content, keywords, window))

    def finalize(basic_shares: str, diluted_shares: str) -> str:
        """Finalize the shares extraction, specifying basic_shares and diluted_shares in millions."""
        return "Shares extraction finalized."

    tools = [find_keyword_contexts, finalize]

    finalized_args, history = run_agent_loop(
        client=extractor.llm,
        system_prompt=sys_prompt,
        initial_prompt=user_content,
        tools=tools,
        max_turns=4,
    )

    basic_shares = clean_val(str(finalized_args.get("basic_shares", "0")))
    diluted_shares = clean_val(str(finalized_args.get("diluted_shares", "0")))

    # After the loop finishes:
    try:
        from src.agents.curator_agent import CuratorAgent

        ticker = extractor.settings.active_ticker or "UNK"
        history_text = ""
        for h in history:
            history_text += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        curator = CuratorAgent(extractor.settings)
        curator.curate_agent(ticker, "diluted_shares", history_text)
    except Exception as e:
        logger.error(f"Failed to run curator for diluted_shares: {e}")

    return basic_shares, diluted_shares
