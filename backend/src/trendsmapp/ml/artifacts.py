"""Safe model serialization, feature schema, environment metadata, hashes, load checks."""

from __future__ import annotations

import io
import json
import platform
from typing import Any, Final

import joblib
import numpy as np

from trendsmapp.contracts.versions import APPLICATION_VERSION, ARTIFACT_SCHEMA_VERSION
from trendsmapp.errors import ValidationError

__all__ = ["MODEL_PACKAGE_SCHEMA_VERSION", "load_model", "model_environment", "save_model"]

#: Version of the serialized model package container.
MODEL_PACKAGE_SCHEMA_VERSION: Final[str] = "1.0.0"


def model_environment() -> dict[str, str]:
    """Capture the library and interpreter environment of the current process."""
    import sklearn
    import xgboost

    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "scikit_learn": sklearn.__version__,
    "xgboost": xgboost.__version__,
        "numpy": np.__version__,
        "application_version": APPLICATION_VERSION,
    }


def save_model(
    model: Any,
    preprocessor: Any,
    feature_names: list[str],
    task: Any,
) -> bytes:
    """Serialize the model package to bytes with schema, hashes, and environment.

    The container is JSON metadata plus a joblib payload. The payload digest is
    recorded in the metadata so a corrupted package is detected at load time.
    """
    import hashlib

    buffer = io.BytesIO()
    joblib.dump({"model": model, "preprocessor": preprocessor}, buffer)
    payload = buffer.getvalue()
    metadata = {
        "schema_version": MODEL_PACKAGE_SCHEMA_VERSION,
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "feature_names": list(feature_names),
        "task_hash": getattr(task, "canonical_json", lambda: "")(),
        "environment": model_environment(),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "payload_size_bytes": len(payload),
    }
    return json.dumps(metadata, sort_keys=True).encode("utf-8") + b"\n" + payload


def load_model(container: bytes) -> tuple[Any, Any, dict[str, Any]]:
    """Load a model package, verifying its schema, digest, and recorded environment.

    Returns ``(model, preprocessor, metadata)``. Raises when the schema version
    is unsupported or the payload digest does not match the metadata.
 """
    import hashlib

    newline = container.index(b"\n")
    metadata = json.loads(container[:newline].decode("utf-8"))
    payload = container[newline + 1 :]
    if metadata.get("schema_version") != MODEL_PACKAGE_SCHEMA_VERSION:
        raise ValidationError(
            f"The model package schema version '{metadata.get('schema_version')}' is "
            f"not supported; expected '{MODEL_PACKAGE_SCHEMA_VERSION}'.",
            details={"reason": "unsupported_model_package_schema"},
        )
    actual = hashlib.sha256(payload).hexdigest()
    if actual != metadata.get("payload_sha256"):
        raise ValidationError(
            "The model package payload does not match its recorded digest; the "
            "package is corrupted or tampered with.",
            details={"reason": "model_payload_digest_mismatch"},
        )
    if len(payload) != metadata.get("payload_size_bytes"):
        raise ValidationError(
            "The model package payload size does not match the metadata.",
            details={"reason": "model_payload_size_mismatch"},
        )
    objects = joblib.load(io.BytesIO(payload))
    return objects["model"], objects["preprocessor"], metadata
