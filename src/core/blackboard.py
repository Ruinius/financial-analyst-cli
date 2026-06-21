import logging
import os
from pathlib import Path
from typing import List, Dict, Optional, Literal
from pydantic import BaseModel, Field, field_validator

from src.core.config import load_config
from src.core.exceptions import WorkspaceError

logger = logging.getLogger(__name__)


# =====================================================================
# 1. CORE SUPPORTING MODELS
# =====================================================================


class LineItem(BaseModel):
    line_name: str
    value: float
    operating: bool = True
    calculated: bool = False
    category: Literal[
        "current_assets",
        "noncurrent_assets",
        "current_liabilities",
        "noncurrent_liabilities",
        "equity",
        "income_statement",
    ]


# =====================================================================
# 2. COMPANY METADATA (Ingestion & Setup Properties)
# =====================================================================


class CompanyMetadata(BaseModel):
    """Company-wide constant configurations identified during ingest."""

    ticker: str
    company_name: Optional[str] = None
    description: Optional[str] = None  # Short description of the company business model

    # Fiscal calendar boundary dates
    fiscal_q1_date: Optional[str] = None
    fiscal_q2_date: Optional[str] = None
    fiscal_q3_date: Optional[str] = None
    fiscal_q4_date: Optional[str] = None  # Fiscal year-end date

    # Currency and Unit definitions
    reporting_currency: str = "USD"
    trading_currency: str = "USD"
    preferred_unit: str = "Millions"  # e.g., Thousands, Millions, Billions, 10K
    fx_rate: float = 1.0  # Currency conversion rate from reporting to trading
    adr_ratio: float = 1.0  # ADR conversion multiplier for foreign listings


# =====================================================================
# 3. COMPANY LEVEL DATA (Self-Learning Context & Historical Tables)
# =====================================================================


class AgentExecutionMetrics(BaseModel):
    """Tracks run performance statistics for a specific agent type and document format."""

    total_runs: int = 0
    last_turn_count: int = 0
    average_turn_count: float = 0.0


class ExtractAgentLearning(BaseModel):
    """Specific learnings gathered for a single micro-agent's task to guide future runs."""

    status: Literal["pending", "running", "completed", "failed"] = "pending"
    successful_keywords: List[str] = Field(default_factory=list)
    avoid_keywords: List[str] = Field(default_factory=list)
    successful_chunk: List[str] = Field(default_factory=list)
    avoid_chunk: List[str] = Field(default_factory=list)
    metrics: AgentExecutionMetrics = Field(default_factory=AgentExecutionMetrics)


class DocumentTypeLearnings(BaseModel):
    """Micro-agent extract learnings grouped for a specific document format."""

    balance_sheet: ExtractAgentLearning = Field(default_factory=ExtractAgentLearning)
    income_statement: ExtractAgentLearning = Field(default_factory=ExtractAgentLearning)
    diluted_shares: ExtractAgentLearning = Field(default_factory=ExtractAgentLearning)
    organic_growth: ExtractAgentLearning = Field(default_factory=ExtractAgentLearning)
    ebita: ExtractAgentLearning = Field(default_factory=ExtractAgentLearning)
    tax: ExtractAgentLearning = Field(default_factory=ExtractAgentLearning)


class LearningsSchema(BaseModel):
    """Overall self-learning contexts separated by document type to optimize search vectors."""

    annual_filing: DocumentTypeLearnings = Field(default_factory=DocumentTypeLearnings)
    quarterly_filing: DocumentTypeLearnings = Field(
        default_factory=DocumentTypeLearnings
    )
    earnings_announcement: DocumentTypeLearnings = Field(
        default_factory=DocumentTypeLearnings
    )


class HistoricalFinancialSummary(BaseModel):
    """Holds a flat, high-level summary of historical financial metrics for longitudinal views."""

    fiscal_year: int
    fiscal_period: str  # "Q1", "Q2", "Q3", "Q4", "FY"
    revenue: float
    operating_income: float
    ebita: float
    reported_tax_provision: float
    adjusted_taxes: float
    adjusted_tax_rate: float
    basic_shares: float
    diluted_shares: float
    simple_growth: float
    organic_growth: float
    net_working_capital: float
    net_long_term_operating_assets: float
    invested_capital: float
    capital_turnover: float
    nopat: float
    roic: float

    @field_validator("fiscal_year")
    @classmethod
    def validate_fiscal_year(cls, v: int) -> int:
        if not (1000 <= v <= 9999):
            raise ValueError("Fiscal year must be a 4-digit integer")
        return v


class HistoricalAnalystView(BaseModel):
    """Holds a structured summary of qualitative views from analyst reports over time."""

    report_date: str
    source_file: str
    economic_moat: str
    economic_moat_rationale: str
    margin_outlook: str
    margin_magnitude: str
    margin_rationale: str
    growth_outlook: str
    growth_magnitude: str
    growth_rationale: str


class CompanyLevelData(BaseModel):
    learnings: LearningsSchema = Field(default_factory=LearningsSchema)
    # Historical lists storing longitudinal trends and views directly (replacing separate markdown files)
    quarterly_financials: List[HistoricalFinancialSummary] = Field(default_factory=list)
    yearly_financials: List[HistoricalFinancialSummary] = Field(default_factory=list)
    historical_analyst_views: List[HistoricalAnalystView] = Field(default_factory=list)


# =====================================================================
# 4. EXTRACTED DATA PER PERIOD (Quarters & Years)
# =====================================================================


class ExtractedFinancialData(BaseModel):
    """Structured financial figures and raw tables extracted per period."""

    # Embedded Markdown representations (preserves visual layout, spacing, lines, and footnotes)
    raw_balance_sheet_markdown: Optional[str] = None
    raw_income_statement_markdown: Optional[str] = None
    raw_notes_markdown: Optional[str] = (
        None  # Dedicated for disclosures explaining identified accounting anomalies or metric spikes/dips
    )

    # Structured extractions
    line_items: List[LineItem] = Field(default_factory=list)

    # Core Period-Specific Metrics
    revenue: float = 0.0
    operating_income: float = 0.0
    ebita: float = 0.0
    reported_tax_provision: float = 0.0
    adjusted_taxes: float = 0.0
    adjusted_tax_rate: float = 0.21
    basic_shares: float = 0.0
    diluted_shares: float = 0.0
    simple_growth: float = 0.0
    organic_growth: float = 0.0

    # Calculated capital metrics (math.py output)
    net_working_capital: float = 0.0
    net_long_term_operating_assets: float = 0.0
    invested_capital: float = 0.0
    capital_turnover: float = 0.0
    nopat: float = 0.0
    roic: float = 0.0


class AnalystReportExtraction(BaseModel):
    source_file: str
    economic_moat: str
    economic_moat_rationale: str
    margin_outlook: str
    margin_magnitude: str
    margin_rationale: str
    growth_outlook: str
    growth_magnitude: str
    growth_rationale: str


class OtherExtraction(BaseModel):
    source_file: str
    summary: str  # Short summary of the document/release


class ExtractedOtherData(BaseModel):
    """Non-financial statement qualitative extractions."""

    analyst_reports: List[AnalystReportExtraction] = Field(default_factory=list)
    others: List[OtherExtraction] = Field(default_factory=list)


# =====================================================================
# 5. BASE FINANCIAL MODEL PER PERIOD (Valuation & DCF Assumptions)
# =====================================================================


class ModelAssumptions(BaseModel):
    """The DCF inputs and estimations populated by modeling agents."""

    wacc: float

    # WACC inputs and calculation outputs
    company_beta_levered: float
    company_beta_unlevered: float
    industry_beta_unlevered: float
    risk_free_rate: float
    equity_risk_premium: float
    pretax_cost_of_debt: float
    cost_of_equity: float
    weight_equity: float
    weight_debt: float
    target_debt_to_equity: float
    interest_expense: float

    capital_turnover: float
    base_revenue: float
    base_invested_capital: float
    revenue_growth_base: float
    revenue_growth_yr5: float
    ebita_margin_base: float
    ebita_margin_yr5: float
    terminal_margin: float
    terminal_growth_rate: float
    adjusted_tax_rate: float

    # Non-operating bridge categories (latest Balance Sheet values)
    excess_cash: float
    short_term_investments: float
    debt: float
    preferred_equity: float
    minority_interest: float
    other_financial_assets_net: float
    net_debt: float

    # Capital structure inputs
    shares_outstanding: float
    share_price: float
    market_cap: float


class DCFProjectionYear(BaseModel):
    """A single projected year's financials (Years 1-10)."""

    year: int
    revenue: float
    growth: float
    ebita: float
    margin: float
    nopat: float
    reinvestment: float
    invested_capital: float
    roic: float
    fcf: float
    discount_factor: float
    present_value: float


class BaseFinancialModel(BaseModel):
    """Base financial model and WACC/DCF calculations generated for the period."""

    assumptions: ModelAssumptions
    projections: List[DCFProjectionYear] = Field(default_factory=list)

    # Valuation Output
    calculated_intrinsic_value_per_share: float = 0.0
    calculated_equity_value: float = 0.0
    calculated_enterprise_value: float = 0.0
    upside_downside_percentage: str = "N/A"
    dcf_run_date: str


# =====================================================================
# 6. ROOT WORKSPACE STATE (The Temporal Blackboard Container)
# =====================================================================


class TemporalBlackboard(BaseModel):
    """All data and status flags for a single period (Quarter or Year)."""

    fiscal_year: int  # can only be 4 digit year
    fiscal_period: Literal["Q1", "Q2", "Q3", "Q4", "FY"]
    is_quarterly: bool
    source_files: List[str] = Field(default_factory=list)

    # Extractor Sub-Agent Statuses (check-out / check-in lock mechanism to prevent duplicate agent execution)
    balance_sheet_status: Literal["pending", "running", "completed", "failed"] = (
        "pending"
    )
    income_statement_status: Literal["pending", "running", "completed", "failed"] = (
        "pending"
    )
    shares_status: Literal["pending", "running", "completed", "failed"] = "pending"
    organic_growth_status: Literal["pending", "running", "completed", "failed"] = (
        "pending"
    )
    ebita_status: Literal["pending", "running", "completed", "failed"] = "pending"
    tax_status: Literal["pending", "running", "completed", "failed"] = "pending"

    # Structured Contents
    financial_data: ExtractedFinancialData = Field(
        default_factory=ExtractedFinancialData
    )
    other_data: ExtractedOtherData = Field(default_factory=ExtractedOtherData)
    base_model: Optional[BaseFinancialModel] = None

    # Modeling Sub-Agent Statuses (per period)
    wacc_agent_status: Literal["pending", "running", "completed", "failed"] = "pending"
    growth_agent_status: Literal["pending", "running", "completed", "failed"] = (
        "pending"
    )
    margin_agent_status: Literal["pending", "running", "completed", "failed"] = (
        "pending"
    )
    non_operating_agent_status: Literal["pending", "running", "completed", "failed"] = (
        "pending"
    )
    dcf_modeling_status: Literal["pending", "running", "completed", "failed"] = (
        "pending"
    )

    # Error audit trail specific to this period
    arithmetic_errors: List[str] = Field(default_factory=list)

    @field_validator("fiscal_year")
    @classmethod
    def validate_fiscal_year(cls, v: int) -> int:
        if not (1000 <= v <= 9999):
            raise ValueError("Fiscal year must be a 4-digit integer")
        return v


class RawDocumentState(BaseModel):
    """Tracks ingestion status of a raw file before/during parsing."""

    file_name: str
    sha256: str
    ingestion_status: Literal["pending", "running", "completed", "failed"] = "pending"


class WorkspaceContext(BaseModel):
    """The root Blackboard schema stored inside workspaces/[TICKER]/workspace_state.json."""

    metadata: CompanyMetadata
    company_data: CompanyLevelData = Field(default_factory=CompanyLevelData)
    reports: Dict[str, TemporalBlackboard] = Field(
        default_factory=dict
    )  # Keyed by period (e.g., "2024_Q3")

    # Ingestion status per raw document
    raw_documents: List[RawDocumentState] = Field(default_factory=list)

    # Company-level process statuses
    metadata_status: Literal["pending", "running", "completed", "failed"] = "pending"
    analyzer_status: Literal["pending", "running", "completed", "failed"] = "pending"
    curator_status: Literal["pending", "running", "completed", "failed"] = "pending"


# =====================================================================
# 7. ATOMIC STORAGE MANAGER
# =====================================================================


def load_workspace_state(ticker: str) -> WorkspaceContext:
    """Load workspace context state for a given ticker."""
    try:
        settings = load_config()
        if not settings.base_workspace_dir:
            raise WorkspaceError("base_workspace_dir is not configured in settings")
        workspace_dir = Path(settings.base_workspace_dir) / ticker
        state_file = workspace_dir / "workspace_state.json"

        if not state_file.exists():
            logger.info(
                f"Workspace state file {state_file} does not exist. Initializing a default state."
            )
            return WorkspaceContext(metadata=CompanyMetadata(ticker=ticker))

        with open(state_file, "r", encoding="utf-8") as f:
            content = f.read()
        return WorkspaceContext.model_validate_json(content)
    except Exception as e:
        if isinstance(e, WorkspaceError):
            raise e
        raise WorkspaceError(f"Failed to load workspace state for {ticker}: {str(e)}")


def save_workspace_state(ticker: str, state: WorkspaceContext) -> None:
    """Save workspace context state for a given ticker atomically using Single-Writer Pattern."""
    try:
        settings = load_config()
        if not settings.base_workspace_dir:
            raise WorkspaceError("base_workspace_dir is not configured in settings")
        workspace_dir = Path(settings.base_workspace_dir) / ticker
        workspace_dir.mkdir(parents=True, exist_ok=True)

        state_file = workspace_dir / "workspace_state.json"
        tmp_file = workspace_dir / "workspace_state.json.tmp"

        # Serialize to tmp file
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(state.model_dump_json(indent=2))

        # Atomically replace
        os.replace(str(tmp_file), str(state_file))
    except Exception as e:
        raise WorkspaceError(f"Failed to save workspace state for {ticker}: {str(e)}")
