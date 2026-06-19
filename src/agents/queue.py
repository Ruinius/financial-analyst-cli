import time
import logging
from typing import Callable, List, Tuple, Dict, Any

logger = logging.getLogger(__name__)


class JobQueue:
    def __init__(
        self, retries: int = 3, initial_delay: float = 1.0, backoff: float = 2.0
    ):
        self.jobs: List[Tuple[Callable[..., Any], Tuple[Any, ...], Dict[str, Any]]] = []
        self.retries = retries
        self.initial_delay = initial_delay
        self.backoff = backoff

    def add_job(self, func: Callable[..., Any], *args, **kwargs) -> None:
        """Add a job function with its arguments to the queue."""
        self.jobs.append((func, args, kwargs))

    def run(self) -> List[Any]:
        """Execute all queued jobs sequentially with retry and back-off logic."""
        results = []
        try:
            for idx, (func, args, kwargs) in enumerate(self.jobs):
                delay = self.initial_delay
                success = False
                last_exception = None

                for attempt in range(self.retries + 1):
                    try:
                        logger.info(
                            f"Running job {idx + 1}/{len(self.jobs)}: {func.__name__} (Attempt {attempt + 1})"
                        )
                        result = func(*args, **kwargs)
                        results.append(result)
                        success = True
                        break
                    except Exception as e:
                        last_exception = e
                        if attempt < self.retries:
                            logger.warning(
                                f"Job {func.__name__} failed: {str(e)}. "
                                f"Retrying in {delay:.1f}s..."
                            )
                            time.sleep(delay)
                            delay *= self.backoff
                        else:
                            logger.error(
                                f"Job {func.__name__} failed permanently on attempt {attempt + 1}. "
                                f"Error: {str(e)}"
                            )

                if not success:
                    raise last_exception or RuntimeError(
                        f"Job {func.__name__} failed permanently."
                    )
        except KeyboardInterrupt:
            logger.warning("Queue execution interrupted by user (Ctrl+C).")
            self.jobs = []
            raise

        # Clear queue after execution
        self.jobs = []
        return results
