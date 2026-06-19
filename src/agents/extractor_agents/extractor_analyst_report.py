import logging
from pathlib import Path
from src.tools.find_chunk import get_chunk_by_id
from src.tools.keyword_search import (
    find_keyword_contexts as orchestrator_find_keyword_contexts,
)
from src.agents.agent_executor import run_agent_loop

logger = logging.getLogger(__name__)


def extract_analyst_report(
    file_path: Path,
    content: str,
    chunk_ids: list,
    extractor,
) -> bool:
    summaries = []
    import src.utils.formatting as formatting

    analyst_company = "Unknown"
    economic_moat = "Narrow"
    moat_rationale = ""
    margin_outlook = "Stable"
    margin_mag = "0 pp"
    margin_rationale = ""
    growth_outlook = "Stable"
    growth_mag = "0 pp"
    growth_rationale = ""

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst. Your goal is to synthesize the analyst report's views, "
        "assess qualitative trends, and verify source citations from the document.\n"
        "Available tools:\n"
        "- 'find_keyword_contexts': arguments: {'keywords': list, 'window': int}\n"
        "- 'get_chunk_by_id': arguments: {'chunk_id': int}\n"
        "- 'finalize': arguments: {\n"
        "    'analyst_company': str,\n"
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
        "1. You have a maximum of 5 turns to complete this synthesis. Do not call 'finalize' on the first turn.\n"
        "2. Locate discussions on moat, margin, and growth outlooks using find_keyword_contexts first, or fetch chunk content directly via get_chunk_by_id.\n"
        "3. CRITICAL: The rationale arguments (`economic_moat_rationale`, `margin_rationale`, and `growth_rationale`) MUST NOT be empty or generic. "
        "Each rationale must be a detailed paragraph summarizing the qualitative drivers, evidence, and specific citations "
        "(citing chunk numbers) found in the text. For example, detail switching costs, CAGR, or specific drivers for the moat, margin, and growth outlooks. "
        "Verify your findings, populate all rationales fully, and call 'finalize'."
    )

    initial_prompt = f"Start synthesizing the analyst report. Document chunks available: {chunk_ids}. Remember to verify source citations."

    # Define tools as inner functions
    def find_keyword_contexts(keywords: list, window: int = 200) -> str:
        """Search the document content for occurrences of keywords within a window of characters."""
        return str(orchestrator_find_keyword_contexts(content, keywords, window))

    def get_chunk(chunk_id: int) -> str:
        """Fetch the exact text content of a specific chunk by its ID and generate a short summary of it."""
        cid = int(chunk_id)
        res = get_chunk_by_id(content, cid)
        summary_sys = "You are Sir Pennyworth. Summarize the analyst report chunk focusing on moat, margins, and growth."
        summary_prompt = f"Summarize Chunk {cid}:\n\n{res[:3000]}"
        try:
            summary_text = extractor.llm.generate(
                summary_prompt, system_prompt=summary_sys
            ).strip()
            summaries.append(f"- **Chunk {cid}**: {summary_text}")
            return f"Summary: {summary_text}\nContent: {res[:2000]}"
        except Exception:
            summaries.append(f"- **Chunk {cid}**: Processed.")
            return res[:2000]

    # Map name mapping for tool discovery since agent expects 'get_chunk_by_id'
    get_chunk.__name__ = "get_chunk_by_id"

    def finalize(
        analyst_company: str,
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

    tools = [find_keyword_contexts, get_chunk, finalize]

    finalized_args, history = run_agent_loop(
        client=extractor.llm,
        system_prompt=sys_prompt,
        initial_prompt=initial_prompt,
        tools=tools,
        max_turns=5,
    )

    analyst_company = finalized_args.get("analyst_company", analyst_company)
    economic_moat = finalized_args.get("economic_moat", economic_moat)
    moat_rationale = finalized_args.get("economic_moat_rationale", moat_rationale)
    margin_outlook = finalized_args.get("margin_outlook", margin_outlook)
    margin_mag = finalized_args.get("margin_magnitude", margin_mag)
    margin_rationale = finalized_args.get("margin_rationale", margin_rationale)
    growth_outlook = finalized_args.get("growth_outlook", growth_outlook)
    growth_mag = finalized_args.get("growth_magnitude", growth_mag)
    growth_rationale = finalized_args.get("growth_rationale", growth_rationale)

    # Format output
    output_lines = []
    output_lines.append(f"# Extracted Financial Report: {file_path.name}\n")
    output_lines.append(f"Analyst Company: **{analyst_company}**\n")
    output_lines.append("## Chunk Summaries\n")
    output_lines.extend(summaries)
    output_lines.append("\n---\n")

    output_lines.append("### Economic Moat\n")
    output_lines.append(f"Rating: **{economic_moat}**\n")
    output_lines.append(f"Rationale: {moat_rationale}\n")

    output_lines.append("### EBITA Margin Outlook\n")
    output_lines.append(f"Outlook: **{margin_outlook}**\n")
    output_lines.append(f"Magnitude: **{margin_mag}**\n")
    output_lines.append(f"Rationale: {margin_rationale}\n")

    output_lines.append("### Organic Growth Outlook\n")
    output_lines.append(f"Outlook: **{growth_outlook}**\n")
    output_lines.append(f"Magnitude: **{growth_mag}**\n")
    output_lines.append(f"Rationale: {growth_rationale}\n")

    # Write output file to 4_extracted_data/
    extracted_dir = Path(extractor.settings.active_workspace_path) / "4_extracted_data"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    out_file_path = extracted_dir / f"{file_path.stem}_extracted.md"

    with open(out_file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))

    # Invoke Curator Agent to curate lessons
    try:
        from src.agents.curator_agent import CuratorAgent

        ticker = extractor.settings.active_ticker or "UNK"
        history_text = ""
        for h in history:
            history_text += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"

        curator = CuratorAgent(extractor.settings)
        curator.curate_agent(ticker, "analyst_report", history_text)
    except Exception as e:
        logger.error(f"Failed to run curator for analyst_report: {e}")

    formatting.print_success(f"Extracted: {file_path.name} -> {out_file_path.name}")
    return True
