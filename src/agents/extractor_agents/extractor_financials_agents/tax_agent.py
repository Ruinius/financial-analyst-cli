import json
import logging
from src.tools.keyword_search import (
    find_keyword_contexts as orchestrator_find_keyword_contexts,
)
from src.tools.find_chunk import get_chunk_by_id as orchestrator_get_chunk
from src.agents.agent_executor import run_agent_loop

logger = logging.getLogger(__name__)


def run_tax_agent(
    content: str,
    extractor,
    operating_income: float,
    operating_ebita: float,
    ebita_adjustments: list,
    income_statement_content: str = "",
    is_quarterly: bool = True,
) -> tuple[float, float, float, list]:
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
        "You are Sir Pennyworth, a senior financial analyst specializing in tax provisions and adjustments.\n"
        f"Your task is to identify key income statement figures directly from the statement (specifically "
        "Income Before Taxes and Reported Tax Provision), identify non-operating bridge items and non-recurring tax "
        "benefits from footnotes, and calculate adjusted taxes, focusing specifically on the "
        f"{focus_period} time period.\n\n"
        "You have been provided with the already extracted Operating Income, Operating EBITA, and EBITA adjustments from a prior stage.\n"
        "Rules:\n"
        "1. You have a maximum of 4 turns. Search for keyword contexts and chunks first to locate the figures.\n"
        "2. Extract Reported Income Before Taxes and Reported Tax Provision from the income statement content.\n"
        "3. Back out the tax effect of non-operating adjustments at a statutory rate of 25% (21% federal, 4% state/local). This includes:\n"
        "   - The EBITA adjustments identified by the EBITA agent (e.g. restructuring, amortization).\n"
        "   - Non-operating items that bridge Income Before Taxes to Operating Income (e.g., interest expense, interest income, non-operating gains/losses).\n"
        "4. Identify any non-recurring tax benefits/credits in the footnotes.\n"
        "5. Calculate Adjusted Taxes = Reported Tax Provision + Tax effect of adjustments - non-recurring tax benefits.\n"
        "6. Standardize positive/negative signs for the calculations and outputs:\n"
        "   - The Reported Tax Provision is expressed as a negative number if it is a tax expense, and positive only if it is a tax benefit/credit.\n"
        "   - For the tax effect of non-operating adjustments (tax_adjustments): a positive value indicates a tax benefit/credit (reducing tax expense), and a negative value indicates a tax expense (increasing overall tax expense).\n"
        "   - Ensure that Adjusted Taxes and their components in the returned JSON have signs consistent with these rules so that math checks (e.g. Adjusted Taxes = Reported Tax Provision + Tax effect of adjustments - non-recurring tax benefits) work correctly.\n"
        "7. Reasoning rules for tax adjustments direction:\n"
        "   - When backing out adjustments to calculate Adjusted Taxes:\n"
        "     - Non-operating bridge items (like interest expense or interest income) must be tax-adjusted as well. An interest expense add-back is a positive pre-tax adjustment (since interest expense was subtracted to get Income Before Taxes). An interest income subtraction is a negative pre-tax adjustment.\n"
        "     - A positive adjustment increases taxable operating profit. Therefore, it increases tax expense (making the tax adjustment a negative value, representing additional tax expense).\n"
        "     - A negative adjustment decreases taxable operating profit. Therefore, it decreases tax expense (making the tax adjustment a positive value, representing a tax reduction/benefit).\n"
        "     - Exception: Non-deductible items like goodwill impairments have a tax impact of 0%, so they have 0.0 associated tax adjustment.\n"
        "8. Identify the currency and unit from the extracted income statement content (provided below). Ensure all pre-tax income, reported tax provision, and tax adjustments are in this same currency and unit (do not convert to USD unless the income statement itself is in USD).\n\n"
        "Example finalize tool call:\n"
        "{\n"
        '  "thought": "I will finalize the extraction. Reported pre-tax income is 1600.0. Tax rate is 25%. Restructuring tax effect of -25.0 (based on 100.0 EBITA adjustment) and interest expense tax effect of -100.0. Total Adjusted Taxes is -400.0 (Reported Tax Provision) + -25.0 + -100.0 = -525.0.",\n'
        '  "tool": "finalize",\n'
        '  "arguments": {\n'
        '    "income_before_taxes": 1600.0,\n'
        '    "reported_tax_provision": -400.0,\n'
        '    "adjusted_taxes": -525.0,\n'
        '    "tax_adjustments": [\n'
        '      {"name": "Tax effect of restructuring at 25%", "value": -25.0},\n'
        '      {"name": "Tax effect of interest expense at 25%", "value": -100.0}\n'
        "    ]\n"
        "  }\n"
        "}"
    )

    user_content = (
        "Start searching for tax provisions and non-operating bridge items. Remember, you have up to 4 turns.\n"
        f"The EBITA Agent has already determined:\n"
        f"- Operating Income: {operating_income}\n"
        f"- Operating EBITA: {operating_ebita}\n"
        f"- EBITA Adjustments: {json.dumps(ebita_adjustments)}\n\n"
        "Here are some useful keywords to search for if needed: interest, gain, loss, tax benefit, tax adjustment, provision, statutory."
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
        income_before_taxes: float,
        reported_tax_provision: float,
        adjusted_taxes: float,
        tax_adjustments: list,
    ) -> str:
        """Finalize the tax adjustments extraction, specifying income_before_taxes, reported_tax_provision, adjusted_taxes, and the adjustments list."""
        return "Tax extraction finalized."

    tools = [find_keyword_contexts, get_chunk_by_id, finalize]

    finalized_args, history = run_agent_loop(
        client=extractor.llm,
        system_prompt=sys_prompt,
        initial_prompt=user_content,
        tools=tools,
        max_turns=4,
    )

    inc_bt = float(finalized_args.get("income_before_taxes", 0.0))
    rep_tax = float(finalized_args.get("reported_tax_provision", 0.0))
    adj_taxes = float(finalized_args.get("adjusted_taxes", rep_tax))
    tax_adjustments = finalized_args.get("tax_adjustments", [])

    # After the loop finishes:
    try:
        from src.agents.curator_agent import CuratorAgent

        ticker = extractor.settings.active_ticker or "UNK"
        history_text = ""
        for h in history:
            history_text += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        curator = CuratorAgent(extractor.settings)
        curator.curate_agent(ticker, "tax", history_text)
    except Exception as e:
        logger.error(f"Failed to run curator for tax: {e}")

    return inc_bt, rep_tax, adj_taxes, tax_adjustments
