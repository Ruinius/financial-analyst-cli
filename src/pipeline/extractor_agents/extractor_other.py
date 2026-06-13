import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_other(
    file_path: Path,
    content: str,
    chunk_ids: list,
    extractor,
) -> bool:
    summaries = []
    import json
    import src.utils.formatting as formatting
    from src.pipeline.extractor_orchestrator import get_chunk_by_id

    # Read from the center outwards
    center = (len(chunk_ids) + 1) / 2
    sorted_chunk_ids = sorted(chunk_ids, key=lambda x: abs(x - center))

    significant_news_or_developments = ""
    stop_early = False

    for chunk_id in sorted_chunk_ids:
        chunk_body = get_chunk_by_id(content, chunk_id)
        if not chunk_body:
            continue

        # Summarize chunk
        summary_sys = "You are Sir Pennyworth. Summarize the news or announcement chunk, focusing on what is different, unusual, or special in 1-2 sentences."
        summary_prompt = f"Summarize Chunk {chunk_id}:\n\n{chunk_body[:3000]}"
        try:
            summary_text = extractor.llm.generate(
                summary_prompt, system_prompt=summary_sys
            ).strip()
            summaries.append(f"- **Chunk {chunk_id}**: {summary_text}")
        except Exception:
            summaries.append(f"- **Chunk {chunk_id}**: Parsed and processed.")

        # Extract details
        extract_sys = (
            "You are Sir Pennyworth, a sophisticated financial analyst. "
            f"We are scanning the document chunks in this rank order: {sorted_chunk_ids}. "
            "Extract significant news, events, or unusual/special developments."
        )
        extract_prompt = f"""
Rank order of chunks being processed: {sorted_chunk_ids}
Current Chunk ID: {chunk_id}

Chunk {chunk_id} Content:
\"\"\"
{chunk_body}
\"\"\"

Extract significant news, events, or unusual/special developments.
Return a valid JSON object matching this structure:
{{
  "significant_news_or_developments": "Summary of significant news or developments.",
  "all_required_info_found": true
}}

Note: Set 'all_required_info_found' to true if you have found significant news or special developments; otherwise false.
"""

        try:
            ex_resp = extractor.llm.generate(
                extract_prompt, system_prompt=extract_sys, stream_thinking=True
            )
            json_match = re.search(r"\{.*\}", ex_resp, re.DOTALL)
            if json_match:
                ex_data = json.loads(json_match.group(0))

                if ex_data.get("all_required_info_found") is True:
                    stop_early = True

                if ex_data.get("significant_news_or_developments"):
                    significant_news_or_developments = ex_data.get(
                        "significant_news_or_developments"
                    )

        except Exception as e:
            logger.error(f"Failed to parse extraction from chunk {chunk_id}: {e}")

        # Early stopping conditions
        if stop_early:
            formatting.print_success(
                f"Deterministic stop: LLM indicated required information was found on chunk {chunk_id}."
            )
            break

    # Format output
    output_lines = []
    output_lines.append(f"# Extracted Financial Report: {file_path.name}\n")
    output_lines.append("## Chunk Summaries\n")
    output_lines.extend(summaries)
    output_lines.append("\n---\n")

    if significant_news_or_developments:
        output_lines.append("### Significant News or Developments\n")
        output_lines.append(f"{significant_news_or_developments}\n")

    # Write output file to 4_extracted_data/
    extracted_dir = Path(extractor.settings.active_workspace_path) / "4_extracted_data"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    out_file_path = extracted_dir / f"{file_path.stem}_extracted.md"

    with open(out_file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))

    formatting.print_success(f"Extracted: {file_path.name} -> {out_file_path.name}")
    return True
