import json
from typing import Optional
from src.core.blackboard import CompanyMetadata, WorkspaceContext


def query_blackboard_helper(
    workspace_state: WorkspaceContext,
    company_metadata: CompanyMetadata,
    period_key: str,
    section: str,
    period: Optional[str] = None,
) -> str:
    """
    Core implementation to query the active blackboard state in a read-only manner.
    Arguments:
      workspace_state: The current WorkspaceContext.
      company_metadata: The current CompanyMetadata.
      period_key: The active period key (e.g. '2024_Q3').
      section: The section of the blackboard to query. Options: 'metadata', 'company_data', 'financial_data', 'other_data', 'reports'.
      period: Optional specific period (e.g., '2024_Q3') if querying 'financial_data' or 'other_data'. If not specified, defaults to the current active period.
    """
    if section == "metadata":
        return company_metadata.model_dump_json()
    elif section == "company_data":
        return workspace_state.company_data.model_dump_json()
    elif section == "reports":
        return json.dumps(list(workspace_state.reports.keys()))
    elif section in ("financial_data", "other_data"):
        p = period or period_key
        if p not in workspace_state.reports:
            return f"Error: Period '{p}' not found in reports."
        report = workspace_state.reports[p]
        if section == "financial_data":
            return report.financial_data.model_dump_json()
        else:
            return report.other_data.model_dump_json()
    else:
        return f"Error: Unknown section '{section}'. Valid options are: metadata, company_data, reports, financial_data, other_data."
