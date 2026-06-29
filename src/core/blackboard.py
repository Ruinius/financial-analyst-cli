import logging
import os
from pathlib import Path
from typing import List, Dict, Optional, Literal, Any
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

    @field_validator("category", mode="before")
    @classmethod
    def validate_category(cls, v: Any) -> str:
        valid_cats = {
            "current_assets",
            "noncurrent_assets",
            "current_liabilities",
            "noncurrent_liabilities",
            "equity",
            "income_statement",
        }
        if isinstance(v, str):
            if v in valid_cats:
                return v
            if "asset" in v:
                return "current_assets"
            if "liabilit" in v:
                return "current_liabilities"
            if "equity" in v:
                return "equity"
            if v.strip().lower() == "other":
                return "income_statement"
        return v


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


class ModelAgentsLearnings(BaseModel):
    """Specific learnings gathered for modeling sub-agents to guide future runs."""

    wacc: ExtractAgentLearning = Field(default_factory=ExtractAgentLearning)
    growth: ExtractAgentLearning = Field(default_factory=ExtractAgentLearning)
    margin: ExtractAgentLearning = Field(default_factory=ExtractAgentLearning)
    non_operating: ExtractAgentLearning = Field(default_factory=ExtractAgentLearning)
    dcf_modeling: ExtractAgentLearning = Field(default_factory=ExtractAgentLearning)


class LearningsSchema(BaseModel):
    """Overall self-learning contexts separated by document type to optimize search vectors."""

    annual_filing: DocumentTypeLearnings = Field(default_factory=DocumentTypeLearnings)
    quarterly_filing: DocumentTypeLearnings = Field(
        default_factory=DocumentTypeLearnings
    )
    earnings_announcement: DocumentTypeLearnings = Field(
        default_factory=DocumentTypeLearnings
    )
    model: ModelAgentsLearnings = Field(default_factory=ModelAgentsLearnings)


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
    document_date: Optional[str] = None
    document_type: Optional[str] = None
    fiscal_quarter: Optional[str] = None
    fiscal_year: Optional[str] = None
    period_end_date: Optional[str] = None


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

    def recover_dangling_states(self) -> bool:
        """Scan the blackboard for tasks stuck in 'running' state and reset them to 'failed'."""
        updated = False

        # 1. Company level statuses
        if self.metadata_status == "running":
            self.metadata_status = "failed"
            updated = True
        if self.analyzer_status == "running":
            self.analyzer_status = "failed"
            updated = True
        if self.curator_status == "running":
            self.curator_status = "failed"
            updated = True

        # 2. Raw document states
        for doc in self.raw_documents:
            if doc.ingestion_status == "running":
                doc.ingestion_status = "failed"
                updated = True

        # 3. Report specific statuses
        for period, report in self.reports.items():
            for field in [
                "balance_sheet_status",
                "income_statement_status",
                "shares_status",
                "organic_growth_status",
                "ebita_status",
                "tax_status",
                "wacc_agent_status",
                "growth_agent_status",
                "margin_agent_status",
                "non_operating_agent_status",
                "dcf_modeling_status",
            ]:
                if getattr(report, field) == "running":
                    setattr(report, field, "failed")
                    updated = True

        return updated

    def checkout_status(
        self,
        task_type: str,
        period: Optional[str] = None,
        file_name: Optional[str] = None,
    ) -> None:
        """Transition a task flag to 'running'."""
        if task_type == "metadata":
            self.metadata_status = "running"
        elif task_type == "analyzer":
            self.analyzer_status = "running"
        elif task_type == "curator":
            self.curator_status = "running"
        elif task_type == "ingestion" and file_name:
            for doc in self.raw_documents:
                if doc.file_name == file_name:
                    doc.ingestion_status = "running"
                    break
            else:
                self.raw_documents.append(
                    RawDocumentState(
                        file_name=file_name,
                        sha256="",
                        ingestion_status="running",
                    )
                )
        elif period and period in self.reports:
            report = self.reports[period]
            status_field = f"{task_type}_status"
            if hasattr(report, status_field):
                setattr(report, status_field, "running")

    def checkin_status(
        self,
        task_type: str,
        status: Literal["completed", "failed"],
        period: Optional[str] = None,
        file_name: Optional[str] = None,
        payload: Optional[Any] = None,
    ) -> None:
        """Transition a task flag to completed/failed and write payload to appropriate block."""
        if task_type == "metadata":
            self.metadata_status = status
            if status == "completed" and payload is not None:
                if hasattr(payload, "company_metadata"):
                    self.metadata = payload.company_metadata
                    docs_meta = getattr(payload, "documents_metadata", {})
                    for doc in self.raw_documents:
                        meta = docs_meta.get(doc.file_name)
                        if meta:
                            doc.document_date = meta.get("document_date")
                            doc.document_type = meta.get("document_type")
                            doc.fiscal_quarter = meta.get("fiscal_quarter")
                            doc.fiscal_year = meta.get("fiscal_year")
                            doc.period_end_date = meta.get("period_end_date")
                elif isinstance(payload, CompanyMetadata):
                    self.metadata = payload
        elif task_type == "analyzer":
            self.analyzer_status = status
        elif task_type == "curator":
            self.curator_status = status
        elif task_type == "ingestion" and file_name:
            for doc in self.raw_documents:
                if doc.file_name == file_name:
                    doc.ingestion_status = status
                    if payload and "sha256" in payload:
                        doc.sha256 = payload["sha256"]
                    break
        elif period and period in self.reports:
            report = self.reports[period]
            status_field = f"{task_type}_status"
            if hasattr(report, status_field):
                setattr(report, status_field, status)

            # Apply payloads
            if status == "completed" and payload is not None:
                if task_type == "balance_sheet":
                    report.financial_data.raw_balance_sheet_markdown = (
                        payload.raw_balance_sheet_markdown
                    )
                elif task_type == "income_statement":
                    report.financial_data.raw_income_statement_markdown = (
                        payload.raw_income_statement_markdown
                    )
                elif task_type == "shares":
                    report.financial_data.basic_shares = payload[0]
                    report.financial_data.diluted_shares = payload[1]
                elif task_type == "organic_growth":
                    report.financial_data.simple_growth = payload[0]
                    report.financial_data.organic_growth = payload[1]
                    report.financial_data.revenue = payload[2]
                elif task_type == "ebita":
                    report.financial_data.operating_income = payload[0]
                    report.financial_data.ebita = payload[1]
                elif task_type == "tax":
                    report.financial_data.reported_tax_provision = payload[1]
                    report.financial_data.adjusted_taxes = payload[2]
                    report.financial_data.adjusted_tax_rate = (
                        payload[2] / report.financial_data.ebita
                        if report.financial_data.ebita
                        else 0.21
                    )
                elif task_type in (
                    "wacc_agent",
                    "growth_agent",
                    "margin_agent",
                    "non_operating_agent",
                    "dcf_modeling",
                ):
                    # Modeling updates base_model
                    if not report.base_model:
                        # Construct a default BaseFinancialModel
                        report.base_model = BaseFinancialModel(
                            assumptions=ModelAssumptions(
                                wacc=0.08,
                                company_beta_levered=1.0,
                                company_beta_unlevered=1.0,
                                industry_beta_unlevered=1.0,
                                risk_free_rate=0.042,
                                equity_risk_premium=0.05,
                                pretax_cost_of_debt=0.062,
                                cost_of_equity=0.092,
                                weight_equity=1.0,
                                weight_debt=0.0,
                                target_debt_to_equity=0.0,
                                interest_expense=0.0,
                                capital_turnover=1.0,
                                base_revenue=0.0,
                                base_invested_capital=0.0,
                                revenue_growth_base=0.0,
                                revenue_growth_yr5=0.0,
                                ebita_margin_base=0.0,
                                ebita_margin_yr5=0.0,
                                terminal_margin=0.0,
                                terminal_growth_rate=0.03,
                                adjusted_tax_rate=0.21,
                                excess_cash=0.0,
                                short_term_investments=0.0,
                                debt=0.0,
                                preferred_equity=0.0,
                                minority_interest=0.0,
                                other_financial_assets_net=0.0,
                                net_debt=0.0,
                                shares_outstanding=1.0,
                                share_price=0.0,
                                market_cap=0.0,
                            ),
                            dcf_run_date="",
                        )

                    assumptions = report.base_model.assumptions
                    if task_type == "wacc_agent":
                        assumptions.wacc = payload.get("wacc", 0.08)
                        assumptions.cost_of_equity = payload.get("cost_equity", 0.092)
                        assumptions.pretax_cost_of_debt = payload.get(
                            "cost_debt_pretax", 0.062
                        )
                        assumptions.weight_equity = payload.get("weight_equity", 1.0)
                        assumptions.weight_debt = payload.get("weight_debt", 0.0)
                        assumptions.company_beta_levered = payload.get(
                            "levered_beta", 1.0
                        )
                        assumptions.company_beta_unlevered = payload.get(
                            "unlevered_beta", 1.0
                        )
                        assumptions.net_debt = payload.get("net_debt", 0.0)
                    elif task_type == "growth_agent":
                        assumptions.revenue_growth_base = payload.get(
                            "base_growth_rate", 0.0
                        )
                        assumptions.revenue_growth_yr5 = payload.get(
                            "revenue_growth_rate", 0.0
                        )
                        assumptions.terminal_growth_rate = payload.get(
                            "terminal_growth_rate", 0.03
                        )
                    elif task_type == "margin_agent":
                        assumptions.ebita_margin_base = payload.get("base_margin", 0.0)
                        assumptions.ebita_margin_yr5 = payload.get("margin_yr5", 0.0)
                        assumptions.terminal_margin = payload.get(
                            "terminal_margin", 0.0
                        )
                    elif task_type == "non_operating_agent":
                        assumptions.excess_cash = payload.get("cash", 0.0)
                        assumptions.short_term_investments = payload.get(
                            "short_term_investments", 0.0
                        )
                        assumptions.debt = payload.get("debt", 0.0)
                        assumptions.preferred_equity = payload.get(
                            "preferred_equity", 0.0
                        )
                        assumptions.minority_interest = payload.get(
                            "minority_interest", 0.0
                        )
                        assumptions.other_financial_assets_net = payload.get(
                            "other_financial", 0.0
                        )
                    elif task_type == "dcf_modeling":
                        # Save projections and calculations
                        report.base_model = payload


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
