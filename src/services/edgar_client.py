import datetime
import logging
from pathlib import Path
from typing import List
import httpx

from src.core.config import load_config

logger = logging.getLogger(__name__)


class EdgarClient:
    def __init__(self):
        self.settings = load_config()
        # Set up declared user agent
        self.user_agent = f"{self.settings.project_name} {self.settings.full_name} ({self.settings.email})"
        self.headers = {"User-Agent": self.user_agent}

    def get_cik(self, ticker: str) -> str:
        """Retrieve CIK for a given ticker case-insensitively from the SEC tickers endpoint."""
        url = "https://www.sec.gov/files/company_tickers.json"
        try:
            with httpx.Client(headers=self.headers, timeout=15.0) as client:
                response = client.get(url)
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            raise RuntimeError(f"Failed to fetch SEC ticker database: {str(e)}")

        ticker_upper = ticker.upper()
        for item in data.values():
            if item["ticker"].upper() == ticker_upper:
                return str(item["cik_str"])

        raise ValueError(f"Ticker {ticker} not found in SEC database.")

    def download_filings(self, ticker: str, years: int = 5) -> List[Path]:
        """Download filings (10-K, 10-Q, 20-F) for a ticker to the active workspace."""
        if not self.settings.active_workspace_path:
            raise ValueError(
                "No active workspace is selected. Use 'fa use <ticker>' first."
            )

        # Hard limit to 5 years
        years = min(years, 5)
        cutoff_date = (
            datetime.date.today() - datetime.timedelta(days=years * 365.25)
        ).strftime("%Y-%m-%d")

        cik = self.get_cik(ticker)
        cik_10 = cik.zfill(10)

        submissions_url = f"https://data.sec.gov/submissions/CIK{cik_10}.json"
        try:
            with httpx.Client(headers=self.headers, timeout=15.0) as client:
                response = client.get(submissions_url)
                response.raise_for_status()
                submissions = response.json()
        except Exception as e:
            raise RuntimeError(
                f"Failed to fetch submissions for CIK {cik_10}: {str(e)}"
            )

        recent = submissions.get("filings", {}).get("recent", {})
        if not recent:
            raise ValueError(f"No recent filings found for CIK {cik_10}.")

        # Identify indices matching criteria
        matching_indices = []
        for i, form in enumerate(recent.get("form", [])):
            if form in ["10-K", "10-Q", "20-F"]:
                filing_date = recent["filingDate"][i]
                if filing_date >= cutoff_date:
                    matching_indices.append(i)

        ingest_dir = Path(self.settings.active_workspace_path) / "1_ingest_data"
        ingest_dir.mkdir(parents=True, exist_ok=True)
        downloaded_paths = []

        with httpx.Client(headers=self.headers, timeout=30.0) as client:
            for idx in matching_indices:
                accession = recent["accessionNumber"][idx]
                doc_name = recent["primaryDocument"][idx]
                form = recent["form"][idx]
                filing_date = recent["filingDate"][idx]

                accession_no_dashes = accession.replace("-", "")
                download_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{doc_name}"

                # Determine output path
                # Standard pattern: {accession}_{doc_name}
                safe_doc_name = Path(doc_name).name
                out_path = ingest_dir / f"{accession}_{safe_doc_name}"

                try:
                    logger.info(
                        f"Downloading {form} filed on {filing_date} from {download_url}"
                    )
                    response = client.get(download_url)
                    response.raise_for_status()
                    with open(out_path, "wb") as f:
                        f.write(response.content)
                    downloaded_paths.append(out_path)
                except Exception as e:
                    logger.error(
                        f"Failed to download filing from {download_url}: {str(e)}"
                    )
                    # Continue downloading others even if one fails

        return downloaded_paths
