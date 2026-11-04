from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

KNOWN_INSECURE_SECRET_KEYS = frozenset({
    "trendsmapp-local-development-key",
    "reviewer-local-secret-change-before-deployment",
})


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean value.")


def _positive_integer(name: str, default: int) -> int:
    value = int(os.getenv(name, default))
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero.")
    return value


def _nonnegative_number(name: str, default: float) -> float:
    value = float(os.getenv(name, default))
    if value < 0 or value != value:
        raise RuntimeError(f"{name} must be zero or a positive number.")
    return value


def _nonempty_text(name: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else ""


@dataclass(frozen=True)
class Settings:
    """Validated process configuration shared by the prototype web and scientific layers."""

    root: Path
    secret_key: str
    _ephemeral_secret_at_init: bool
    _https_only_at_init: bool
    # auth_token is a property that reads from environment dynamically
    demo_mode: bool
    demo_dataset: Path
    max_upload_bytes: int
    max_processed_rows: int
    max_timestamps: int
    max_stations_per_frame: int
    max_concurrent_jobs: int
    max_concurrent_surface_jobs: int
    max_concurrent_video_jobs: int
    upload_ttl_hours: float
    max_video_frames: int
    surface_resolution: int
    animation_resolution: int

    # Store the raw auth_token from env at creation time for backward compat
    _auth_token_at_init: str = field(default="", repr=False)

    @property
    def auth_token(self) -> str:
        """Dynamically read the auth token from environment."""
        return os.getenv("TRENDSMAPP_AUTH_TOKEN", "").strip() or self._auth_token_at_init

    @property
    def https_only(self) -> bool:
        """Dynamically read HTTPS_ONLY from environment."""
        return _boolean("TRENDSMAPP_HTTPS_ONLY", False)

    @property
    def ephemeral_secret(self) -> bool:
        """Dynamically check if we're using an ephemeral secret."""
        return not bool(os.getenv("SECRET_KEY", "").strip())

    @property
    def secret_is_ephemeral(self) -> bool:
        """Backward compatibility alias for ephemeral_secret."""
        return self.ephemeral_secret

    @classmethod
    def from_environment(cls) -> "Settings":
        root = Path(__file__).resolve().parent
        demo_value = os.getenv("TRENDSMAPP_DEMO_DATASET", "examples/chilika_demo.xlsx")
        demo_path = Path(demo_value)
        if not demo_path.is_absolute():
            demo_path = root / demo_path

        https_only = _boolean("TRENDSMAPP_HTTPS_ONLY", False)
        explicit_secret = _nonempty_text("SECRET_KEY")
        if explicit_secret:
            secret_key = explicit_secret
            ephemeral_secret = False
            if len(secret_key) < 32:
                logger.warning(
                    "SECRET_KEY length is %d characters; recommended minimum is 32. "
                    "Consider using a longer random value.",
                    len(secret_key)
                )
        else:
            secret_key = secrets.token_urlsafe(48)
            ephemeral_secret = True
            # Persist generated key so sessions survive restarts
            secret_file = root / ".secret"
            secret_file.write_text(secret_key)
            secret_file.chmod(0o600)
            logger.warning(
                "SECRET_KEY is not set; an ephemeral key was generated for this process. "
                "Signed sessions reset on every restart. Set SECRET_KEY for stable sessions."
            )

        settings = cls(
            root=root,
            secret_key=secret_key,
            _ephemeral_secret_at_init=ephemeral_secret,
            _https_only_at_init=https_only,
            _auth_token_at_init=_nonempty_text("TRENDSMAPP_AUTH_TOKEN"),
            demo_mode=_boolean("TRENDSMAPP_DEMO_MODE", True),
            demo_dataset=demo_path.resolve(),
            max_upload_bytes=_positive_integer("TRENDSMAPP_MAX_UPLOAD_BYTES", 50 * 1024 * 1024),
            max_processed_rows=_positive_integer("TRENDSMAPP_MAX_PROCESSED_ROWS", 100_000),
            max_timestamps=_positive_integer("TRENDSMAPP_MAX_TIMESTAMPS", 100),
            max_stations_per_frame=_positive_integer("TRENDSMAPP_MAX_STATIONS_PER_FRAME", 500),
            max_concurrent_jobs=_positive_integer("TRENDSMAPP_MAX_CONCURRENT_JOBS", 1),
            max_concurrent_surface_jobs=_positive_integer("TRENDSMAPP_MAX_CONCURRENT_SURFACE_JOBS", int(os.getenv("TRENDSMAPP_MAX_CONCURRENT_JOBS", 1))),
            max_concurrent_video_jobs=_positive_integer("TRENDSMAPP_MAX_CONCURRENT_VIDEO_JOBS", int(os.getenv("TRENDSMAPP_MAX_CONCURRENT_JOBS", 1))),
            upload_ttl_hours=_nonnegative_number("TRENDSMAPP_UPLOAD_TTL_HOURS", 24.0),
            max_video_frames=_positive_integer("TRENDSMAPP_MAX_VIDEO_FRAMES", 300),
            surface_resolution=_positive_integer("TRENDSMAPP_SURFACE_RESOLUTION", 220),
            animation_resolution=_positive_integer("TRENDSMAPP_ANIMATION_RESOLUTION", 160),
        )
        # Validate HTTPS_ONLY requirements after settings object is created
        # (uses dynamic properties for https_only and ephemeral_secret)
        if settings.https_only and (settings.ephemeral_secret or settings.secret_key in KNOWN_INSECURE_SECRET_KEYS):
            raise RuntimeError(
                "SECRET_KEY must be set to a long unique random value when TRENDSMAPP_HTTPS_ONLY=true."
            )
        if settings.demo_mode and not settings.demo_dataset.is_file():
            raise RuntimeError(f"Demo dataset does not exist: {settings.demo_dataset}")
        if settings.ephemeral_secret:
            logger.warning(
                "SECRET_KEY is not set; an ephemeral key was generated for this process. "
                "Signed sessions reset on every restart. Set SECRET_KEY for stable sessions."
            )
        elif settings.secret_key in KNOWN_INSECURE_SECRET_KEYS:
            logger.warning(
                "SECRET_KEY matches a published example value; replace it with a long unique random secret."
            )
        return settings


settings = Settings.from_environment()