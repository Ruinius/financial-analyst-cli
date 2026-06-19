import logging
from src.tools.keyword_search import (
    find_keyword_contexts as orchestrator_find_keyword_contexts,
)
from src.tools.find_chunk import get_chunk_by_id as orchestrator_get_chunk
from src.agents.agent_executor import run_agent_loop

logger = logging.getLogger(__name__)


def run_ebita_agent(
    content: str,
    extractor,
    income_statement_content: str = "",
    is_quarterly: bool = True,
) -> tuple[float, float, list]:
    # Load extraction learnings
    learning_context = extractor.get_extract_context()

    # Check local dictionary classifications to pass as guidance/override
    local_dict_guidance = ""
    is_dict = extractor.get_dictionary("income_statement")
    if is_dict:
        local_dict_guidance += f"--- Income Statement Dictionary ---\n{is_dict}\n"

    focus_period = (
        "fiscal quarter (three months)"
        if is_quarterly
        else "fiscal year (twelve months)"
    )
    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst specializing in EBITA adjustments.\n"
        f"Your task is to identify and extract Operating Income directly from the income statement, "
        "identify non-operating/non-recurring operating adjustments (e.g. restructuring charges, asset impairments, "
        "amortization of acquired intangibles in opex) from the income statement and footnotes, and calculate clean Operating EBITA, "
        f"focusing specifically on the {focus_period} time period.\n\n"
        "Rules:\n"
        "1. You have a maximum of 4 turns. Search for keyword contexts and chunks first to locate the figures.\n"
        "2. Extract Operating Income from the income statement content. Note that if the income statement does not explicitly list it, you must attempt to calculate it starting with a proxy line item that would be close (such as pre-tax income / income before taxes).\n"
        "3. Identify any non-recurring operating adjustments (e.g. restructuring, asset impairments, amortization of acquired intangibles).\n"
        "4. Calculate clean Operating EBITA = Operating Income + EBITA adjustments.\n"
        "5. Standardize positive/negative signs for the calculations and outputs:\n"
        "   - EBITA adjustments are positive if they add back an opex expense (increasing EBITA), and negative if they subtract an operating gain (decreasing EBITA).\n"
        "   - Verify that any number that effectively increases profit is expressed as a positive number.\n"
        "   - Pay special attention to ambiguous items: make sure their sign correctly reflects whether they are a net expense (negative) or net income/benefit (positive).\n"
        "   - Ensure that EBITA and its components in the returned JSON have signs consistent with these rules.\n"
        "6. For adjustments or values not found on the face of the income statement (e.g., found in footnotes or chunk disclosures), you must be extremely careful to use the value corresponding to the three-month period (quarter) rather than the year-to-date (six-month or nine-month) period when the focus period is a quarter. If only a year-to-date value is provided, calculate the quarterly value by subtracting the prior periods' values if available.\n"
        "7. If any individual adjustment value represents a large percentage of EBITA (or Operating Income), you must double-check the text/footnotes to ensure it is the correct value for the focus period and not an incorrect, aggregate, or multi-period value.\n"
        "8. Identify the currency and unit from the extracted income statement content (provided below). Ensure all extracted Operating Income and adjustments are in this same currency and unit (do not convert to USD unless the income statement itself is in USD).\n\n"
        "Example finalize tool call:\n"
        "{\n"
        '  "thought": "I will finalize the extraction. Operating Income is 2000.0. Restructuring of 100.0 needs to be added back. So Operating EBITA is 2100.0.",\n'
        '  "tool": "finalize",\n'
        '  "arguments": {\n'
        '    "operating_income": 2000.0,\n'
        '    "operating_ebita": 2100.0,\n'
        '    "ebita_adjustments": [\n'
        '      {"name": "Restructuring", "value": 100.0}\n'
        "    ]\n"
        "  }\n"
        "}"
    )

    user_content = (
        "Start searching for Operating Income and EBITA adjustments. Remember, you have up to 4 turns.\n"
        "(hint: try searching for keywords like 'restructur', 'amort', 'impair', 'goodwill', 'conting', 'acquire', 'intangible'), "
    )
    if learning_context:
        user_content += f'\n\nHere is the active company extraction learning context to guide your extraction decision logic:\n"""\n{learning_context}\n"""'
    if income_statement_content:
        user_content += f'\n\nHere is the already extracted Income Statement for your reference:\n"""\n{income_statement_content}\n"""'

    if local_dict_guidance:
        user_content += f"\n\nLocal Dictionary Guidance:\n{local_dict_guidance}\n"

    # Define tools as inner functions
    def find_keyword_contexts(keywords: list, window: int = 250) -> str:
        """Search the document content for occurrences of keywords within a window of characters."""
        return str(orchestrator_find_keyword_contexts(content, keywords, window))

    def get_chunk_by_id(chunk_id: int) -> str:
        """Fetch the exact text content of a specific chunk by its ID."""
        chunk_str = orchestrator_get_chunk(content, int(chunk_id))
        if not chunk_str:
            return f"Chunk {chunk_id} not found or empty."
        return chunk_str

    def finalize(
        operating_income: float, operating_ebita: float, ebita_adjustments: list
    ) -> str:
        """Finalize the EBITA extraction, specifying operating_income, operating_ebita, and the adjustments list."""
        return "EBITA extraction finalized."

    tools = [find_keyword_contexts, get_chunk_by_id, finalize]

    finalized_args, history = run_agent_loop(
        client=extractor.llm,
        system_prompt=sys_prompt,
        initial_prompt=user_content,
        tools=tools,
        max_turns=4,
    )

    op_inc = float(finalized_args.get("operating_income", 0.0))
    ebita = float(finalized_args.get("operating_ebita", op_inc))
    ebita_adjustments = finalized_args.get("ebita_adjustments", [])

    # After the loop finishes:
    try:
        from src.agents.curator_agent import CuratorAgent

        ticker = extractor.settings.active_ticker or "UNK"
        history_text = ""
        for h in history:
            history_text += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        curator = CuratorAgent(extractor.settings)
        curator.curate_agent(ticker, "ebita", history_text)
    except Exception as e:
        logger.error(f"Failed to run curator for ebita: {e}")

    return op_inc, ebita, ebita_adjustments
