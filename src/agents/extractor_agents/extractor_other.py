import logging
from pathlib import Path
from typing import Optional
from src.core.blackboard import CompanyMetadata, OtherExtraction
from src.services.llm_client import LLMClient
from src.agents.agent_executor import run_agent_loop
from src.tools.find_chunk import get_chunk_by_id
from src.tools.keyword_search import find_keyword_contexts

logger = logging.getLogger(__name__)


def run_other_doc_agent(
    client: LLMClient,
    filename: str,
    content: str,
    company_metadata: CompanyMetadata,
    learnings: Optional[str] = None,
) -> OtherExtraction:
    """
    Stateless other document agent that extracts significant news/developments from parsed files.
    Returns an OtherExtraction schema. Enforces a 10-turn limit.
    """
    max_turns = 10

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst acting as the Other Document Agent. "
        "Your task is to scan the document content and extract significant news, events, or unusual/special developments.\n"
        "Available tools:\n"
        "- 'keyword_search': arguments: {'keywords': list, 'window': int}\n"
        "- 'find_chunk': arguments: {'chunk_id': int}\n"
        "- 'finalize': arguments: {'summary': str}\n\n"
        "Rules:\n"
        "1. You have a maximum of 10 turns. Do not call 'finalize' on the first turn.\n"
        "2. Locate discussions on significant news or events using keyword_search first, or fetch chunk content directly via find_chunk.\n"
        "3. Synthesize the findings and call 'finalize' with a concise summary."
    )

    initial_prompt = f"Start extracting details from other document: '{filename}'."
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

    def finalize(summary: str) -> str:
        """Finalize the extraction, providing a summary of the significant news or developments."""
        return "Extraction finalized."

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

    return OtherExtraction(
        source_file=filename,
        summary=finalized_args.get("summary", ""),
    )


def extract_other(
    file_path: Path,
    content: str,
    chunk_ids: list,
    extractor,
) -> bool:
    """Legacy file-based compatibility wrapper around the stateless run_other_doc_agent."""
    import src.utils.formatting as formatting

    ticker = extractor.settings.active_ticker or "UNK"
    company_metadata = CompanyMetadata(ticker=ticker)

    # Call the stateless agent
    other_extraction = run_other_doc_agent(
        client=extractor.llm,
        filename=file_path.name,
        content=content,
        company_metadata=company_metadata,
        learnings=extractor.get_extract_context(),
    )

    # Format output as expected by the legacy pipeline
    output_lines = []
    output_lines.append(f"# Extracted Financial Report: {file_path.name}\n")
    output_lines.append("## Chunk Summaries\n")
    output_lines.append("- **Summary**: Processed via stateless agent.\n")
    output_lines.append("\n---\n")

    if other_extraction.summary:
        output_lines.append("### Significant News or Developments\n")
        output_lines.append(f"{other_extraction.summary}\n")

    # Write output file to 4_extracted_data/
    extracted_dir = Path(extractor.settings.active_workspace_path) / "4_extracted_data"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    out_file_path = extracted_dir / f"{file_path.stem}_extracted.md"

    with open(out_file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))

    # Invoke Curator Agent to curate lessons
    try:
        from src.agents.curator_agent import CuratorAgent

        history_text = f"Stateless run of OtherDocAgent on {file_path.name}. Finalized output: {other_extraction.model_dump_json()}"
        curator = CuratorAgent(extractor.settings)
        curator.curate_agent(ticker, "other", history_text)
    except Exception as e:
        logger.error(f"Failed to run curator for other: {e}")

    formatting.print_success(f"Extracted: {file_path.name} -> {out_file_path.name}")
    return True
