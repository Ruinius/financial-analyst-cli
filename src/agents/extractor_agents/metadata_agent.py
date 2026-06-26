import logging
import json
from pathlib import Path
from typing import Dict, Optional, Any, List
from pydantic import BaseModel

from src.services.llm_client import LLMClient
from src.core.blackboard import CompanyMetadata
from src.agents.agent_executor import run_agent_loop
from src.tools.find_chunk import get_chunk_by_id
from src.tools.keyword_search import find_keyword_contexts

logger = logging.getLogger(__name__)


class MetadataAgentResult(BaseModel):
    company_metadata: CompanyMetadata
    documents_metadata: Dict[str, Dict[str, Any]]


def run_metadata_agent(
    client: LLMClient,
    ticker: str,
    parsed_documents: Dict[str, str],  # filename -> full file content
) -> MetadataAgentResult:
    """
    Stateless agent that scans fanned-in documents to extract company metadata
    (name, description, fiscal calendar dates, currencies, conversion factors)
    and document-level metadata (document_date, period_end_date, document_type, fiscal_quarter, fiscal_year).
    Has no file I/O.
    """

    # Define local tools to access document contents without file I/O
    def get_first_chunk(filename: str) -> str:
        """Retrieve the first chunk of a target parsed document to find company/document info."""
        content = parsed_documents.get(filename, "")
        if not content:
            return f"Error: Document {filename} not found or empty."
        return get_chunk_by_id(content, 0) or content[:4000]

    def keyword_search(filename: str, keywords: List[str], window: int = 200) -> str:
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
        documents_metadata: Optional[str] = None,
    ) -> str:
        """Finalize the metadata extraction by providing the extracted company metadata details and a JSON string of document-level metadata."""
        return "Metadata extraction finalized."

    # Load document types spec
    doc_types_path = (
        Path(__file__).parent.parent.parent / "resources" / "document_types.json"
    )
    doc_types_str = ""
    if doc_types_path.exists():
        try:
            with open(doc_types_path, "r", encoding="utf-8") as f:
                doc_types_str = f.read()
        except Exception:
            pass

    system_prompt = (
        "You are Sir Pennyworth, a senior financial analyst acting as the Metadata Agent. "
        f"Your task is to scan the available documents for the ticker '{ticker}' and extract core company metadata "
        "as well as document-level metadata for each of the fanned-in documents.\n"
        "Rules:\n"
        "1. You are given a list of parsed document filenames.\n"
        "2. Use 'get_first_chunk' on all documents first to find header information, tables of contents, or general company/document information.\n"
        "3. Use 'keyword_search' if you need to look for specific details like conversion factors (FX rate, ADR ratio) or specific fiscal dates.\n"
        "4. You must extract company-wide metadata:\n"
        "   - Official Company Name\n"
        "   - Short description of the business model\n"
        "   - Fiscal boundary dates (q1, q2, q3, q4 year-end) if mentioned\n"
        "   - Reporting and Trading Currency (e.g. USD, EUR, JPY)\n"
        "   - Preferred unit of reporting (e.g. Millions, Billions)\n"
        "   - FX rate and ADR ratio (if applicable, default to 1.0)\n"
        "5. For EACH fanned-in document, you must also extract its document-level metadata:\n"
        "   - 'document_date' (YYYY-MM-DD): The date the document was filed, published, or released.\n"
        "   - 'period_end_date' (YYYY-MM-DD or 'N/A'): The actual end date of the fiscal period covered by the report.\n"
        "   - 'document_type': must match one of the keys in document_types.json.\n"
        "   - 'fiscal_quarter' (Q1, Q2, Q3, Q4, FY, or N/A).\n"
        "   - 'fiscal_year' (YYYY or N/A): The fiscal year the report corresponds to.\n"
        "6. Once done, call 'finalize' with the extracted arguments. The 'documents_metadata' argument MUST be a valid JSON string "
        "mapping each fanned-in filename to a dictionary with these document metadata keys: "
        "'document_date', 'period_end_date', 'document_type', 'fiscal_quarter', 'fiscal_year'."
    )

    filenames_str = ", ".join(parsed_documents.keys())
    initial_prompt = (
        f"Starting metadata extraction for ticker: '{ticker}'.\n"
        f"Fanned-in parsed documents: [{filenames_str}].\n\n"
        f"Document Types Specification:\n{doc_types_str}\n\n"
        "Please inspect the available documents and extract the company name, description, fiscal calendar dates, reporting currency, preferred unit, FX rate, and ADR ratio. "
        "Also, identify the document-level metadata (document_date, period_end_date, document_type, fiscal_quarter, fiscal_year) for each document, and serialize it as a JSON dictionary passed to 'finalize'."
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

    # Parse documents_metadata JSON string
    documents_metadata = {}
    docs_meta_str = finalized_args.pop("documents_metadata", None)
    if docs_meta_str:
        try:
            documents_metadata = json.loads(docs_meta_str)
        except Exception as e:
            logger.warning(f"Failed to parse documents_metadata JSON: {e}")
            from src.utils.markdown_helper import extract_json_from_text

            json_str = extract_json_from_text(docs_meta_str)
            if json_str:
                try:
                    documents_metadata = json.loads(json_str)
                except Exception:
                    pass

    # Ensure all fanned-in documents have at least a default dictionary in documents_metadata
    for fn in parsed_documents.keys():
        if fn not in documents_metadata:
            documents_metadata[fn] = {
                "document_date": "N/A",
                "period_end_date": "N/A",
                "document_type": "other",
                "fiscal_quarter": "N/A",
                "fiscal_year": "N/A",
            }

    # Extract company metadata keys only
    company_keys = [
        "ticker",
        "company_name",
        "description",
        "fiscal_q1_date",
        "fiscal_q2_date",
        "fiscal_q3_date",
        "fiscal_q4_date",
        "reporting_currency",
        "trading_currency",
        "preferred_unit",
        "fx_rate",
        "adr_ratio",
    ]
    comp_args = {k: v for k, v in finalized_args.items() if k in company_keys}
    comp_args["ticker"] = ticker

    company_metadata = CompanyMetadata.model_validate(comp_args)

    return MetadataAgentResult(
        company_metadata=company_metadata,
        documents_metadata=documents_metadata,
    )
