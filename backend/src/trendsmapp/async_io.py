"""Blocking file I/O kept off the event loop.

Worker handlers are async, but spooling a raw upload to a seekable local file
is blocking disk work. Constructing and closing the spool therefore happens
through :func:`run_blocking` (``asyncio.to_thread``), never inline in an async
function.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Callable
from typing import BinaryIO, cast

__all__ = ["new_spool", "run_blocking"]


async def run_blocking[T](func: Callable[[], T]) -> T:
    """Run a blocking callable in a worker thread and return its result."""
    return await asyncio.to_thread(func)


def new_spool() -> BinaryIO:
    """Create a seekable local spool file.

    Blocking: call through :func:`run_blocking` from async code.
    """
    return cast(BinaryIO, tempfile.TemporaryFile())
