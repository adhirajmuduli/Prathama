from __future__ import annotations

import logging
import os
import ssl
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from dotenv import find_dotenv, load_dotenv
from sqlalchemy import Date, Float, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

load_dotenv(find_dotenv())


def _postgres_ssl_argument(sslmode: str, root_cert: str | None) -> object | None:
    """Map PostgreSQL sslmode semantics onto an asyncpg-compatible ssl argument.

    Returns ``None`` when the mode should fall back to the driver default
    (``allow``/``prefer``/unset), ``False`` for a hard disable, and a tuned
    ``ssl.SSLContext`` otherwise. ``verify-ca``/``verify-full`` validate the
    server certificate against ``sslrootcert`` when provided, else system CAs;
    only ``verify-full`` also checks the hostname.
    """
    if sslmode == "disable":
        return False
    if sslmode in {"", "allow", "prefer"}:
        return None
    # create_default_context (Python 3.10+ secure defaults): verifies the server
    # certificate against the system CAs and checks the hostname by default.
    context = ssl.create_default_context(cafile=root_cert) if root_cert else ssl.create_default_context()
    if sslmode == "require":
        # Encrypted, unauthenticated connection: postgres "require" semantics
        # deliberately skip certificate validation; use verify-full instead.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    if sslmode in {"verify-ca", "verify-full"}:
        context.check_hostname = sslmode == "verify-full"
        context.verify_mode = ssl.CERT_REQUIRED
        return context
    raise RuntimeError(f"Unsupported DATABASE_URL sslmode: '{sslmode}'.")


def _database_configuration() -> tuple[str, dict]:
    configured = os.getenv("DATABASE_URL", "").strip().strip('"').strip("'")
    if not configured:
        configured_path = Path(os.getenv("TRENDSMAPP_DATABASE_PATH", "trendsmapp.db"))
        if not configured_path.is_absolute():
            configured_path = Path(__file__).resolve().parent / configured_path
        configured_path.parent.mkdir(parents=True, exist_ok=True)
        local_path = configured_path.resolve().as_posix()
        return f"sqlite+aiosqlite:///{local_path}", {}

    parsed = urlparse(configured)
    scheme = "postgresql+asyncpg" if parsed.scheme in {"postgres", "postgresql"} else parsed.scheme
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    sslmode = query.pop("sslmode", "").strip().lower()
    root_cert = query.pop("sslrootcert", "").strip() or None
    query.pop("channel_binding", None)
    url = urlunparse(parsed._replace(scheme=scheme, query=urlencode(query)))
    if not scheme.endswith("asyncpg"):
        return url, {}
    ssl_argument = _postgres_ssl_argument(sslmode, root_cert)
    return url, ({} if ssl_argument is None else {"ssl": ssl_argument})


ASYNC_DB_URL, CONNECT_ARGS = _database_configuration()
IS_SQLITE = ASYNC_DB_URL.startswith("sqlite+")
engine_options = {"pool_pre_ping": True, "connect_args": CONNECT_ARGS}
if not IS_SQLITE:
    engine_options.update(pool_size=5, max_overflow=5, pool_recycle=300)
engine = create_async_engine(ASYNC_DB_URL, echo=False, **engine_options)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[str | None] = mapped_column(String, default="Unnamed")
    __table_args__ = (UniqueConstraint("latitude", "longitude", name="uix_station_coordinates"),)


class Parameter(Base):
    __tablename__ = "parameters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)


class Measurement(Base):
    __tablename__ = "measurements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(Integer, ForeignKey("stations.id", ondelete="CASCADE"))
    parameter_id: Mapped[int] = mapped_column(Integer, ForeignKey("parameters.id", ondelete="CASCADE"))
    sampled_at: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    __table_args__ = (
        UniqueConstraint("station_id", "parameter_id", "sampled_at", name="uix_measurement_comb"),
    )


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as database_session:
        try:
            await database_session.execute(select(1))
            yield database_session
            await database_session.commit()
        except Exception:
            await database_session.rollback()
            logging.exception("Database transaction failed")
            raise


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
