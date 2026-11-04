from __future__ import annotations

import threading
from typing import Callable, TypeVar

from config import settings

T = TypeVar("T")

_surface_slots = threading.BoundedSemaphore(settings.max_concurrent_surface_jobs)
_video_slots = threading.BoundedSemaphore(settings.max_concurrent_video_jobs)


def run_science_job(function: Callable[..., T], /, *args, job_type: str = "surface") -> T:
    """Run a CPU-bound scientific job off the event loop, bounded by the configured slot count.

    The caller must invoke this through ``asyncio.to_thread`` so the event loop
    stays responsive while jobs queue on the semaphore inside the worker thread.

    Args:
        function: The callable to execute.
        args: Positional arguments to pass to the function.
        job_type: Either "surface" or "video" to determine which semaphore to use.
    """
    semaphore = _video_slots if job_type == "video" else _surface_slots
    with semaphore:
        return function(*args)
