from src.utils.tools import extract_json_from_text
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_analyst_report(
    file_path: Path,
    content: str,
    chunk_ids: list,
    extractor,
) -> bool:
    summaries = []
    import json
    import src.utils.formatting as formatting
    from src.tools.find_chunk import get_chunk_by_id

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
        "You must execute actions by outputting a valid JSON object containing 'thought', 'tool', and 'arguments'.\n"
        "Available tools:\n"
        "- 'find_keyword_contexts': arguments: {'keywords': list, 'window': int (recommended: 250)}\n"
        "- 'get_chunk_by_id': arguments: {'chunk_id': int}\n"
        "- 'finalize': arguments: {\n"
        "    'analyst_company': str (e.g., 'Morningstar', 'Goldman Sachs', 'J.P. Morgan'. If not explicitly mentioned, try to determine from document text or return 'Unknown'),\n"
        "    'economic_moat': 'None | Narrow | Wide',\n"
        "    'economic_moat_rationale': str,\n"
        "    'margin_outlook': 'Decreasing | Stable | Increasing',\n"
        "    'margin_magnitude': str (representing the amount of increase or decrease in percentage points, e.g., '+2 pp', '-1 pp', or '0 pp'. This refers to how much increase/decrease or acceleration/deceleration occurs, NOT the absolute value of the margin itself. If not explicitly stated, take a best guess),\n"
        "    'margin_rationale': str,\n"
        "    'growth_outlook': 'Decelerating | Stable | Accelerating',\n"
        "    'growth_magnitude': str (representing the amount of acceleration or deceleration in percentage points, e.g., '+2 pp', '-1 pp', or '0 pp'. This refers to how much increase/decrease or acceleration/deceleration occurs, NOT the absolute value of the growth rate itself. If not explicitly stated, take a best guess),\n"
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

    history = [
        {
            "role": "user",
            "content": f"Start synthesizing the analyst report. Document chunks available: {chunk_ids}. Remember to verify source citations.",
        }
    ]

    for turn in range(5):
        prompt = ""
        for h in history:
            prompt += f"\n\n--- {h['role'].upper()} ---\n{h['content']}"
        if turn == 4:
            prompt += (
                "\n\n--- USER ---\n"
                "CRITICAL: This is your final turn. You MUST call the 'finalize' tool now to return your findings. "
                "Do not call any other tool. Provide your best detailed rationales and ratings based on what you have learned so far."
            )
        try:
            resp = extractor.llm.generate(
                prompt, system_prompt=sys_prompt, stream_thinking=True
            ).strip()
        except Exception as e:
            logger.error(f"Analyst Report Agent failed at turn {turn}: {e}")
            break

        history.append({"role": "assistant", "content": resp})

        json_str = extract_json_from_text(resp)
        if not json_str:
            history.append(
                {
                    "role": "user",
                    "content": "Error: Your response did not contain a valid JSON tool call.",
                }
            )
            continue
        try:
            action = json.loads(json_str)
        except Exception as e:
            history.append({"role": "user", "content": f"Error parsing JSON: {e}"})
            continue

        tool = action.get("tool")
        args = action.get("arguments", {})

        if tool == "finalize":
            r_moat = args.get("economic_moat_rationale", "").strip()
            r_margin = args.get("margin_rationale", "").strip()
            r_growth = args.get("growth_rationale", "").strip()

            if (not r_moat or not r_margin or not r_growth) and turn < 4:
                history.append(
                    {
                        "role": "user",
                        "content": (
                            "Error: You called 'finalize' but some rationale fields are empty or missing. "
                            "You MUST provide detailed, non-empty rationales explaining the moat, margin, and growth outlooks based on the document text. "
                            "If the document does not explicitly discuss margins or growth, state that clearly in the rationale field instead of leaving it blank. "
                            "Please populate all rationales fully and call 'finalize' again."
                        ),
                    }
                )
                continue

            analyst_company = args.get("analyst_company", analyst_company)
            economic_moat = args.get("economic_moat", economic_moat)
            moat_rationale = args.get("economic_moat_rationale", moat_rationale)
            margin_outlook = args.get("margin_outlook", margin_outlook)
            margin_mag = args.get("margin_magnitude", margin_mag)
            margin_rationale = args.get("margin_rationale", margin_rationale)
            growth_outlook = args.get("growth_outlook", growth_outlook)
            growth_mag = args.get("growth_magnitude", growth_mag)
            growth_rationale = args.get("growth_rationale", growth_rationale)
            break
        elif tool == "find_keyword_contexts":
            kw = args.get("keywords", [])
            window = args.get("window", 200)
            from src.tools.keyword_search import find_keyword_contexts

            res = str(find_keyword_contexts(content, kw, window))
            history.append(
                {
                    "role": "user",
                    "content": f"Observation from find_keyword_contexts:\n{res[:4000]}",
                }
            )
        elif tool == "get_chunk_by_id":
            cid = int(args.get("chunk_id", 0))
            res = get_chunk_by_id(content, cid)
            summary_sys = "You are Sir Pennyworth. Summarize the analyst report chunk focusing on moat, margins, and growth."
            summary_prompt = f"Summarize Chunk {cid}:\n\n{res[:3000]}"
            try:
                summary_text = extractor.llm.generate(
                    summary_prompt, system_prompt=summary_sys
                ).strip()
                summaries.append(f"- **Chunk {cid}**: {summary_text}")
                history.append(
                    {
                        "role": "user",
                        "content": f"Observation from get_chunk_by_id for chunk {cid}:\nSummary: {summary_text}\nContent: {res[:2000]}",
                    }
                )
            except Exception:
                summaries.append(f"- **Chunk {cid}**: Processed.")
                history.append(
                    {
                        "role": "user",
                        "content": f"Observation from get_chunk_by_id for chunk {cid}:\n{res[:2000]}",
                    }
                )
        else:
            history.append({"role": "user", "content": f"Error: Unknown tool {tool}"})

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
        from src.pipeline.curator_agent import CuratorAgent

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
