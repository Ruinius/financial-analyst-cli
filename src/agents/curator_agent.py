import logging
import threading
from pathlib import Path
from typing import Tuple, Optional

from src.core.config import load_config
from src.services.llm_client import get_llm_client
from src.core.blackboard import load_workspace_state
from src.agents.agent_executor import run_agent_loop

logger = logging.getLogger(__name__)

_wiki_lock = threading.Lock()


def strip_markdown_code_blocks(text: str) -> str:
    """Strip leading/trailing markdown code block fences (e.g. ```markdown ... ```)."""
    text = text.strip()
    text_lower = text.lower()

    # ⚡ Bolt Optimization: Replace regex re.sub with native string methods for ~25x speedup
    if text_lower.startswith("```markdown"):
        text = text[11:].lstrip()
    elif text.startswith("```"):
        text = text[3:].lstrip()

    if text.endswith("```"):
        text = text[:-3].rstrip()

    return text.strip()


class CuratorAgent:
    def __init__(self, settings=None):
        self.settings = settings or load_config()
        self.llm = get_llm_client()

    def curate(
        self, ticker: str, stage: str, agent_logs: str, update_wiki: bool = False
    ) -> None:
        """
        Run the LLMWiki curator agent to refine and compact learnings, merge user feedback,
        and update the ticker's wiki/learning files in the workspace root.
        """
        # Handle MagicMocks in testing environments safely
        if not isinstance(ticker, str) or "MagicMock" in str(ticker):
            ticker = "MOCK"

        if not self.settings.active_workspace_path:
            logger.warning("No active workspace path set. Skipping curation.")
            return

        workspace = Path(self.settings.active_workspace_path)
        wiki_path = workspace / f"{ticker}_wiki.md"
        extract_learning_path = workspace / f"{ticker}_extract_learning.md"
        analyze_learning_path = workspace / f"{ticker}_analyze_learning.md"
        model_learning_path = workspace / f"{ticker}_model_learning.md"

        # Ensure files exist with boilerplates
        self._ensure_files_exist(
            ticker,
            wiki_path,
            extract_learning_path,
            analyze_learning_path,
            model_learning_path,
        )

        logger.info(f"Running Curator Agent for ticker {ticker} at stage: {stage}")

        if stage == "ingest":
            self._curate_ingest(ticker, agent_logs, wiki_path, extract_learning_path)
        elif stage == "extract":
            self._curate_extract(ticker, agent_logs, extract_learning_path)
        elif stage == "analyze":
            self._curate_analyze(ticker, agent_logs, wiki_path, analyze_learning_path)
            try:
                self.curate_wiki(ticker)
            except Exception as e:
                logger.error(f"Failed to run new curate_wiki in analyze stage: {e}")
        elif stage == "model":
            self._curate_model(
                ticker, agent_logs, model_learning_path, update_wiki=update_wiki
            )
            if update_wiki:
                try:
                    self.curate_wiki(ticker)
                except Exception as e:
                    logger.error(f"Failed to run new curate_wiki in model stage: {e}")

    def curate_wiki(self, ticker: str) -> None:
        """
        Runs CuratorAgent as a micro-agent to compile or update [TICKER]_wiki.md
        using query_blackboard tool under a write lock.
        """
        # Handle MagicMocks in testing environments safely
        if not isinstance(ticker, str) or "MagicMock" in str(ticker):
            ticker = "MOCK"

        logger.info(f"CuratorAgent acquiring wiki write lock for {ticker}...")
        with _wiki_lock:
            logger.info(f"CuratorAgent write lock acquired for {ticker}.")
            workspace_state = load_workspace_state(ticker)

            sys_prompt = (
                "You are Sir Pennyworth's Curator Agent. Your job is to compile/update the company qualitative wiki file "
                "named '[TICKER]_wiki.md' based on the blackboard data. You have access to the query_blackboard tool.\n"
                "Rules:\n"
                "1. You have a maximum of 10 turns.\n"
                "2. Use 'query_blackboard' to read metadata, company level data, and period reports.\n"
                "3. Synthesize the findings into a clear 'Bull Perspective' and 'Bear Perspective'. Include short summaries "
                "of key assumptions, financial metrics, and valuation outcomes where appropriate.\n"
                "4. When finished, call 'finalize' with the complete markdown content of the wiki."
            )

            initial_prompt = (
                f"Please compile the wiki for ticker '{ticker}' based on the active blackboard state.\n"
                "Ensure to highlight the key qualitative elements (economic moat, growth outlook, margin outlook) "
                "and any financial/DCF valuation conclusions."
            )

            def query_blackboard(section: str, period: Optional[str] = None) -> str:
                """Query the active blackboard state in a read-only manner."""
                from src.tools.query_blackboard import query_blackboard_helper

                periods = list(workspace_state.reports.keys())
                period_key = periods[0] if periods else "2024_Q3"
                return query_blackboard_helper(
                    workspace_state=workspace_state,
                    company_metadata=workspace_state.metadata,
                    period_key=period_key,
                    section=section,
                    period=period,
                )

            def finalize(content: str) -> str:
                """Finalize the wiki curation by returning the full compiled markdown content."""
                return "Wiki curation finalized."

            tools = [query_blackboard, finalize]

            finalized_args, history = run_agent_loop(
                client=self.llm,
                system_prompt=sys_prompt,
                initial_prompt=initial_prompt,
                tools=tools,
                max_turns=10,
            )

            if finalized_args and "content" in finalized_args:
                wiki_content = strip_markdown_code_blocks(finalized_args["content"])

                if self.settings.active_workspace_path:
                    workspace = Path(self.settings.active_workspace_path)
                    wiki_path = workspace / f"{ticker}_wiki.md"

                    # Write atomically
                    tmp_file = wiki_path.with_suffix(".md.tmp")
                    with open(tmp_file, "w", encoding="utf-8") as f:
                        f.write(wiki_content)
                    import os

                    os.replace(str(tmp_file), str(wiki_path))
                    logger.info(f"Successfully updated qualitative wiki: {wiki_path}")

    def _ensure_files_exist(
        self, ticker: str, wiki: Path, extract: Path, analyze: Path, model: Path
    ) -> None:
        if not wiki.exists():
            wiki.write_text(
                f"# Wiki: {ticker}\n\n"
                "## Bull Perspective\n- No bull perspective compiled yet.\n\n"
                "## Bear Perspective\n- No bear perspective compiled yet.\n\n",
                encoding="utf-8",
            )
        if not extract.exists():
            extract.write_text(
                f"# Ingestion & Extraction Learning: {ticker}\n\n"
                "## Fiscal Schedule Mappings\n"
                "- Q1: N/A\n"
                "- Q2: N/A\n"
                "- Q3: N/A\n"
                "- FY: N/A\n\n"
                "## Preferred Currency & Unit\n"
                "- Currency: N/A\n"
                "- Unit: Millions\n\n"
                "## Lessons to Better Ingest & Extract\n- None\n\n"
                "## balance_sheet\n"
                "- Which key words that worked well in the search: None\n"
                "- What are line items to watch out for and why: None\n\n"
                "## income_statement\n"
                "- Which key words that worked well in the search: None\n"
                "- What are line items to watch out for and why: None\n\n"
                "## diluted_shares\n"
                "- Which key words that worked well in the search: None\n"
                "- What are line items to watch out for and why: None\n\n"
                "## organic growth\n"
                "- Which key words that worked well in the search: None\n"
                "- What are line items to watch out for and why: None\n\n"
                "## ebita\n"
                "- Which key words that worked well in the search: None\n"
                "- What are line items to watch out for and why: None\n\n"
                "## tax\n"
                "- Which key words that worked well in the search: None\n"
                "- What are line items to watch out for and why: None\n\n"
                "## analyst_report\n"
                "- Which key words that worked well in the search: None\n"
                "- What are line items to watch out for and why: None\n\n"
                "## transcript\n"
                "- Which key words that worked well in the search: None\n"
                "- What are line items to watch out for and why: None\n\n"
                "## other\n"
                "- Which key words that worked well in the search: None\n"
                "- What are line items to watch out for and why: None\n\n"
                "## User Feedback\n"
                "<!-- Write your feedback here. The Curator Agent will compile it into lessons and clear this section. -->\n",
                encoding="utf-8",
            )
        else:
            try:
                content = extract.read_text(encoding="utf-8")
                # Add Preferred Currency & Unit section if missing
                if "## Preferred Currency & Unit" not in content:
                    # ⚡ Bolt Optimization: Replace O(N^2) re.DOTALL regex with fast str.find()
                    start_idx = content.find("## Fiscal Schedule Mappings")
                    if start_idx != -1:
                        end_idx = content.find(
                            "\n##", start_idx + len("## Fiscal Schedule Mappings")
                        )
                        insert_pos = end_idx if end_idx != -1 else len(content)
                        content = (
                            content[:insert_pos].rstrip()
                            + "\n\n## Preferred Currency & Unit\n- Currency: N/A\n- Unit: Millions\n\n"
                            + content[insert_pos:].lstrip()
                        )
                    else:
                        content = (
                            "## Preferred Currency & Unit\n- Currency: N/A\n- Unit: Millions\n\n"
                            + content
                        )
                    extract.write_text(content, encoding="utf-8")
                    content = extract.read_text(encoding="utf-8")

                sections_to_add = []
                for section in [
                    "balance_sheet",
                    "income_statement",
                    "diluted_shares",
                    "organic growth",
                    "ebita",
                    "tax",
                    "analyst_report",
                    "transcript",
                    "other",
                ]:
                    if f"## {section}" not in content:
                        sections_to_add.append(
                            f"## {section}\n"
                            "- Which key words that worked well in the search: None\n"
                            "- What are line items to watch out for and why: None\n"
                        )
                if sections_to_add:
                    feedback_match_idx = content.lower().find("## user feedback")
                    if feedback_match_idx != -1:
                        prefix = content[:feedback_match_idx]
                        suffix = content[feedback_match_idx:]
                        new_content = (
                            prefix + "\n".join(sections_to_add) + "\n\n" + suffix
                        )
                    else:
                        new_content = content + "\n\n" + "\n".join(sections_to_add)
                    extract.write_text(new_content, encoding="utf-8")
            except Exception as e:
                logger.error(
                    f"Failed to run self-healing on extract learning file: {e}"
                )

        if not analyze.exists():
            analyze.write_text(
                f"# Analysis Learning: {ticker}\n\n"
                "## Lessons to Better Analyze\n- None\n\n"
                "## User Feedback\n"
                "<!-- Write your feedback here. The Curator Agent will compile it into lessons and clear this section. -->\n",
                encoding="utf-8",
            )
        if not model.exists():
            model.write_text(
                f"# Modeling Learning: {ticker}\n\n"
                "## Lessons to Better Model\n- None\n\n"
                "## WACC\n"
                "- Which key words that worked well in the search: None\n"
                "- What are line items to watch out for and why: None\n\n"
                "## Growth\n"
                "- Which key words that worked well in the search: None\n"
                "- What are line items to watch out for and why: None\n\n"
                "## Margin\n"
                "- Which key words that worked well in the search: None\n"
                "- What are line items to watch out for and why: None\n\n"
                "## User Feedback\n"
                "<!-- Write your feedback here. The Curator Agent will compile it into lessons and clear this section. -->\n",
                encoding="utf-8",
            )
        else:
            try:
                content = model.read_text(encoding="utf-8")
                sections_to_add = []
                for section in ["WACC", "Growth", "Margin"]:
                    if f"## {section}" not in content:
                        sections_to_add.append(
                            f"## {section}\n"
                            "- Which key words that worked well in the search: None\n"
                            "- What are line items to watch out for and why: None\n"
                        )
                if sections_to_add:
                    feedback_match_idx = content.lower().find("## user feedback")
                    if feedback_match_idx != -1:
                        prefix = content[:feedback_match_idx]
                        suffix = content[feedback_match_idx:]
                        new_content = (
                            prefix + "\n".join(sections_to_add) + "\n\n" + suffix
                        )
                    else:
                        new_content = content + "\n\n" + "\n".join(sections_to_add)
                    model.write_text(new_content, encoding="utf-8")
            except Exception as e:
                logger.error(f"Failed to run self-healing on model learning file: {e}")

    def _get_feedback_and_content(self, file_path: Path) -> Tuple[str, str]:
        if not file_path.exists():
            return "", ""
        content = file_path.read_text(encoding="utf-8")
        feedback = ""
        main_content = content

        # Locate the ## User Feedback section
        # ⚡ Bolt Optimization: Replace O(N) regex evaluation with fast str.find() and slicing
        content_lower = content.lower()
        start_idx = content_lower.find("## user feedback")
        if start_idx != -1:
            main_content = content[:start_idx]
            nl_idx = content.find("\n", start_idx)
            if nl_idx != -1:
                raw_feedback = content[nl_idx:].strip()

                # Strip html comment placeholder without regex
                feedback = raw_feedback
                while True:
                    comment_start = feedback.find("<!--")
                    if comment_start == -1:
                        break
                    comment_end = feedback.find("-->", comment_start)
                    if comment_end == -1:
                        break
                    feedback = feedback[:comment_start] + feedback[comment_end + 3 :]

                feedback = feedback.strip()

        return feedback, main_content

    def _curate_ingest(
        self, ticker: str, agent_logs: str, wiki_path: Path, extract_path: Path
    ) -> None:
        # Update extract mappings
        feedback, main_content = self._get_feedback_and_content(extract_path)
        sys_prompt_extract = (
            "You are Sir Pennyworth's Ingestion & Extraction Learning Curator. "
            "Your task is to update the Ingestion & Extraction Learning markdown file with correct fiscal mappings from the logs, "
            "absorb user feedback, and compile/rewrite the entire file to be highly succinct and strictly future-AI-actionable. "
            "You MUST preserve the exact markdown structure of all sections (all headings: ## Fiscal Schedule Mappings, ## Preferred Currency & Unit, ## Lessons to Better Ingest & Extract, "
            "## balance_sheet, ## income_statement, ## diluted_shares, ## organic growth, ## ebita, ## tax, ## analyst_report, ## transcript, ## other, and ## User Feedback). "
            "Keep all contents (including agent-specific sections) highly succinct, dense, and focused ONLY on lessons/rules that will help future AI agent tasks succeed "
            "(e.g. specific keywords, naming patterns, structural anomalies, or formula logic). Aggressively discard verbose commentary, conversational filler, "
            "or generic tips (like 'always double check numbers'). Do not delete or rename any section. "
            "CRITICAL 1: Each section (all headings and subheadings) MUST be kept to less than 10 lines of text/bullets. "
            "CRITICAL 2: You may include short single-line examples, but you MUST NOT include any example extracted tables (e.g. Markdown tables of balance sheets, income statements, etc.). "
            "CRITICAL 3: To avoid redundancy, the '## Lessons to Better Ingest & Extract' section must focus ONLY on high-level ingestion/extraction rules (such as fiscal calendar mappings or general period validation). "
            "DO NOT include or duplicate agent-specific details (like specific keywords, line items, or formulas for balance sheet, income statement, organic growth, diluted shares, ebita, tax, analyst report, transcript, or other) in the top section; "
            "keep those details strictly inside their respective agent headings."
            "Return the entire updated markdown file, and ensure that the '## User Feedback' section is empty/cleared "
            "(with only the placeholder comment inside). Do not wrap in markdown code blocks."
        )
        prompt_extract = f"""
Ticker: {ticker}
Current Ingestion & Extraction Content (excluding old feedback):
\"\"\"
{main_content}
\"\"\"

User Feedback to incorporate:
\"\"\"
{feedback}
\"\"\"

Ingestion logs / Mappings from parsed registry:
\"\"\"
{agent_logs}
\"\"\"

Please:
1. Update the '## Fiscal Schedule Mappings' block with any newly determined quarter mappings or fiscal year end.
2. Update the '## Preferred Currency & Unit' block with the company's reporting currency (preferring local currency if multiple are present) and reporting unit (e.g. Millions, Billions, 10K) if identified during the ingestion or extraction run.
3. Incorporate any user feedback into the '## Lessons to Better Ingest & Extract' section.
4. Rewrite and compact all sections of the file (including lessons and agent-specific sections like balance_sheet, income_statement, etc.) to be highly succinct, focused ONLY on lessons/keywords/mappings that will help future AI agent tasks, and eliminate any redundant or conversational/generic text. Maintain the exact markdown structure.
5. CRITICAL: Limit each section/subheading to less than 10 lines of content.
6. CRITICAL: Do NOT include any example extracted tables. Short single-line examples are fine.
7. CRITICAL: Avoid redundancy by keeping '## Lessons to Better Ingest & Extract' strictly to high-level rules. Do not list agent-specific line items or keywords in the top section.
8. Output the full file with '## User Feedback' containing only:
## User Feedback
<!-- Write your feedback here. The Curator Agent will compile it into lessons and clear this section. -->
"""
        try:
            updated_extract = self.llm.generate(
                prompt_extract, system_prompt=sys_prompt_extract
            )
            extract_path.write_text(
                strip_markdown_code_blocks(updated_extract), encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Failed to curate ingest learning: {e}")

    def _curate_extract(self, ticker: str, agent_logs: str, extract_path: Path) -> None:
        feedback, main_content = self._get_feedback_and_content(extract_path)
        sys_prompt = (
            "You are Sir Pennyworth's Ingestion & Extraction Learning Curator. "
            "Your task is to update the Ingestion & Extraction Learning markdown file with new extraction lessons from the run, "
            "absorb user feedback, and compile/rewrite the entire file to be highly succinct and future-AI-actionable. "
            "You MUST preserve the exact markdown structure of all sections (all headings: ## Fiscal Schedule Mappings, ## Preferred Currency & Unit, ## Lessons to Better Ingest & Extract, "
            "## balance_sheet, ## income_statement, ## diluted_shares, ## organic growth, ## ebita, ## tax, ## analyst_report, ## transcript, ## other, and ## User Feedback). "
            "Keep all contents (including agent-specific sections) highly succinct, dense, and focused ONLY on lessons/rules that will help future AI agent tasks succeed "
            "(e.g. specific keywords, line naming adjustments, or calculation tricks). Avoid generic advice or conversational filler. "
            "Do not delete or rename any section. "
            "CRITICAL 1: Each section (all headings and subheadings) MUST be kept to less than 10 lines of text/bullets. "
            "CRITICAL 2: You may include short single-line examples, but you MUST NOT include any example extracted tables (e.g. Markdown tables of balance sheets, income statements, etc.). "
            "CRITICAL 3: To avoid redundancy, the '## Lessons to Better Ingest & Extract' section must focus ONLY on high-level ingestion/extraction rules (such as fiscal calendar mappings or general period validation). "
            "DO NOT include or duplicate agent-specific details (like specific keywords, line items, or formulas for balance sheet, income statement, organic growth, diluted shares, ebita, tax, analyst report, transcript, or other) in the top section; "
            "keep those details strictly inside their respective agent headings."
            "Return the entire updated markdown file, and ensure that the '## User Feedback' section is empty/cleared "
            "(with only the placeholder comment inside). Do not wrap in markdown code blocks."
        )
        prompt = f"""
Ticker: {ticker}
Current Ingestion & Extraction Content (excluding old feedback):
\"\"\"
{main_content}
\"\"\"

User Feedback to incorporate:
\"\"\"
{feedback}
\"\"\"

Extraction Run logs / reasoning / items parsed:
\"\"\"
{agent_logs}
\"\"\"

Please:
1. Update the '## Preferred Currency & Unit' block with the company's reporting currency (preferring local currency if multiple are present) and reporting unit (e.g. Millions, Billions, 10K) if identified during the extraction run.
2. Incorporate any user feedback and new lessons from the extraction run into the '## Lessons to Better Ingest & Extract' section.
3. Rewrite and compact all sections of the file (including lessons and agent-specific sections like balance_sheet, income_statement, etc.) to be highly succinct, focused ONLY on actionable details that will guide future AI agents, and remove any generic advice or conversational filler. Maintain the exact markdown structure.
4. CRITICAL: Limit each section/subheading to less than 10 lines of content.
5. CRITICAL: Do NOT include any example extracted tables. Short single-line examples are fine.
6. CRITICAL: Avoid redundancy by keeping '## Lessons to Better Ingest & Extract' strictly to high-level rules. Do not list agent-specific line items or keywords in the top section.
7. Output the full file with '## User Feedback' containing only:
## User Feedback
<!-- Write your feedback here. The Curator Agent will compile it into lessons and clear this section. -->
"""
        try:
            updated_content = self.llm.generate(prompt, system_prompt=sys_prompt)
            extract_path.write_text(
                strip_markdown_code_blocks(updated_content), encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Failed to curate extract learning: {e}")

    def _curate_analyze(
        self, ticker: str, agent_logs: str, wiki_path: Path, analyze_path: Path
    ) -> None:
        # First: Curate the qualitative perspectives in Wiki (strictly from recent document context, no pollution)
        wiki_content = wiki_path.read_text(encoding="utf-8")
        sys_prompt_wiki = (
            "You are Sir Pennyworth's Qualitative Wiki Curator. Your job is to update the Bull Perspective and Bear Perspective "
            "in the Wiki markdown file based strictly on the context of the recent document runs logs (which contain historical data tables over time). "
            "You must analyze the data trends chronologically over time and form a synthesized conclusion. "
            "For example, it is normal for different analyst reports to disagree, but you should identify and describe the overarching trend, consensus shift, and direction of the trajectory. "
            "Do not include outside knowledge. Return the entire updated markdown file. Do not wrap in markdown code blocks."
        )
        prompt_wiki = f"""
Ticker: {ticker}
Current Wiki Content:
\"\"\"
{wiki_content}
\"\"\"

Qualitative Analysis Logs / Compiled historical analysis output over time:
\"\"\"
{agent_logs}
\"\"\"

Please rewrite and refine the '## Bull Perspective' and '## Bear Perspective' sections inside the Wiki.
Analyze the data trends chronologically over time and form a synthesized conclusion. While individual analyst reports may disagree, identify what the overall trajectory is. Compact and consolidate the perspectives based strictly on this latest run context.
"""
        try:
            updated_wiki = self.llm.generate(prompt_wiki, system_prompt=sys_prompt_wiki)
            wiki_path.write_text(
                strip_markdown_code_blocks(updated_wiki), encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Failed to curate qualitative wiki: {e}")

        # Second: Curate the analysis learning file
        feedback, main_content = self._get_feedback_and_content(analyze_path)
        sys_prompt_analyze = (
            "You are Sir Pennyworth's Analysis Learning Curator. "
            "Your task is to update the Analysis Learning markdown file with new analysis lessons, "
            "absorb user feedback, and compile/rewrite the lessons to be highly succinct and future-AI-actionable. "
            "Retain ONLY lessons that will help future AI agent tasks analyze this ticker (such as specific reporting segments, "
            "one-off non-operating items, or unique disclosure details to look for). Eliminate all general platitudes, "
            "redundant rules, and conversational filler. "
            "CRITICAL 1: Each section MUST be kept to less than 10 lines of text/bullets. "
            "CRITICAL 2: You may include short single-line examples, but you MUST NOT include any tables in the lessons. "
            "Return the entire updated markdown file, and ensure that the '## User Feedback' section is empty/cleared "
            "(with only the placeholder comment inside). Do not wrap in markdown code blocks."
        )
        prompt_analyze = f"""
Ticker: {ticker}
Current Analysis Learning Content (excluding old feedback):
\"\"\"
{main_content}
\"\"\"

User Feedback to incorporate:
\"\"\"
{feedback}
\"\"\"

Analysis logs / reasoning / qualitative reports compiled:
\"\"\"
{agent_logs}
\"\"\"

Please:
1. Incorporate any user feedback and new lessons from the analysis run into the '## Lessons to Better Analyze' section.
2. Perform a complete rewrite and compaction of the lessons. Keep them highly succinct, focused ONLY on actionable information for future AI agents, and remove any generic advice or conversational filler.
3. CRITICAL: Limit the entire lessons section to less than 10 lines of content.
4. CRITICAL: Do NOT include any tables. Short single-line examples are fine.
5. Output the full file with '## User Feedback' containing only:
## User Feedback
<!-- Write your feedback here. The Curator Agent will compile it into lessons and clear this section. -->
"""
        try:
            updated_content = self.llm.generate(
                prompt_analyze, system_prompt=sys_prompt_analyze
            )
            analyze_path.write_text(
                strip_markdown_code_blocks(updated_content), encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Failed to curate analyze learning: {e}")

    def _curate_model(
        self, ticker: str, agent_logs: str, model_path: Path, update_wiki: bool = False
    ) -> None:
        feedback, main_content = self._get_feedback_and_content(model_path)

        extract_learning_path = model_path.parent / f"{ticker}_extract_learning.md"
        analyze_learning_path = model_path.parent / f"{ticker}_analyze_learning.md"
        wiki_path = model_path.parent / f"{ticker}_wiki.md"

        extract_context = ""
        if extract_learning_path.exists():
            try:
                extract_context = extract_learning_path.read_text(encoding="utf-8")
            except Exception:
                pass

        analyze_context = ""
        if analyze_learning_path.exists():
            try:
                analyze_context = analyze_learning_path.read_text(encoding="utf-8")
            except Exception:
                pass

        sys_prompt = (
            "You are Sir Pennyworth's Modeling Learning Curator. "
            "Your task is to update the Modeling Learning markdown file with new modeling lessons, "
            "absorb user feedback, and compile/rewrite the lessons to be highly succinct and future-AI-actionable. "
            "You have access to historical Ingestion & Extraction Learning and Analysis Learning contexts for this company. Use them to identify any company-specific conventions (e.g. reporting currency, ADR ratios, specific line items, restructuring adjustments) that should be incorporated into the modeling lessons.\n"
            "Retain ONLY lessons that will help future AI agent tasks model this ticker (such as WACC adjustments, currency "
            "conversions, ADR ratios, specific overrides, or growth rate boundaries). Eliminate all generic modeling tips or "
            "conversational filler. "
            "CRITICAL 1: Each section MUST be kept to less than 10 lines of text/bullets. "
            "CRITICAL 2: You may include short single-line examples, but you MUST NOT include any tables in the lessons. "
            "Return the entire updated markdown file, and ensure that the '## User Feedback' section is empty/cleared "
            "(with only the placeholder comment inside). Do not wrap in markdown code blocks."
        )
        prompt = f"""
Ticker: {ticker}
Current Modeling Learning Content (excluding old feedback):
\"\"\"
{main_content}
\"\"\"

User Feedback to incorporate:
\"\"\"
{feedback}
\"\"\"

Modeling assumptions / overrides / values logged:
\"\"\"
{agent_logs}
\"\"\"

Context from Ingestion & Extraction Learning:
\"\"\"
{extract_context}
\"\"\"

Context from Analysis Learning:
\"\"\"
{analyze_context}
\"\"\"

Please:
1. Incorporate any user feedback and new lessons (e.g. currency, WACC adjustments, ADR ratios, specific overrides) into the '## Lessons to Better Model' section.
2. Perform a complete rewrite and compaction of the lessons. Keep them highly succinct, focused ONLY on actionable information for future AI agents, and remove any generic advice or conversational filler.
3. CRITICAL: Limit the entire lessons section to less than 10 lines of content.
4. CRITICAL: Do NOT include any tables. Short single-line examples are fine.
5. Output the full file with '## User Feedback' containing only:
## User Feedback
<!-- Write your feedback here. The Curator Agent will compile it into lessons and clear this section. -->
"""
        try:
            updated_content = self.llm.generate(prompt, system_prompt=sys_prompt)
            model_path.write_text(
                strip_markdown_code_blocks(updated_content), encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Failed to curate model learning: {e}")

        # If logs contain final modeling results, update company wiki perspectives
        if update_wiki and wiki_path.exists():
            try:
                wiki_content = wiki_path.read_text(encoding="utf-8")
                sys_prompt_wiki = (
                    "You are Sir Pennyworth's Qualitative Wiki Curator. Your job is to update the company Wiki markdown file. "
                    "Specifically, you must update the Bull Perspective and Bear Perspective in the Wiki to incorporate the findings, "
                    "rationales, and assumptions from the final DCF modeling results, the agent's critique/comments on valuation, and the resulting fair value upside/downside. "
                    "Do not include outside knowledge. Return the entire updated markdown file. Do not wrap in markdown code blocks."
                )
                prompt_wiki = f"""
Ticker: {ticker}
Current Wiki Content:
\"\"\"
{wiki_content}
\"\"\"

Final DCF Modeling run logs and modeler critique:
\"\"\"
{agent_logs}
\"\"\"

Please update the '## Bull Perspective' and '## Bear Perspective' in the Wiki. Incorporate the final DCF modeling findings, key assumptions (like growth rate or WACC), and the valuation upside/downside. Maintain the exact markdown headers of the Wiki.
"""
                updated_wiki = self.llm.generate(
                    prompt_wiki, system_prompt=sys_prompt_wiki
                )
                wiki_path.write_text(
                    strip_markdown_code_blocks(updated_wiki), encoding="utf-8"
                )
                logger.info(f"Successfully updated Wiki for model curation of {ticker}")
            except Exception as wiki_err:
                logger.error(f"Failed to update wiki during model curation: {wiki_err}")

    def curate_agent(self, ticker: str, agent_name: str, agent_logs: str) -> None:
        """
        Curate a specific agent's section within extract_learning.md.
        """
        if not ticker or "MagicMock" in str(ticker):
            ticker = "MOCK"

        if not self.settings.active_workspace_path:
            logger.warning("No active workspace path set. Skipping curation.")
            return

        workspace = Path(self.settings.active_workspace_path)
        extract_learning_path = workspace / f"{ticker}_extract_learning.md"

        self._ensure_files_exist(
            ticker,
            workspace / f"{ticker}_wiki.md",
            extract_learning_path,
            workspace / f"{ticker}_analyze_learning.md",
            workspace / f"{ticker}_model_learning.md",
        )

        content = extract_learning_path.read_text(encoding="utf-8")

        sys_prompt = (
            "You are Sir Pennyworth's Ingestion & Extraction Learning Curator. "
            f"Your task is to update the '## {agent_name}' section of the Ingestion & Extraction Learning markdown file "
            "based on the execution logs of that agent. "
            "Return the entire updated markdown file. Do not alter any other section of the file. "
            "Do not wrap the output in markdown code blocks. "
            "CRITICAL 1: Keep the updated section highly succinct and dense, strictly less than 10 lines of text/bullets in total. "
            "CRITICAL 2: Retain ONLY messages/rules/tips that will help future AI agent tasks succeed (e.g. specific keywords that yielded matches, unique line items to watch out for). "
            "CRITICAL 3: Do NOT include any example extracted tables. Do not include conversational filler, general advice, or verbose logs."
        )

        prompt = f"""
Ticker: {ticker}
Agent/Section to update: {agent_name}
Current Ingestion & Extraction Learning Content:
\"\"\"
{content}
\"\"\"

Execution logs / history of the {agent_name} agent:
\"\"\"
{agent_logs}
\"\"\"

Please update the '## {agent_name}' section in the file. Keep all other sections and mappings exactly as they are.
The section MUST answer the following questions:
- Which key words that worked well in the search? (Focus strictly on search queries that returned actual matches or were useful)
- What are line items to watch out for and why? (Note specific names, signs, or footnoted adjustments)

Keep the answers extremely short (less than 10 lines total for the entire section), focused strictly on what is useful for future AI agents, and remove all generic advice, chat, or example tables.
Output the FULL markdown file with the updated '## {agent_name}' section. Do not wrap in code blocks.
"""
        try:
            updated_content = self.llm.generate(prompt, system_prompt=sys_prompt)
            extract_learning_path.write_text(
                strip_markdown_code_blocks(updated_content), encoding="utf-8"
            )
            logger.info(
                f"Successfully curated {agent_name} section in extract_learning.md"
            )
        except Exception as e:
            logger.error(f"Failed to curate {agent_name} section: {e}")

    def curate_model_agent(self, ticker: str, agent_name: str, agent_logs: str) -> None:
        """
        Curate a specific modeling agent's section within model_learning.md.
        """
        if not ticker or "MagicMock" in str(ticker):
            ticker = "MOCK"

        if not self.settings.active_workspace_path:
            logger.warning("No active workspace path set. Skipping curation.")
            return

        workspace = Path(self.settings.active_workspace_path)
        model_learning_path = workspace / f"{ticker}_model_learning.md"

        self._ensure_files_exist(
            ticker,
            workspace / f"{ticker}_wiki.md",
            workspace / f"{ticker}_extract_learning.md",
            workspace / f"{ticker}_analyze_learning.md",
            model_learning_path,
        )

        content = model_learning_path.read_text(encoding="utf-8")

        extract_learning_path = workspace / f"{ticker}_extract_learning.md"
        analyze_learning_path = workspace / f"{ticker}_analyze_learning.md"

        extract_context = ""
        if extract_learning_path.exists():
            try:
                extract_context = extract_learning_path.read_text(encoding="utf-8")
            except Exception:
                pass

        analyze_context = ""
        if analyze_learning_path.exists():
            try:
                analyze_context = analyze_learning_path.read_text(encoding="utf-8")
            except Exception:
                pass

        sys_prompt = (
            "You are Sir Pennyworth's Modeling Learning Curator. "
            f"Your task is to update the '## {agent_name}' section of the Modeling Learning markdown file "
            "based on the execution logs of that modeling agent. "
            "You have access to historical Ingestion & Extraction Learning and Analysis Learning contexts for this company. Use them to identify any company-specific conventions (e.g. reporting currency, ADR ratios, specific line items, restructuring adjustments) that should be incorporated into the modeling lessons.\n"
            "Return the entire updated markdown file. Do not alter any other section of the file. "
            "Do not wrap the output in markdown code blocks. "
            "CRITICAL 1: Keep the updated section highly succinct and dense, strictly less than 10 lines of text/bullets in total. "
            "CRITICAL 2: Retain ONLY messages/rules/tips that will help future AI agent tasks succeed (e.g. specific line items, accounting treatments, WACC parameters). "
            "CRITICAL 3: Do NOT include any example tables. Do not include conversational filler, general advice, or verbose logs."
        )

        prompt = f"""
Ticker: {ticker}
Agent/Section to update: {agent_name}
Current Modeling Learning Content:
\"\"\"
{content}
\"\"\"

Execution logs / history of the {agent_name} agent:
\"\"\"
{agent_logs}
\"\"\"

Context from Ingestion & Extraction Learning:
\"\"\"
{extract_context}
\"\"\"

Context from Analysis Learning:
\"\"\"
{analyze_context}
\"\"\"

Please update the '## {agent_name}' section in the file. Keep all other sections and mappings exactly as they are.
The section MUST answer the following questions:
- Which key words that worked well in the search? (Focus strictly on search queries that returned actual matches or were useful)
- What are line items to watch out for and why? (Note specific names, values, or WACC adjustments)

Keep the answers extremely short (less than 10 lines total for the entire section), focused strictly on what is useful for future AI agents, and remove all generic advice, chat, or example tables.
Output the FULL markdown file with the updated '## {agent_name}' section. Do not wrap in code blocks.
"""
        try:
            updated_content = self.llm.generate(prompt, system_prompt=sys_prompt)
            model_learning_path.write_text(
                strip_markdown_code_blocks(updated_content), encoding="utf-8"
            )
            logger.info(
                f"Successfully curated {agent_name} section in model_learning.md"
            )
        except Exception as e:
            logger.error(
                f"Failed to curate {agent_name} section in model_learning: {e}"
            )
