from src.utils.tools import extract_json_from_text
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_transcript(
    file_path: Path,
    content: str,
    chunk_ids: list,
    extractor,
) -> bool:
    summaries = []
    import json
    import src.utils.formatting as formatting
    from src.tools.find_chunk import get_chunk_by_id

    # Read from the center outwards
    center = (len(chunk_ids) + 1) / 2
    sorted_chunk_ids = sorted(chunk_ids, key=lambda x: abs(x - center))[:5]

    guidance_or_qa = ""
    stop_early = False

    history = [
        {
            "role": "user",
            "content": f"Start extracting guidance and Q&A from transcript. Document chunks available: {chunk_ids}.",
        }
    ]

    for chunk_id in sorted_chunk_ids:
        chunk_body = get_chunk_by_id(content, chunk_id)
        if not chunk_body:
            continue

        # Summarize chunk
        summary_sys = "You are Sir Pennyworth. Summarize the transcript chunk, focusing on analyst questions, management guidance, or developments in 1-2 sentences."
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
            "Extract analyst questions, management guidance, and key business developments."
        )
        extract_prompt = f"""
Rank order of chunks being processed: {sorted_chunk_ids}
Current Chunk ID: {chunk_id}

Chunk {chunk_id} Content:
\"\"\"
{chunk_body}
\"\"\"

Extract key management guidance, analyst questions and answers, and important business developments.
Return a valid JSON object matching this structure:
{{
  "guidance_or_qa": "Summary of guidance, questions, and developments.",
  "all_required_info_found": true
}}

Note: Set 'all_required_info_found' to true if you have found the key answers/information needed regarding management guidance or analyst questions; otherwise false.
"""

        history.append(
            {
                "role": "user",
                "content": f"Processing Chunk {chunk_id} Content:\n{chunk_body[:2000]}",
            }
        )

        try:
            ex_resp = extractor.llm.generate(
                extract_prompt, system_prompt=extract_sys, stream_thinking=True
            )
            history.append({"role": "assistant", "content": ex_resp})
            json_str = extract_json_from_text(ex_resp)
            if json_str:
                ex_data = json.loads(json_str)

                if ex_data.get("all_required_info_found") is True:
                    stop_early = True

                if ex_data.get("guidance_or_qa"):
                    guidance_or_qa = ex_data.get("guidance_or_qa")

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

    if guidance_or_qa:
        output_lines.append("### Guidance and Q&A Summary\n")
        output_lines.append(f"{guidance_or_qa}\n")

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
        curator.curate_agent(ticker, "transcript", history_text)
    except Exception as e:
        logger.error(f"Failed to run curator for transcript: {e}")

    formatting.print_success(f"Extracted: {file_path.name} -> {out_file_path.name}")
    return True
