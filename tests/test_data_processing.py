import pandas as pd
import pytest

from utils.data_processing import DataValidationError, normalize_observations, ordered_timestamps


def test_normalizes_long_format_without_remelting():
    source = pd.DataFrame({
        "Latitude": [19.5, 19.6],
        "Longitude": [85.1, 85.2],
        "Timestamp": ["2024-01-01", "2024-02-01"],
        "Value": [1.2, 2.3],
        "Parameter": ["chlorophyll", "chlorophyll"],
    })
    result = normalize_observations(source)
    assert result["timestamp"].tolist() == ["2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z"]
    assert result["value"].tolist() == [1.2, 2.3]
    assert result["parameter"].unique().tolist() == ["chlorophyll"]


def test_normalizes_wide_format_and_drops_only_blank_measurements():
    source = pd.DataFrame({
        "lat": [19.5, 19.6],
        "lon": [85.1, 85.2],
        "2024-01-01": [1.0, None],
        "2024-02-01": [2.0, 3.0],
    })
    result = normalize_observations(source)
    assert len(result) == 3
    assert ordered_timestamps(result) == ["2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z"]


@pytest.mark.parametrize("frame", [
    pd.DataFrame({"latitude": [19.5], "longitude": [85.1]}),
    pd.DataFrame({"latitude": [91], "longitude": [85.1], "timestamp": ["2024-01-01"], "value": [1]}),
    pd.DataFrame({"latitude": [19.5], "longitude": [181], "timestamp": ["2024-01-01"], "value": [1]}),
])
def test_rejects_ambiguous_or_invalid_tables(frame):
    with pytest.raises(DataValidationError):
        normalize_observations(frame)
