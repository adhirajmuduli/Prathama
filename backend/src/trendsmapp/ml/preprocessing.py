"""Fold-local preprocessing: scikit-learn ColumnTransformer and Pipeline construction.

The pipeline is returned unfitted; the training loop fits it on each fold's
inner-train data only, so imputation and encoding can never see the outer test
fold. Feature lineage is the caller's responsibility (the feature table hash).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

__all__ = ["build_preprocessor"]

#: Whether numeric features are standardized after imputation.
SCALE_NUMERIC: Final[bool] = True


def build_preprocessor(
    feature_names: Sequence[str],
    *,
    categorical: Sequence[str] = (),
    scale_numeric: bool = SCALE_NUMERIC,
) -> Pipeline:
    """Build an unfitted preprocessing pipeline over the feature columns.

    Columns are addressed by position (the order of ``feature_names``), so the
    pipeline works on both numpy arrays and dataframes. Numeric columns get
    median imputation (and optional scaling); categorical columns get one-hot
    encoding with unknown categories ignored, so an unseen category at
    prediction time cannot crash the model.
    """
    categorical_set = set(categorical)
    numeric = [index for index, name in enumerate(feature_names) if name not in categorical_set]
    categorical_indices = [
        index for index, name in enumerate(feature_names) if name in categorical_set
    ]
    transforms: list[tuple[str, Any, list[int]]] = []
    numeric_steps: list[tuple[str, Any]] = [("impute", SimpleImputer(strategy="median"))]
    if scale_numeric:
        numeric_steps.append(("scale", StandardScaler()))
    transforms.append(("numeric", Pipeline(numeric_steps), numeric))
    if categorical_indices:
        transforms.append(
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                categorical_indices,
            )
        )
    return Pipeline([("preprocess", ColumnTransformer(transforms))])
