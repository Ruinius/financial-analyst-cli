import logging
from typing import Dict, Optional
from src.services.llm_client import LLMClient
from src.core.blackboard import CompanyMetadata
from src.agents.agent_executor import run_agent_loop
from src.tools.find_chunk import get_chunk_by_id
from src.tools.keyword_search import find_keyword_contexts

logger = logging.getLogger(__name__)


def run_metadata_agent(
    client: LLMClient,
    ticker: str,
    parsed_documents: Dict[str, str],  # filename -> full file content
) -> CompanyMetadata:
    """
    Stateless agent that scans fanned-in documents to extract company metadata
    (name, description, fiscal calendar dates, currencies, conversion factors).
    Has no file I/O.
    """

    # Define local tools to access document contents without file I/O
    def get_first_chunk(filename: str) -> str:
        """Retrieve the first chunk of a target parsed document to find company info."""
        content = parsed_documents.get(filename, "")
        if not content:
            return f"Error: Document {filename} not found or empty."
        return get_chunk_by_id(content, 0) or content[:4000]

    def keyword_search(filename: str, keywords: list, window: int = 200) -> str:
        """Search the target parsed document content for occurrences of keywords within a window of characters."""
        content = parsed_documents.get(filename, "")
        if not content:
            return f"Error: Document {filename} not found or empty."
        return str(find_keyword_contexts(content, keywords, window))

    def finalize(
        company_name: Optional[str] = None,
        description: Optional[str] = None,
        fiscal_q1_date: Optional[str] = None,
        fiscal_q2_date: Optional[str] = None,
        fiscal_q3_date: Optional[str] = None,
        fiscal_q4_date: Optional[str] = None,
        reporting_currency: str = "USD",
        trading_currency: str = "USD",
        preferred_unit: str = "Millions",
        fx_rate: float = 1.0,
        adr_ratio: float = 1.0,
    ) -> str:
        """Finalize the metadata extraction by providing the extracted company metadata details."""
        return "Metadata extraction finalized."

    system_prompt = (
        "You are Sir Pennyworth, a senior financial analyst acting as the Metadata Agent. "
        f"Your task is to scan the available documents for the ticker '{ticker}' and extract core company metadata.\n"
        "Rules:\n"
        "1. You are given a list of parsed document filenames.\n"
        "2. Use 'get_first_chunk' on relevant documents first to find header information, tables of contents, or general company information.\n"
        "3. Use 'keyword_search' if you need to look for specific details like conversion factors (FX rate, ADR ratio) or specific fiscal dates.\n"
        "4. You must extract:\n"
        "   - Official Company Name\n"
        "   - Short description of the business model\n"
        "   - Fiscal boundary dates (q1, q2, q3, q4 year-end) if mentioned\n"
        "   - Reporting and Trading Currency (e.g. USD, EUR, JPY)\n"
        "   - Preferred unit of reporting (e.g. Millions, Billions)\n"
        "   - FX rate and ADR ratio (if applicable, default to 1.0)\n"
        "5. Once done, call 'finalize' with the extracted arguments."
    )

    filenames_str = ", ".join(parsed_documents.keys())
    initial_prompt = (
        f"Starting metadata extraction for ticker: '{ticker}'.\n"
        f"Fanned-in parsed documents: [{filenames_str}].\n\n"
        "Please inspect the available documents and extract the company name, description, fiscal calendar dates, reporting currency, preferred unit, FX rate, and ADR ratio."
    )

    tools = [get_first_chunk, keyword_search, finalize]

    finalized_args, history = run_agent_loop(
        client=client,
        system_prompt=system_prompt,
        initial_prompt=initial_prompt,
        tools=tools,
        max_turns=10,
    )

    if not finalized_args:
        finalized_args = {}

    finalized_args["ticker"] = ticker

    return CompanyMetadata.model_validate(finalized_args)
