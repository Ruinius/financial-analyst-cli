import asyncio
import logging
from pathlib import Path
from src.core.blackboard import load_workspace_state

logger = logging.getLogger(__name__)


async def orchestrate_ingest(orchestrator, ticker: str) -> None:
    from src.agents.ingester import Ingester, compute_sha256

    ingester = Ingester()
    settings = orchestrator.settings
    workspace = Path(settings.active_workspace_path)
    if not workspace.exists():
        return

    ingest_dir = workspace / "1_ingest_data"
    if not ingest_dir.exists():
        return

    raw_files = [
        p
        for p in ingest_dir.iterdir()
        if p.is_file() and p.name.lower() != "readme.md" and not p.name.startswith(".")
    ]

    if not raw_files:
        return

    registry = ingester.load_parsed_registry()

    for raw_file in raw_files:
        file_hash = compute_sha256(raw_file)
        state = load_workspace_state(ticker)
        is_processed = any(
            doc.file_name == raw_file.name and doc.ingestion_status == "completed"
            for doc in state.raw_documents
        )
        if is_processed or file_hash in registry:
            continue

        orchestrator.checkout_status(ticker, "ingestion", file_name=raw_file.name)
        try:
            await asyncio.to_thread(ingester.ingest_single_file, raw_file, registry)
            orchestrator.checkin_status(
                ticker,
                "ingestion",
                "completed",
                file_name=raw_file.name,
                payload={"sha256": file_hash},
            )
        except Exception as e:
            logger.error(f"Ingestion failed for {raw_file.name}: {e}")
            orchestrator.checkin_status(
                ticker, "ingestion", "failed", file_name=raw_file.name
            )

    ingester.save_parsed_registry(registry)
