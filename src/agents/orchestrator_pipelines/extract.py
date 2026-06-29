import asyncio
import logging
import json
from pathlib import Path
from typing import Optional, List

from src.core.exceptions import WorkspaceError
from src.core.blackboard import (
    load_workspace_state,
    save_workspace_state,
    TemporalBlackboard,
)

logger = logging.getLogger(__name__)


def parse_markdown_to_line_items(
    markdown_content: str,
    llm,
    category_default: str,
) -> list:
    from src.core.blackboard import LineItem
    from src.utils.financial_math import clean_val
    from src.utils.markdown_helper import extract_json_from_text

    if not markdown_content:
        return []

    content = markdown_content

    dict_guidance = ""
    if category_default == "income_statement":
        dict_path = Path("src/resources/dictionary/income_statement.md")
        if dict_path.exists():
            try:
                is_dict = dict_path.read_text(encoding="utf-8")
                if is_dict:
                    dict_guidance = f"\n\nUse the following Income Statement Dictionary as a guide for classifications and expense/revenue sign mapping:\n{is_dict}\n"
            except Exception:
                pass

    sys_prompt = (
        "You are Sir Pennyworth, a senior financial analyst. "
        "Extract all financial statement line items from the provided markdown statement. "
        "Ensure you extract standard items: revenue, operating income, cash_and_equivalents, debt, etc."
    )
    if category_default == "income_statement":
        sys_prompt += (
            "\n\nStandardize positive/negative signs for the Income Statement:\n"
            "- Any number that subtracts from the revenue is an expense, cost, or loss, and MUST be expressed as a negative number.\n"
            "- Any number that effectively increases profit (e.g. revenue, interest income, tax benefits, gains) MUST be expressed as a positive number.\n"
            "- If an item is an expense but listed as a positive number in the source markdown, you MUST convert it to a negative number.\n"
            "- Be careful with ambiguous items like 'Net Interest Income' or 'Other Income/Expense Net'. Check their context: if they represent a net expense or loss, express them as negative. If they represent net income or gain, express them as positive."
        )

    prompt = f"""
Markdown statement content:
\"\"\"
{content}
\"\"\"
{dict_guidance}
Extract all financial statement line items (Line Name, Value, Category (current_assets | current_liabilities | noncurrent_assets | noncurrent_liabilities | income_statement | other)).
Return a valid JSON object matching this structure:
{{
  "line_items": [
     {{
       "line_name": "Cash and cash equivalents",
       "value": "12,345",
       "category": "{category_default}"
     }}
  ]
}}
"""
    extracted_items = []
    try:
        resp = llm.generate(prompt, system_prompt=sys_prompt, stream_thinking=True)
        json_str = extract_json_from_text(resp)
        if json_str:
            data = json.loads(json_str)
            for item in data.get("line_items", []):
                val_float = clean_val(str(item.get("value", "0")))
                if val_float == 0.0 and str(item.get("value")) not in ["0", "0.0"]:
                    continue

                cat = item.get("category", category_default)
                if cat not in [
                    "current_assets",
                    "noncurrent_assets",
                    "current_liabilities",
                    "noncurrent_liabilities",
                    "equity",
                    "income_statement",
                ]:
                    if "asset" in cat:
                        cat = "current_assets"
                    elif "liabilit" in cat:
                        cat = "current_liabilities"
                    elif "equity" in cat:
                        cat = "equity"
                    else:
                        cat = "income_statement"

                line_item = LineItem(
                    line_name=item.get("line_name"),
                    value=val_float,
                    category=cat,
                    operating=True,
                    calculated=False,
                )
                extracted_items.append(line_item)
    except Exception as e:
        logger.error(f"Failed to parse line items from markdown statement: {e}")

    return extracted_items


async def orchestrate_extract(
    orchestrator,
    ticker: str,
    agent: Optional[str] = None,
    non_interactive: bool = False,
    limit: Optional[int] = None,
    force: bool = False,
    target_files: Optional[List[str]] = None,
) -> None:
    import src.agents.blackboard_orchestrator as bo
    from src.agents.orchestrator_pipelines.ingest import Ingester

    def run_extractor_with_learning(agent_fn, agent_name, doc_type, *args, **kwargs):
        from src.agents.agent_executor import last_agent_run

        # Clear any prior run state
        last_agent_run.set(None)

        res = agent_fn(*args, **kwargs)

        # Try to run learning
        run_info = last_agent_run.get()
        if run_info:
            turn_count, run_logs = run_info
            try:
                from src.agents.learning_agent import LearningAgent

                learning_agent = LearningAgent(
                    settings=orchestrator.settings, client=orchestrator.client
                )
                learning_agent.run_learning(
                    ticker=ticker,
                    agent_name=agent_name,
                    document_type=doc_type,
                    turn_count=turn_count,
                    run_logs=run_logs,
                )
            except Exception as le:
                logger.error(f"LearningAgent run failed for {agent_name}: {le}")
        return res

    def get_doc_type_for_period(period_key: str) -> str:
        is_q = "Q" in period_key
        registry_rows = periods_docs.get(period_key, [])
        for r in registry_rows:
            dt = r.get("document_type")
            if dt in ("annual_filing", "quarterly_filing", "earnings_announcement"):
                return dt
        return "quarterly_filing" if is_q else "annual_filing"

    state = load_workspace_state(ticker)
    settings = orchestrator.settings
    workspace = Path(settings.active_workspace_path)

    # Load registry
    ingester_inst = Ingester()
    registry = ingester_inst.load_parsed_registry()

    parsed_dir = workspace / "2_parsed_data"
    all_files = []
    if parsed_dir.exists():
        all_files = [
            p
            for p in parsed_dir.iterdir()
            if p.is_file()
            and p.suffix.lower() == ".md"
            and p.name.lower() != "readme.md"
            and not p.name.startswith(".")
        ]

    # Find which files are already extracted
    needing_extraction = []
    if not force:
        extracted_files = set()
        for report in state.reports.values():
            for sf in report.source_files:
                extracted_files.add(sf)

        for p in all_files:
            fn = p.name
            # Find registry row
            row = None
            for r in registry.values():
                if r.get("new_filename") == fn:
                    row = r
                    break

            if not row:
                needing_extraction.append(p)
                continue

            fy = row.get("fiscal_year")
            fq = row.get("fiscal_quarter")
            doc_type = row.get("document_type", "other")

            if not fy or not fq or fy == "N/A" or fq == "N/A" or doc_type == "N/A":
                needing_extraction.append(p)
                continue

            period_key = f"{fy}_{fq}"
            if period_key not in state.reports:
                needing_extraction.append(p)
                continue

            report = state.reports[period_key]
            if fn not in report.source_files:
                needing_extraction.append(p)
                continue

            is_formal = doc_type in (
                "quarterly_filing",
                "annual_filing",
                "earnings_announcement",
            )
            if is_formal:
                if (
                    report.balance_sheet_status != "completed"
                    or report.income_statement_status != "completed"
                    or report.shares_status != "completed"
                    or report.organic_growth_status != "completed"
                    or report.ebita_status != "completed"
                    or report.tax_status != "completed"
                ):
                    needing_extraction.append(p)
                    continue
    else:
        # If force is True or single agent targeted, treat all files as candidates
        needing_extraction = all_files

    # Sort files in reverse-chronological order (descending by filename)
    needing_extraction = sorted(needing_extraction, key=lambda p: p.name, reverse=True)

    if target_files is not None:
        # Explicit target files requested
        files_to_process = [p for p in all_files if p.name in target_files]
    else:
        # Apply limit to needing_extraction
        files_to_process = needing_extraction
        import src.utils.formatting as formatting

        already_extracted = [p.name for p in all_files if p not in needing_extraction]

        if limit is not None:
            if limit > len(needing_extraction):
                formatting.print_info(
                    f"Acknowledge limit of {limit} files requested, but there is only {len(needing_extraction)} file(s) that is new."
                )
                if already_extracted:
                    formatting.print_info(
                        "Skipped the already extracted file(s) and starting on the new file(s):"
                    )
                    for fn_ext in already_extracted:
                        formatting.print_info(
                            f"  - Skipped (already extracted): {fn_ext}"
                        )

            skipped_files = needing_extraction[limit:]
            files_to_process = needing_extraction[:limit]

            for f in skipped_files:
                formatting.print_info(f"Skipped extraction due to limit: {f.name}")
        else:
            if already_extracted and not force:
                formatting.print_info(
                    "Skipping already extracted document(s) and starting on new document(s):"
                )
                for fn_ext in already_extracted:
                    formatting.print_info(f"  - Skipped (already extracted): {fn_ext}")
                for p_proc in files_to_process:
                    formatting.print_info(
                        f"  - Starting extraction on new file: {p_proc.name}"
                    )

    selected_filenames = {p.name for p in files_to_process}

    parsed_documents = {}
    for p in files_to_process:
        try:
            parsed_documents[p.name] = p.read_text(encoding="utf-8")
        except Exception:
            pass

    if not parsed_documents:
        # No files to extract, return early
        return

    extract_agent_map = {
        "metadata": "metadata",
        "metadata_agent": "metadata",
        "balance_sheet": "balance_sheet",
        "balance_sheet_agent": "balance_sheet",
        "income_statement": "income_statement",
        "income_statement_agent": "income_statement",
        "shares": "shares",
        "shares_agent": "shares",
        "diluted_shares": "shares",
        "diluted_shares_agent": "shares",
        "organic_growth": "organic_growth",
        "organic_growth_agent": "organic_growth",
        "interpretation": "interpretation",
        "interpretation_agent": "interpretation",
        "ebita": "ebita",
        "ebita_agent": "ebita",
        "operating_ebita": "ebita",
        "operating_ebita_agent": "ebita",
        "tax": "tax",
        "tax_agent": "tax",
        "adjusted_taxes": "tax",
        "adjusted_taxes_agent": "tax",
        "analyst_report": "analyst_report",
        "analyst_report_agent": "analyst_report",
        "other": "other",
        "other_doc": "other",
        "other_doc_agent": "other",
    }

    model_agent_map = {
        "wacc": "wacc_agent",
        "wacc_agent": "wacc_agent",
        "growth": "growth_agent",
        "growth_agent": "growth_agent",
        "margin": "margin_agent",
        "margin_agent": "margin_agent",
        "non_operating": "non_operating_agent",
        "non_operating_agent": "non_operating_agent",
        "dcf": "dcf_modeling",
        "dcf_modeling": "dcf_modeling",
        "dcf_modeling_agent": "dcf_modeling",
    }

    normalized_agent = None
    if agent:
        agent_lower = agent.lower().strip()
        if agent_lower in extract_agent_map:
            normalized_agent = extract_agent_map[agent_lower]
        elif agent_lower in model_agent_map:
            # Modeling agent, skip this stage
            return
        else:
            raise WorkspaceError(f"Unknown agent: '{agent}'")

    # Verify global dependency: company metadata extraction must be completed first for non-metadata agents
    if normalized_agent and normalized_agent != "metadata":
        if state.metadata_status != "completed":
            raise WorkspaceError(
                "Missing dependency: Company metadata extraction must be completed first."
            )

    # 1. Run MetadataAgent if pending or failed, or explicitly targeted, or if any selected files lack metadata
    has_unidentified_metadata = False
    for fn in selected_filenames:
        row = None
        for r in registry.values():
            if r.get("new_filename") == fn:
                row = r
                break
        if (
            not row
            or row.get("fiscal_year") == "N/A"
            or row.get("fiscal_quarter") == "N/A"
            or row.get("document_type") == "N/A"
        ):
            has_unidentified_metadata = True
            break

    run_metadata = (
        (normalized_agent == "metadata")
        or (
            normalized_agent is None
            and (
                state.metadata_status in ("pending", "failed")
                or has_unidentified_metadata
            )
        )
        or force
    )

    if run_metadata:
        orchestrator.checkout_status(ticker, "metadata")
        try:
            metadata_result = await asyncio.to_thread(
                bo.run_metadata_agent,
                client=orchestrator.client,
                ticker=ticker,
                parsed_documents=parsed_documents,
            )
            orchestrator.checkin_status(
                ticker, "metadata", "completed", payload=metadata_result
            )

            # Sync newly extracted document metadata back to parsed_data.csv cache
            if hasattr(metadata_result, "documents_metadata"):
                ingester_inst = Ingester()
                reg = ingester_inst.load_parsed_registry()

                # Document type abbreviation dictionary
                doc_types_path = (
                    Path(__file__).parent.parent.parent
                    / "resources"
                    / "document_types.json"
                )
                doc_type_abbr = {}
                if doc_types_path.exists():
                    try:
                        with open(doc_types_path, "r", encoding="utf-8") as f:
                            doc_types_data = json.load(f)
                            for k, v in doc_types_data.get(
                                "document_types", {}
                            ).items():
                                if "abbreviation" in v:
                                    doc_type_abbr[k] = v["abbreviation"]
                    except Exception:
                        pass

                # Fallback if loading failed
                if not doc_type_abbr:
                    doc_type_abbr = {
                        "quarterly_filing": "10Q",
                        "annual_filing": "10K",
                        "earnings_announcement": "EA",
                        "press_release": "PR",
                        "analyst_report": "AR",
                        "news_article": "NA",
                        "transcript": "TR",
                        "other": "OTH",
                    }

                renamed_mapping = {}  # old_new_filename -> new_new_filename

                for fn, m in metadata_result.documents_metadata.items():
                    target_hash = None
                    for h, row in reg.items():
                        if (
                            row.get("new_filename") == fn
                            or row.get("original_filename") == fn
                        ):
                            target_hash = h
                            break
                    if target_hash:
                        doc_date = m.get("document_date", "N/A")
                        doc_type = m.get("document_type", "other")
                        fq = m.get("fiscal_quarter", "N/A")
                        fy = m.get("fiscal_year", "N/A")
                        period_end = m.get("period_end_date", "N/A")

                        reg[target_hash]["document_date"] = doc_date
                        reg[target_hash]["document_type"] = doc_type
                        reg[target_hash]["fiscal_quarter"] = fq
                        reg[target_hash]["fiscal_year"] = fy
                        reg[target_hash]["period_end_date"] = period_end

                        # Deterministic rename steps
                        clean_date = doc_date.replace("-", "").strip()
                        abbr = doc_type_abbr.get(doc_type)
                        if not abbr:
                            if doc_type in doc_type_abbr.values():
                                abbr = doc_type
                            else:
                                abbr = (
                                    doc_type.replace(" ", "_").upper()
                                    if doc_type
                                    else "OTH"
                                )

                        old_new_filename = reg[target_hash].get("new_filename")
                        old_original_filename = reg[target_hash].get(
                            "original_filename"
                        )

                        if clean_date and clean_date != "N/A" and len(clean_date) == 8:
                            new_stem = f"{clean_date}_{abbr}_parsed"
                        else:
                            old_stem = (
                                Path(old_new_filename).stem
                                if old_new_filename
                                else "document"
                            )
                            new_stem = f"{old_stem}_{abbr}_parsed"

                        new_new_filename = f"{new_stem}.md"

                        # Rename parsed markdown file
                        parsed_dir = workspace / "2_parsed_data"
                        old_parsed_path = parsed_dir / old_new_filename
                        new_parsed_path = parsed_dir / new_new_filename

                        if (
                            old_parsed_path.exists()
                            and old_parsed_path != new_parsed_path
                        ):
                            try:
                                if new_parsed_path.exists():
                                    new_parsed_path.unlink()
                                old_parsed_path.rename(new_parsed_path)
                                logger.info(
                                    f"Renamed parsed file: {old_new_filename} -> {new_new_filename}"
                                )
                                import src.utils.formatting as formatting

                                formatting.print_success(
                                    f"Renamed parsed file: {old_new_filename} -> {new_new_filename}"
                                )
                            except Exception as re:
                                logger.error(
                                    f"Failed to rename parsed file {old_new_filename}: {re}"
                                )

                        # Rename archived raw file
                        archive_dir = workspace / "3_archived_data"
                        if old_original_filename:
                            old_archive_path = archive_dir / old_original_filename
                            suffix = Path(old_original_filename).suffix
                            new_original_filename = f"{new_stem}{suffix}"
                            new_archive_path = archive_dir / new_original_filename

                            if (
                                old_archive_path.exists()
                                and old_archive_path != new_archive_path
                            ):
                                try:
                                    if new_archive_path.exists():
                                        new_archive_path.unlink()
                                    old_archive_path.rename(new_archive_path)
                                    logger.info(
                                        f"Renamed archived file: {old_original_filename} -> {new_original_filename}"
                                    )
                                    import src.utils.formatting as formatting

                                    formatting.print_success(
                                        f"Renamed archived file: {old_original_filename} -> {new_original_filename}"
                                    )
                                    reg[target_hash]["original_filename"] = (
                                        new_original_filename
                                    )
                                except Exception as ae:
                                    logger.error(
                                        f"Failed to rename archived file {old_original_filename}: {ae}"
                                    )

                        reg[target_hash]["new_filename"] = new_new_filename
                        renamed_mapping[old_new_filename] = new_new_filename

                        # Update blackboard state references to the filenames
                        try:
                            w_state = load_workspace_state(ticker)
                            state_updated = False
                            for doc in w_state.raw_documents:
                                if doc.file_name == old_original_filename:
                                    doc.file_name = reg[target_hash][
                                        "original_filename"
                                    ]
                                    state_updated = True
                            for report in w_state.reports.values():
                                if old_new_filename in report.source_files:
                                    report.source_files = [
                                        new_new_filename
                                        if sf == old_new_filename
                                        else sf
                                        for sf in report.source_files
                                    ]
                                    state_updated = True
                            if state_updated:
                                save_workspace_state(ticker, w_state)
                        except Exception as se:
                            logger.error(
                                f"Failed to update workspace state filename references: {se}"
                            )

                ingester_inst.save_parsed_registry(reg)

                # Update selected_filenames in memory
                new_selected_filenames = set()
                for fn in selected_filenames:
                    if fn in renamed_mapping:
                        new_selected_filenames.add(renamed_mapping[fn])
                    else:
                        new_selected_filenames.add(fn)
                selected_filenames = new_selected_filenames

        except Exception as e:
            logger.error(f"MetadataAgent execution failed: {e}")
            orchestrator.checkin_status(ticker, "metadata", "failed")
            raise WorkspaceError(f"Metadata extraction failed: {e}")

    # If we are only running metadata agent, stop here
    if normalized_agent == "metadata":
        return

    # Reload state
    state = load_workspace_state(ticker)
    if state.metadata_status != "completed":
        logger.warning(
            "Metadata extraction is not completed. Cannot proceed with sub-agents."
        )
        return

    ingester = Ingester()
    registry = ingester.load_parsed_registry()

    # Group docs by period_key
    periods_docs = {}
    for row in registry.values():
        fy = row.get("fiscal_year")
        fq = row.get("fiscal_quarter")
        if not fy or not fq or fy == "N/A" or fq == "N/A":
            continue
        period_key = f"{fy}_{fq}"
        periods_docs.setdefault(period_key, []).append(row)

    # Find which periods contain at least one of the selected files
    periods_to_update = set()
    for period_key, doc_rows in periods_docs.items():
        for row in doc_rows:
            if row["new_filename"] in selected_filenames:
                periods_to_update.add(period_key)
                break

    # For each period, initialize reports on blackboard
    for period_key in periods_docs:
        if period_key not in state.reports:
            fy_str, fq_str = period_key.split("_")
            is_q = "Q" in fq_str
            state.reports[period_key] = TemporalBlackboard(
                fiscal_year=int(fy_str),
                fiscal_period=fq_str,
                is_quarterly=is_q,
            )
    save_workspace_state(ticker, state)

    learnings = ""

    updated_periods = set()

    # Check prerequisites for single agents that target specific periods
    if normalized_agent == "shares":
        has_valid_period = any(
            report.income_statement_status == "completed"
            for report in state.reports.values()
        )
        if not has_valid_period:
            raise WorkspaceError(
                "Missing dependency: Income statement must be completed for at least one period before running shares agent."
            )
    elif normalized_agent == "organic_growth":
        has_valid_period = any(
            report.income_statement_status == "completed"
            for report in state.reports.values()
        )
        if not has_valid_period:
            raise WorkspaceError(
                "Missing dependency: Income statement must be completed for at least one period before running organic growth agent."
            )
    elif normalized_agent == "interpretation":
        has_valid_period = any(
            report.balance_sheet_status == "completed"
            and report.income_statement_status == "completed"
            for report in state.reports.values()
        )
        if not has_valid_period:
            raise WorkspaceError(
                "Missing dependency: Both balance sheet and income statement must be completed for at least one period before running interpretation agent."
            )
    elif normalized_agent == "ebita":
        has_valid_period = any(
            report.income_statement_status == "completed"
            for report in state.reports.values()
        )
        if not has_valid_period:
            raise WorkspaceError(
                "Missing dependency: Income statement must be completed for at least one period before running EBITA agent."
            )
    elif normalized_agent == "tax":
        has_valid_period = any(
            report.income_statement_status == "completed"
            for report in state.reports.values()
        )
        if not has_valid_period:
            raise WorkspaceError(
                "Missing dependency: Income statement must be completed for at least one period before running tax agent."
            )

    # Define inner tasks for concurrent execution

    # 1. Extraction Phase (Parallel) Tasks
    async def run_balance_sheet(
        period_key: str, fn: str, content: str, is_q: bool, doc_type: str
    ):
        async with orchestrator.doc_sem:
            orchestrator.checkout_status(ticker, "balance_sheet", period=period_key)
            try:
                res = await asyncio.to_thread(
                    run_extractor_with_learning,
                    agent_fn=bo.run_balance_sheet_agent,
                    agent_name="balance_sheet",
                    doc_type=doc_type,
                    client=orchestrator.client,
                    filename=fn,
                    content=content,
                    company_metadata=state.metadata,
                    learnings=learnings,
                    is_quarterly=is_q,
                )

                # GAAP Override check
                is_formal = doc_type in ("quarterly_filing", "annual_filing")
                cur_state = load_workspace_state(ticker)
                report = cur_state.reports[period_key]

                has_formal_in_source = False
                for sf in report.source_files:
                    for reg_row in registry.values():
                        if reg_row["new_filename"] == sf:
                            if reg_row.get("document_type") in (
                                "quarterly_filing",
                                "annual_filing",
                            ):
                                has_formal_in_source = True
                                break

                should_overwrite = is_formal or not has_formal_in_source

                orchestrator.checkin_status(
                    ticker,
                    "balance_sheet",
                    "completed",
                    period=period_key,
                    payload=res if should_overwrite else None,
                )

                if should_overwrite:
                    # Parse table to line items
                    bs_items = parse_markdown_to_line_items(
                        res.raw_balance_sheet_markdown,
                        orchestrator.client,
                        "current_assets",
                    )

                    # Append to blackboard line items (replacing previous Balance Sheet items)
                    cur_state = load_workspace_state(ticker)
                    report = cur_state.reports[period_key]
                    report.financial_data.line_items = [
                        item
                        for item in report.financial_data.line_items
                        if item.category
                        not in (
                            "current_assets",
                            "noncurrent_assets",
                            "current_liabilities",
                            "noncurrent_liabilities",
                            "equity",
                        )
                    ]
                    report.financial_data.line_items.extend(bs_items)
                    if fn not in report.source_files:
                        report.source_files.append(fn)
                    save_workspace_state(ticker, cur_state)
                else:
                    cur_state = load_workspace_state(ticker)
                    report = cur_state.reports[period_key]
                    if fn not in report.source_files:
                        report.source_files.append(fn)
                    save_workspace_state(ticker, cur_state)
                    logger.info(
                        f"Skipping GAAP override for {fn} as formal filing data is already present."
                    )

                updated_periods.add(period_key)

            except Exception as e:
                logger.error(f"Balance sheet agent failed for {fn}: {e}")
                orchestrator.checkin_status(
                    ticker, "balance_sheet", "failed", period=period_key
                )
                cur_state = load_workspace_state(ticker)
                err_msg = str(e)
                cur_state.reports[period_key].arithmetic_errors.append(
                    f"Balance Sheet Agent failure for {fn}: {err_msg}"
                )
                if fn not in cur_state.reports[period_key].source_files:
                    cur_state.reports[period_key].source_files.append(fn)
                save_workspace_state(ticker, cur_state)
                raise

    async def run_income_statement(
        period_key: str, fn: str, content: str, is_q: bool, doc_type: str
    ):
        async with orchestrator.doc_sem:
            orchestrator.checkout_status(ticker, "income_statement", period=period_key)
            try:
                res = await asyncio.to_thread(
                    run_extractor_with_learning,
                    agent_fn=bo.run_income_statement_agent,
                    agent_name="income_statement",
                    doc_type=doc_type,
                    client=orchestrator.client,
                    filename=fn,
                    content=content,
                    company_metadata=state.metadata,
                    learnings=learnings,
                    is_quarterly=is_q,
                )

                # GAAP Override check
                is_formal = doc_type in ("quarterly_filing", "annual_filing")
                cur_state = load_workspace_state(ticker)
                report = cur_state.reports[period_key]

                has_formal_in_source = False
                for sf in report.source_files:
                    for reg_row in registry.values():
                        if reg_row["new_filename"] == sf:
                            if reg_row.get("document_type") in (
                                "quarterly_filing",
                                "annual_filing",
                            ):
                                has_formal_in_source = True
                                break

                should_overwrite = is_formal or not has_formal_in_source

                orchestrator.checkin_status(
                    ticker,
                    "income_statement",
                    "completed",
                    period=period_key,
                    payload=res if should_overwrite else None,
                )

                if should_overwrite:
                    # Parse table to line items
                    is_items = parse_markdown_to_line_items(
                        res.raw_income_statement_markdown,
                        orchestrator.client,
                        "income_statement",
                    )

                    # Append to blackboard line items (replacing previous Income Statement items)
                    cur_state = load_workspace_state(ticker)
                    report = cur_state.reports[period_key]
                    report.financial_data.line_items = [
                        item
                        for item in report.financial_data.line_items
                        if item.category != "income_statement"
                    ]
                    report.financial_data.line_items.extend(is_items)
                    if fn not in report.source_files:
                        report.source_files.append(fn)
                    save_workspace_state(ticker, cur_state)
                else:
                    cur_state = load_workspace_state(ticker)
                    report = cur_state.reports[period_key]
                    if fn not in report.source_files:
                        report.source_files.append(fn)
                    save_workspace_state(ticker, cur_state)
                    logger.info(
                        f"Skipping GAAP override for {fn} as formal filing data is already present."
                    )

                updated_periods.add(period_key)

            except Exception as e:
                logger.error(f"Income statement agent failed for {fn}: {e}")
                orchestrator.checkin_status(
                    ticker, "income_statement", "failed", period=period_key
                )
                cur_state = load_workspace_state(ticker)
                err_msg = str(e)
                cur_state.reports[period_key].arithmetic_errors.append(
                    f"Income Statement Agent failure for {fn}: {err_msg}"
                )
                if fn not in cur_state.reports[period_key].source_files:
                    cur_state.reports[period_key].source_files.append(fn)
                save_workspace_state(ticker, cur_state)
                raise

    async def run_analyst_report(period_key: str, fn: str, content: str):
        async with orchestrator.doc_sem:
            try:
                res = await asyncio.to_thread(
                    bo.run_analyst_report_agent,
                    client=orchestrator.client,
                    filename=fn,
                    content=content,
                    company_metadata=state.metadata,
                    learnings=learnings,
                )
                # Checkin
                cur_state = load_workspace_state(ticker)
                cur_state.reports[period_key].other_data.analyst_reports.append(res)
                if fn not in cur_state.reports[period_key].source_files:
                    cur_state.reports[period_key].source_files.append(fn)
                save_workspace_state(ticker, cur_state)
                updated_periods.add(period_key)
            except Exception as e:
                logger.error(f"AnalystReportAgent failed for {fn}: {e}")
                raise

    async def run_other_doc(period_key: str, fn: str, content: str):
        async with orchestrator.doc_sem:
            try:
                res = await asyncio.to_thread(
                    bo.run_other_doc_agent,
                    client=orchestrator.client,
                    filename=fn,
                    content=content,
                    company_metadata=state.metadata,
                    learnings=learnings,
                )
                # Checkin
                cur_state = load_workspace_state(ticker)
                cur_state.reports[period_key].other_data.others.append(res)
                if fn not in cur_state.reports[period_key].source_files:
                    cur_state.reports[period_key].source_files.append(fn)
                save_workspace_state(ticker, cur_state)
                updated_periods.add(period_key)
            except Exception as e:
                logger.error(f"OtherDocAgent failed for {fn}: {e}")
                raise

    # 2. Metrics Level 1 (Parallel) Tasks
    async def run_shares_task(period_key: str):
        async with orchestrator.phase_sem:
            cur_state = load_workspace_state(ticker)
            is_q = "Q" in period_key

            registry_rows = periods_docs.get(period_key, [])
            parsed_documents = {}
            for r in registry_rows:
                fn = r["new_filename"]
                doc_path = workspace / "2_parsed_data" / fn
                if doc_path.exists():
                    parsed_documents[fn] = doc_path.read_text(encoding="utf-8")

            orchestrator.checkout_status(ticker, "shares", period=period_key)
            doc_type = get_doc_type_for_period(period_key)
            try:
                basic, diluted = await asyncio.to_thread(
                    run_extractor_with_learning,
                    agent_fn=bo.run_diluted_shares_agent,
                    agent_name="diluted_shares",
                    doc_type=doc_type,
                    client=orchestrator.client,
                    parsed_documents=parsed_documents,
                    company_metadata=state.metadata,
                    workspace_state=cur_state,
                    period_key=period_key,
                    is_quarterly=is_q,
                    learnings=learnings,
                )
                orchestrator.checkin_status(
                    ticker,
                    "shares",
                    "completed",
                    period=period_key,
                    payload=(basic, diluted),
                )
                updated_periods.add(period_key)
            except Exception as e:
                logger.error(f"SharesAgent failed for {period_key}: {e}")
                orchestrator.checkin_status(
                    ticker, "shares", "failed", period=period_key
                )
                raise

    async def run_organic_growth_task(period_key: str):
        async with orchestrator.phase_sem:
            cur_state = load_workspace_state(ticker)
            is_q = "Q" in period_key

            registry_rows = periods_docs.get(period_key, [])
            parsed_documents = {}
            for r in registry_rows:
                fn = r["new_filename"]
                doc_path = workspace / "2_parsed_data" / fn
                if doc_path.exists():
                    parsed_documents[fn] = doc_path.read_text(encoding="utf-8")

            orchestrator.checkout_status(ticker, "organic_growth", period=period_key)
            doc_type = get_doc_type_for_period(period_key)
            try:
                (
                    simple_growth,
                    organic_growth,
                    revenue,
                ) = await asyncio.to_thread(
                    run_extractor_with_learning,
                    agent_fn=bo.run_organic_growth_agent,
                    agent_name="organic_growth",
                    doc_type=doc_type,
                    client=orchestrator.client,
                    parsed_documents=parsed_documents,
                    company_metadata=state.metadata,
                    workspace_state=cur_state,
                    period_key=period_key,
                    is_quarterly=is_q,
                    learnings=learnings,
                )

                # Non-GAAP Preservation
                old_report = cur_state.reports[period_key]
                old_org_growth = old_report.financial_data.organic_growth
                resolved_organic_growth = organic_growth
                if (
                    organic_growth == 0.0 or organic_growth == simple_growth
                ) and old_org_growth != 0.0:
                    resolved_organic_growth = old_org_growth

                orchestrator.checkin_status(
                    ticker,
                    "organic_growth",
                    "completed",
                    period=period_key,
                    payload=(simple_growth, resolved_organic_growth, revenue),
                )
                updated_periods.add(period_key)
            except Exception as e:
                logger.error(f"OrganicGrowthAgent failed for {period_key}: {e}")
                orchestrator.checkin_status(
                    ticker, "organic_growth", "failed", period=period_key
                )
                raise

    async def run_interpretation_task(period_key: str):
        async with orchestrator.phase_sem:
            cur_state = load_workspace_state(ticker)
            report = cur_state.reports[period_key]
            is_q = "Q" in period_key

            if report.financial_data.line_items:
                try:
                    interpreted_items = await asyncio.to_thread(
                        bo.run_interpretation_agent,
                        client=orchestrator.client,
                        extracted_line_items=report.financial_data.line_items,
                        company_metadata=state.metadata,
                        workspace_state=cur_state,
                        period_key=period_key,
                        is_quarterly=is_q,
                        learnings=learnings,
                    )
                    # Update
                    cur_state = load_workspace_state(ticker)
                    cur_state.reports[
                        period_key
                    ].financial_data.line_items = interpreted_items
                    save_workspace_state(ticker, cur_state)
                    updated_periods.add(period_key)
                except Exception as e:
                    logger.error(f"InterpretationAgent failed for {period_key}: {e}")
                    raise

    # 3. Metrics Level 2 (Parallel) Tasks
    async def run_ebita_task(period_key: str):
        async with orchestrator.phase_sem:
            cur_state = load_workspace_state(ticker)
            is_q = "Q" in period_key

            registry_rows = periods_docs.get(period_key, [])
            parsed_documents = {}
            for r in registry_rows:
                fn = r["new_filename"]
                doc_path = workspace / "2_parsed_data" / fn
                if doc_path.exists():
                    parsed_documents[fn] = doc_path.read_text(encoding="utf-8")

            orchestrator.checkout_status(ticker, "ebita", period=period_key)
            doc_type = get_doc_type_for_period(period_key)
            try:
                op_inc, ebita, ebita_adjustments = await asyncio.to_thread(
                    run_extractor_with_learning,
                    agent_fn=bo.run_ebita_agent,
                    agent_name="ebita",
                    doc_type=doc_type,
                    client=orchestrator.client,
                    parsed_documents=parsed_documents,
                    company_metadata=state.metadata,
                    workspace_state=cur_state,
                    period_key=period_key,
                    is_quarterly=is_q,
                    learnings=learnings,
                )

                # Non-GAAP Preservation
                old_report = cur_state.reports[period_key]
                old_ebita = old_report.financial_data.ebita
                old_op_inc = old_report.financial_data.operating_income
                has_old_adjustments = (old_ebita != 0.0) and (old_ebita != old_op_inc)
                has_new_adjustments = (ebita != 0.0) and (ebita != op_inc)

                resolved_ebita = ebita
                resolved_adjustments = ebita_adjustments
                if not has_new_adjustments and has_old_adjustments:
                    resolved_ebita = old_ebita
                    try:
                        resolved_adjustments = json.loads(
                            old_report.financial_data.raw_notes_markdown
                        )
                    except Exception:
                        pass

                orchestrator.checkin_status(
                    ticker,
                    "ebita",
                    "completed",
                    period=period_key,
                    payload=(op_inc, resolved_ebita),
                )

                # Store adjustments in notes/metadata for next agent
                cur_state = load_workspace_state(ticker)
                cur_state.reports[
                    period_key
                ].financial_data.raw_notes_markdown = json.dumps(resolved_adjustments)
                save_workspace_state(ticker, cur_state)
                updated_periods.add(period_key)
            except Exception as e:
                logger.error(f"EbitaAgent failed for {period_key}: {e}")
                orchestrator.checkin_status(
                    ticker, "ebita", "failed", period=period_key
                )
                raise

    async def run_tax_task(period_key: str):
        async with orchestrator.phase_sem:
            cur_state = load_workspace_state(ticker)
            report = cur_state.reports[period_key]
            is_q = "Q" in period_key

            registry_rows = periods_docs.get(period_key, [])
            parsed_documents = {}
            for r in registry_rows:
                fn = r["new_filename"]
                doc_path = workspace / "2_parsed_data" / fn
                if doc_path.exists():
                    parsed_documents[fn] = doc_path.read_text(encoding="utf-8")

            orchestrator.checkout_status(ticker, "tax", period=period_key)
            try:
                # Get ebita adjustments from notes
                ebita_adjustments = []
                notes = report.financial_data.raw_notes_markdown
                if notes:
                    try:
                        ebita_adjustments = json.loads(notes)
                    except Exception:
                        pass

                op_ebita = (
                    report.financial_data.ebita
                    if report.ebita_status == "completed"
                    else 0.0
                )

                doc_type = get_doc_type_for_period(period_key)
                (
                    inc_bt,
                    rep_tax,
                    adj_taxes,
                    tax_adjustments,
                ) = await asyncio.to_thread(
                    run_extractor_with_learning,
                    agent_fn=bo.run_tax_agent,
                    agent_name="tax",
                    doc_type=doc_type,
                    client=orchestrator.client,
                    parsed_documents=parsed_documents,
                    company_metadata=state.metadata,
                    workspace_state=cur_state,
                    period_key=period_key,
                    operating_income=report.financial_data.operating_income,
                    operating_ebita=op_ebita,
                    ebita_adjustments=ebita_adjustments,
                    is_quarterly=is_q,
                    learnings=learnings,
                )

                # Non-GAAP Preservation
                old_report = cur_state.reports[period_key]
                old_rep_tax = old_report.financial_data.reported_tax_provision
                old_adj_tax = old_report.financial_data.adjusted_taxes
                has_old_tax_adj = (old_adj_tax != 0.0) and (old_adj_tax != old_rep_tax)
                has_new_tax_adj = (adj_taxes != 0.0) and (adj_taxes != rep_tax)

                resolved_adj_taxes = adj_taxes
                if not has_new_tax_adj and has_old_tax_adj:
                    resolved_adj_taxes = old_adj_tax

                orchestrator.checkin_status(
                    ticker,
                    "tax",
                    "completed",
                    period=period_key,
                    payload=(inc_bt, rep_tax, resolved_adj_taxes),
                )
                updated_periods.add(period_key)
            except Exception as e:
                logger.error(f"TaxAgent failed for {period_key}: {e}")
                orchestrator.checkin_status(ticker, "tax", "failed", period=period_key)
                raise

    # ----------------------------------------------------
    # Execution Gating & Concurrency
    # ----------------------------------------------------

    extract_tasks = []
    for period_key, doc_rows in periods_docs.items():
        for row in doc_rows:
            fn = row["new_filename"]
            if fn not in selected_filenames:
                continue

            doc_type = row.get("document_type", "other")
            is_q = "Q" in period_key

            doc_path = workspace / "2_parsed_data" / fn
            if not doc_path.exists():
                continue
            content = doc_path.read_text(encoding="utf-8")

            # Check period report lock / status
            report = state.reports[period_key]

            is_formal = doc_type in (
                "quarterly_filing",
                "annual_filing",
                "earnings_announcement",
            )
            if is_formal:
                # Income Statement
                if normalized_agent is None or normalized_agent == "income_statement":
                    if (
                        report.income_statement_status in ("pending", "failed")
                        or (is_formal and fn not in report.source_files)
                        or normalized_agent == "income_statement"
                    ):
                        extract_tasks.append(
                            orchestrator.wrap_task(
                                "income_statement",
                                period_key,
                                fn,
                                lambda pk=period_key,
                                f=fn,
                                c=content,
                                iq=is_q,
                                dt=doc_type: (run_income_statement(pk, f, c, iq, dt)),
                            )
                        )

                # Balance Sheet
                if normalized_agent is None or normalized_agent == "balance_sheet":
                    if (
                        report.balance_sheet_status in ("pending", "failed")
                        or (is_formal and fn not in report.source_files)
                        or normalized_agent == "balance_sheet"
                    ):
                        extract_tasks.append(
                            orchestrator.wrap_task(
                                "balance_sheet",
                                period_key,
                                fn,
                                lambda pk=period_key,
                                f=fn,
                                c=content,
                                iq=is_q,
                                dt=doc_type: (run_balance_sheet(pk, f, c, iq, dt)),
                            )
                        )
            else:
                # Qualitative extractions
                if doc_type == "analyst_report":
                    if normalized_agent is None or normalized_agent == "analyst_report":
                        if fn not in report.source_files:
                            extract_tasks.append(
                                orchestrator.wrap_task(
                                    "analyst_report",
                                    period_key,
                                    fn,
                                    lambda pk=period_key, f=fn, c=content: (
                                        run_analyst_report(pk, f, c)
                                    ),
                                )
                            )
                elif doc_type in (
                    "press_release",
                    "news_article",
                    "transcript",
                    "other",
                ):
                    if normalized_agent is None or normalized_agent == "other":
                        if fn not in report.source_files:
                            extract_tasks.append(
                                orchestrator.wrap_task(
                                    "other",
                                    period_key,
                                    fn,
                                    lambda pk=period_key, f=fn, c=content: (
                                        run_other_doc(pk, f, c)
                                    ),
                                )
                            )

    if extract_tasks:
        await asyncio.gather(*extract_tasks, return_exceptions=True)
        await orchestrator._process_failure_queue(ticker, non_interactive)

    # Reload state to have all latest extractions available for metrics
    state = load_workspace_state(ticker)

    # 2. Metrics Level 1 (Parallel)
    metrics_l1_tasks = []
    for period_key in periods_docs:
        report = state.reports[period_key]

        # A. Diluted Shares Agent
        if normalized_agent is None or normalized_agent == "shares":
            if (
                period_key in periods_to_update
                or report.shares_status in ("pending", "failed")
                or normalized_agent == "shares"
            ):
                if report.income_statement_status == "completed":
                    metrics_l1_tasks.append(
                        orchestrator.wrap_task(
                            "shares",
                            period_key,
                            None,
                            lambda pk=period_key: run_shares_task(pk),
                        )
                    )

        # B. Organic Growth Agent
        if normalized_agent is None or normalized_agent == "organic_growth":
            if (
                period_key in periods_to_update
                or report.organic_growth_status in ("pending", "failed")
                or normalized_agent == "organic_growth"
            ):
                if report.income_statement_status == "completed":
                    metrics_l1_tasks.append(
                        orchestrator.wrap_task(
                            "organic_growth",
                            period_key,
                            None,
                            lambda pk=period_key: run_organic_growth_task(pk),
                        )
                    )

        # C. Interpretation Agent
        if normalized_agent is None or normalized_agent == "interpretation":
            if period_key in periods_to_update or normalized_agent == "interpretation":
                if (
                    report.balance_sheet_status == "completed"
                    and report.income_statement_status == "completed"
                ):
                    metrics_l1_tasks.append(
                        orchestrator.wrap_task(
                            "interpretation",
                            period_key,
                            None,
                            lambda pk=period_key: run_interpretation_task(pk),
                        )
                    )

    if metrics_l1_tasks:
        await asyncio.gather(*metrics_l1_tasks, return_exceptions=True)
        await orchestrator._process_failure_queue(ticker, non_interactive)

    # Reload state to have interpretation outputs available for Metrics Level 2
    state = load_workspace_state(ticker)

    # 3. Metrics Level 2 (Parallel)
    metrics_l2_tasks = []
    for period_key in periods_docs:
        report = state.reports[period_key]

        # Run operating_ebita
        if normalized_agent is None or normalized_agent == "ebita":
            if (
                period_key in periods_to_update
                or report.ebita_status in ("pending", "failed")
                or normalized_agent == "ebita"
            ):
                if report.income_statement_status == "completed":
                    metrics_l2_tasks.append(
                        orchestrator.wrap_task(
                            "ebita",
                            period_key,
                            None,
                            lambda pk=period_key: run_ebita_task(pk),
                        )
                    )

        # Run adjusted_taxes
        if normalized_agent is None or normalized_agent == "tax":
            if (
                period_key in periods_to_update
                or report.tax_status in ("pending", "failed")
                or normalized_agent == "tax"
            ):
                if report.income_statement_status == "completed":
                    metrics_l2_tasks.append(
                        orchestrator.wrap_task(
                            "tax",
                            period_key,
                            None,
                            lambda pk=period_key: run_tax_task(pk),
                        )
                    )

    if metrics_l2_tasks:
        await asyncio.gather(*metrics_l2_tasks, return_exceptions=True)
        await orchestrator._process_failure_queue(ticker, non_interactive)

    # 5. Deterministic Calculations for capital and ROIC
    import src.utils.financial_math as pipeline_math

    cur_state = load_workspace_state(ticker)
    for period_key, report in cur_state.reports.items():
        if normalized_agent and period_key not in updated_periods:
            continue

        if (
            report.balance_sheet_status != "completed"
            or report.income_statement_status != "completed"
        ):
            continue

        try:
            # Calculations
            revenue = report.financial_data.revenue
            ebita = report.financial_data.ebita
            adjusted_tax_rate = report.financial_data.adjusted_tax_rate or 0.21

            is_quarterly = "Q" in period_key
            multiplier = 4.0 if is_quarterly else 1.0

            # Group line items
            oca_items = [
                item
                for item in report.financial_data.line_items
                if item.category == "current_assets" and item.operating
            ]
            ocl_items = [
                item
                for item in report.financial_data.line_items
                if item.category == "current_liabilities" and item.operating
            ]
            onca_items = [
                item
                for item in report.financial_data.line_items
                if item.category == "noncurrent_assets" and item.operating
            ]
            oncl_items = [
                item
                for item in report.financial_data.line_items
                if item.category == "noncurrent_liabilities" and item.operating
            ]

            oca = sum(item.value for item in oca_items)
            ocl = sum(item.value for item in ocl_items)
            onca = sum(item.value for item in onca_items)
            oncl = sum(item.value for item in oncl_items)

            ann_rev = revenue * multiplier
            nwc, nltoa, ic, turnover = pipeline_math.calculate_invested_capital(
                oca, ocl, onca, oncl, ann_rev
            )

            nopat, annualized_nopat, roic = pipeline_math.calculate_roic(
                ebita, adjusted_tax_rate, ic, multiplier
            )

            # Save back
            report.financial_data.net_working_capital = nwc
            report.financial_data.net_long_term_operating_assets = nltoa
            report.financial_data.invested_capital = ic
            report.financial_data.capital_turnover = turnover
            report.financial_data.nopat = nopat
            report.financial_data.roic = roic

        except Exception as e:
            logger.error(f"Deterministic calculations failed for {period_key}: {e}")

    save_workspace_state(ticker, cur_state)
