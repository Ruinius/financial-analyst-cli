import re
import logging
from pathlib import Path
from typing import Tuple

from src.core.config import load_config
from src.services.llm_client import LLMClient

logger = logging.getLogger(__name__)


def strip_markdown_code_blocks(text: str) -> str:
    """Strip leading/trailing markdown code block fences (e.g. ```markdown ... ```)."""
    text = text.strip()
    # Remove leading ```markdown or ```
    text = re.sub(r"^```(?:markdown)?\s*", "", text, flags=re.IGNORECASE)
    # Remove trailing ```
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


class CuratorAgent:
    def __init__(self, settings=None):
        self.settings = settings or load_config()
        self.llm = LLMClient()

    def curate(self, ticker: str, stage: str, agent_logs: str) -> None:
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
        elif stage == "model":
            self._curate_model(ticker, agent_logs, model_learning_path)

    def _ensure_files_exist(
        self, ticker: str, wiki: Path, extract: Path, analyze: Path, model: Path
    ) -> None:
        if not wiki.exists():
            wiki.write_text(
                f"# Wiki: {ticker}\n\n"
                "## Bull Perspective\n- No bull perspective compiled yet.\n\n"
                "## Bear Perspective\n- No bear perspective compiled yet.\n\n"
                "## Ingested Sources\n- None\n",
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
                "## Lessons to Better Ingest & Extract\n- None\n\n"
                "## User Feedback\n"
                "<!-- Write your feedback here. The Curator Agent will compile it into lessons and clear this section. -->\n",
                encoding="utf-8",
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
                "## User Feedback\n"
                "<!-- Write your feedback here. The Curator Agent will compile it into lessons and clear this section. -->\n",
                encoding="utf-8",
            )

    def _get_feedback_and_content(self, file_path: Path) -> Tuple[str, str]:
        if not file_path.exists():
            return "", ""
        content = file_path.read_text(encoding="utf-8")
        feedback = ""
        main_content = content

        # Locate the ## User Feedback section
        match = re.search(
            r"## User Feedback\s*\n(.*)", content, re.DOTALL | re.IGNORECASE
        )
        if match:
            raw_feedback = match.group(1).strip()
            # Strip html comment placeholder
            feedback = re.sub(r"<!--.*?-->", "", raw_feedback, flags=re.DOTALL).strip()
            # Extract main content before the User Feedback section
            main_content = content[: match.start()]

        return feedback, main_content

    def _curate_ingest(
        self, ticker: str, agent_logs: str, wiki_path: Path, extract_path: Path
    ) -> None:
        # Update wiki sources registry
        wiki_content = wiki_path.read_text(encoding="utf-8")
        sys_prompt_wiki = (
            "You are Sir Pennyworth's Wiki Curator Agent. Update the list of Ingested Sources in the Wiki markdown content. "
            "Return the entire updated markdown file. Do not wrap in markdown code blocks."
        )
        prompt_wiki = f"""
Ticker: {ticker}
Current Wiki Content:
\"\"\"
{wiki_content}
\"\"\"

Ingestion logs / New files processed:
\"\"\"
{agent_logs}
\"\"\"

Please append the newly ingested files to the '## Ingested Sources' list. Do not duplicate if they are already in the list. Keep everything else unchanged.
"""
        try:
            updated_wiki = self.llm.generate(prompt_wiki, system_prompt=sys_prompt_wiki)
            wiki_path.write_text(
                strip_markdown_code_blocks(updated_wiki), encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Failed to update Ingested Sources in wiki: {e}")

        # Update extract mappings
        feedback, main_content = self._get_feedback_and_content(extract_path)
        sys_prompt_extract = (
            "You are Sir Pennyworth's Ingestion & Extraction Learning Curator. "
            "Your task is to update the Ingestion & Extraction Learning markdown file with correct fiscal mappings from the logs, "
            "absorb user feedback, and compile/rewrite the lessons to be concise and accurate. "
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
2. Incorporate any user feedback into the '## Lessons to Better Ingest & Extract' section.
3. Perform a complete rewrite and compaction of the lessons, keeping it concise and removing outdated or incorrect rules.
4. Output the full file with '## User Feedback' containing only:
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
            "absorb user feedback, and compact the lessons. "
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
1. Incorporate any user feedback and new lessons from the extraction run into the '## Lessons to Better Ingest & Extract' section.
2. Perform a complete rewrite and compaction of the lessons, keeping it concise and removing outdated or incorrect rules.
3. Output the full file with '## User Feedback' containing only:
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
            "in the Wiki markdown file based strictly on the context of the recent document runs logs. Do not include outside knowledge. "
            "Return the entire updated markdown file. Do not wrap in markdown code blocks."
        )
        prompt_wiki = f"""
Ticker: {ticker}
Current Wiki Content:
\"\"\"
{wiki_content}
\"\"\"

Qualitative Analysis Logs / Summarized views from the run:
\"\"\"
{agent_logs}
\"\"\"

Please rewrite and refine the '## Bull Perspective' and '## Bear Perspective' sections inside the Wiki. Compract and consolidate them based strictly on this latest run context.
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
            "absorb user feedback, and compact the lessons. "
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
2. Perform a complete rewrite and compaction of the lessons, keeping it concise and removing outdated or incorrect rules.
3. Output the full file with '## User Feedback' containing only:
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

    def _curate_model(self, ticker: str, agent_logs: str, model_path: Path) -> None:
        feedback, main_content = self._get_feedback_and_content(model_path)
        sys_prompt = (
            "You are Sir Pennyworth's Modeling Learning Curator. "
            "Your task is to update the Modeling Learning markdown file with new modeling lessons, "
            "absorb user feedback, and compact the lessons. "
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

Please:
1. Incorporate any user feedback and new lessons (e.g. currency, WACC adjustments, ADR ratios) into the '## Lessons to Better Model' section.
2. Perform a complete rewrite and compaction of the lessons, keeping it concise and removing outdated or incorrect rules.
3. Output the full file with '## User Feedback' containing only:
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
