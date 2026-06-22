import logging
from typing import Optional
from src.core.blackboard import CompanyMetadata, AnalystReportExtraction
from src.services.llm_client import LLMClient
from src.agents.agent_executor import run_agent_loop
from src.tools.find_chunk import get_chunk_by_id
from src.tools.keyword_search import find_keyword_contexts

logger = logging.getLogger(__name__)


def run_analyst_report_agent(
    client: LLMClient,
    filename: str,
    content: str,
    company_metadata: CompanyMetadata,
    learnings: Optional[str] = None,
) -> AnalystReportExtraction:
    """
    Stateless analyst report agent that synthesizes quantitative and qualitative outlooks
    from a parsed analyst report without file I/O. Enforces a 10-turn limit.
    """
    max_turns = 10

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst. Your goal is to synthesize the analyst report's views, "
        "assess qualitative trends, and verify source citations from the document.\n"
        "Available tools:\n"
        "- 'keyword_search': arguments: {'keywords': list, 'window': int}\n"
        "- 'find_chunk': arguments: {'chunk_id': int}\n"
        "- 'finalize': arguments: {\n"
        "    'economic_moat': 'None | Narrow | Wide',\n"
        "    'economic_moat_rationale': str,\n"
        "    'margin_outlook': 'Decreasing | Stable | Increasing',\n"
        "    'margin_magnitude': str,\n"
        "    'margin_rationale': str,\n"
        "    'growth_outlook': 'Decelerating | Stable | Accelerating',\n"
        "    'growth_magnitude': str,\n"
        "    'growth_rationale': str\n"
        "  }\n\n"
        "Rules:\n"
        "1. You have a maximum of 10 turns to complete this synthesis. Do not call 'finalize' on the first turn.\n"
        "2. Locate discussions on moat, margin, and growth outlooks using keyword_search first, or fetch chunk content directly via find_chunk.\n"
        "3. CRITICAL: The rationale arguments (`economic_moat_rationale`, `margin_rationale`, and `growth_rationale`) MUST NOT be empty or generic. "
        "Each rationale must be a detailed paragraph summarizing the qualitative drivers, evidence, and specific citations "
        "(citing chunk numbers) found in the text. For example, detail switching costs, CAGR, or specific drivers for the moat, margin, and growth outlooks. "
        "Verify your findings, populate all rationales fully, and call 'finalize'."
    )

    initial_prompt = f"Start synthesizing the analyst report: '{filename}'. Remember to verify source citations."
    if learnings:
        initial_prompt += f'\n\nHere is the active company extraction learning context to guide your extraction decision logic:\n"""\n{learnings}\n"""'

    # Define tools closed over document content
    def find_chunk(chunk_id: int) -> str:
        """Fetch the exact text content of a specific chunk by its ID."""
        chunk_str = get_chunk_by_id(content, int(chunk_id))
        if not chunk_str:
            return f"Chunk {chunk_id} not found or empty."
        return chunk_str

    def keyword_search(keywords: list, window: int = 200) -> str:
        """Search the document content for occurrences of keywords within a window of characters."""
        return str(find_keyword_contexts(content, keywords, window))

    def finalize(
        economic_moat: str,
        economic_moat_rationale: str,
        margin_outlook: str,
        margin_magnitude: str,
        margin_rationale: str,
        growth_outlook: str,
        growth_magnitude: str,
        growth_rationale: str,
    ) -> str:
        """Finalize the analyst report synthesis, providing ratings and detailed non-empty rationales for moat, margin, and growth outlooks."""
        if (
            not economic_moat_rationale.strip()
            or not margin_rationale.strip()
            or not growth_rationale.strip()
        ):
            raise ValueError(
                "You called 'finalize' but some rationale fields are empty or missing. "
                "You MUST provide detailed, non-empty rationales explaining the moat, margin, and growth outlooks. "
                "If not explicitly discussed, state that clearly in the rationale field instead of leaving it blank."
            )
        return "Analyst report synthesis finalized."

    tools = [find_chunk, keyword_search, finalize]

    finalized_args, history = run_agent_loop(
        client=client,
        system_prompt=sys_prompt,
        initial_prompt=initial_prompt,
        tools=tools,
        max_turns=max_turns,
    )

    if not finalized_args:
        finalized_args = {}

    return AnalystReportExtraction(
        source_file=filename,
        economic_moat=finalized_args.get("economic_moat", "Narrow"),
        economic_moat_rationale=finalized_args.get("economic_moat_rationale", ""),
        margin_outlook=finalized_args.get("margin_outlook", "Stable"),
        margin_magnitude=finalized_args.get("margin_magnitude", "0 pp"),
        margin_rationale=finalized_args.get("margin_rationale", ""),
        growth_outlook=finalized_args.get("growth_outlook", "Stable"),
        growth_magnitude=finalized_args.get("growth_magnitude", "0 pp"),
        growth_rationale=finalized_args.get("growth_rationale", ""),
    )
