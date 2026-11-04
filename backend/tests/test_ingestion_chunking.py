"""Tests for chunk planning, range validation, and part assembly."""

from __future__ import annotations

import hashlib
import io

import pytest

from trendsmapp.errors import ConflictError, StorageError, ValidationError
from trendsmapp.hashing import sha256_bytes
from trendsmapp.ingestion.chunking import (
    MAX_PART_COUNT,
    StoredPartRef,
    TextBatch,
    assemble_parts,
    count_rows,
    expected_part_size,
    parse_content_range,
    part_count,
    plan_parts,
    validate_part_request,
)
from trendsmapp.storage.local import LocalObjectStore


def test_part_count_divides_exactly_and_with_a_remainder() -> None:
    assert part_count(120, 40) == 3
    assert part_count(100, 40) == 3
    assert part_count(1, 40) == 1
    assert part_count(40, 40) == 1


def test_part_count_rejects_empty_files_and_invalid_chunks() -> None:
    with pytest.raises(ValidationError) as error:
        part_count(0, 40)
    assert "at least one byte" in str(error.value)
    with pytest.raises(ValidationError):
        part_count(100, 0)


def test_plan_parts_declares_contiguous_byte_ranges() -> None:
    plans = plan_parts(100, 40)
    assert [
        (plan.part_number, plan.start_byte, plan.end_byte, plan.size_bytes) for plan in plans
    ] == [
        (1, 0, 39, 40),
        (2, 40, 79, 40),
        (3, 80, 99, 20),
    ]
    total = sum(plan.size_bytes for plan in plans)
    assert total == 100


def test_plan_parts_rejects_more_parts_than_the_protocol_allows() -> None:
    with pytest.raises(ValidationError) as error:
        plan_parts(MAX_PART_COUNT + 1, 1)
    assert error.value.details["parts"] == MAX_PART_COUNT + 1


def test_expected_part_size_returns_the_last_partial_part() -> None:
    assert expected_part_size(total_bytes=100, chunk_size=40, part_number=1) == 40
    assert expected_part_size(total_bytes=100, chunk_size=40, part_number=3) == 20
    with pytest.raises(ValidationError):
        expected_part_size(total_bytes=100, chunk_size=40, part_number=4)
    with pytest.raises(ValidationError):
        expected_part_size(total_bytes=100, chunk_size=40, part_number=0)


def test_parse_content_range_accepts_the_canonical_form() -> None:
    assert parse_content_range("bytes=0-5242879") == (0, 5_242_879)
    assert parse_content_range("bytes=40-79") == (40, 79)
    assert parse_content_range(" bytes = 0 - 39 ") == (0, 39)


@pytest.mark.parametrize(
    "value",
    ["", "bytes", "bytes=", "bytes=0", "0-39", "chunks=0-39", "bytes=*", "bytes=a-b"],
)
def test_parse_content_range_rejects_malformed_values(value: str) -> None:
    with pytest.raises(ValidationError):
        parse_content_range(value)


def test_parse_content_range_rejects_reversed_ranges() -> None:
    with pytest.raises(ValidationError) as error:
        parse_content_range("bytes=40-39")
    assert error.value.details["start"] == 40


def test_validate_part_request_accepts_a_matching_range() -> None:
    plan = validate_part_request(
        part_number=2,
        content_range="bytes=40-79",
        total_bytes=100,
        chunk_size=40,
    )
    assert plan.part_number == 2
    assert plan.size_bytes == 40


def test_validate_part_request_rejects_a_mismatched_range() -> None:
    with pytest.raises(ValidationError) as error:
        validate_part_request(
            part_number=2,
            content_range="bytes=0-39",
            total_bytes=100,
            chunk_size=40,
        )
    assert error.value.details["expected_range"] == "bytes=40-79"
    assert error.value.details["received_range"] == "bytes=0-39"


def test_validate_part_request_rejects_out_of_range_part_numbers() -> None:
    with pytest.raises(ValidationError):
        validate_part_request(part_number=0, content_range=None, total_bytes=100, chunk_size=40)
    with pytest.raises(ValidationError):
        validate_part_request(part_number=4, content_range=None, total_bytes=100, chunk_size=40)


def test_validate_part_request_allows_an_omitted_range() -> None:
    plan = validate_part_request(part_number=1, content_range=None, total_bytes=100, chunk_size=40)
    assert plan.start_byte == 0


def _store_parts(
    store: LocalObjectStore,
    *,
    upload_id: str,
    payloads: list[bytes],
) -> list[StoredPartRef]:
    """Store the parts of an upload and return their references."""
    references: list[StoredPartRef] = []
    for index, payload in enumerate(payloads, start=1):
        key = f"uploads/{upload_id}/parts/{index:05d}"
        stored = store.put_bytes(key, payload, content_type="application/octet-stream")
        references.append(
            StoredPartRef(key=key, sha256=stored.sha256, size_bytes=stored.size_bytes)
        )
    return references


def test_assemble_parts_reassembles_the_exact_bytes(store: LocalObjectStore) -> None:
    payloads = [b"a" * 40, b"b" * 40, b"c" * 20]
    references = _store_parts(store, upload_id="upl_" + "0" * 32, payloads=payloads)
    destination = io.BytesIO()
    declared = sha256_bytes(b"".join(payloads))

    result = assemble_parts(
        store=store,
        parts=references,
        destination=destination,
        expected_total_bytes=100,
        expected_sha256=declared,
    )
    assert result.sha256 == declared
    assert result.size_bytes == 100
    assert result.part_count == 3
    assert destination.getvalue() == b"".join(payloads)


def test_assemble_parts_detects_a_size_mismatch(store: LocalObjectStore) -> None:
    references = _store_parts(store, upload_id="upl_" + "1" * 32, payloads=[b"a" * 40])
    corrupted = StoredPartRef(key=references[0].key, sha256=references[0].sha256, size_bytes=39)
    with pytest.raises(ConflictError) as error:
        assemble_parts(
            store=store,
            parts=[corrupted],
            destination=io.BytesIO(),
            expected_total_bytes=40,
            expected_sha256=None,
        )
    assert error.value.details["recorded_bytes"] == 39
    assert error.value.details["stored_bytes"] == 40


def test_assemble_parts_detects_a_digest_mismatch(store: LocalObjectStore) -> None:
    references = _store_parts(store, upload_id="upl_" + "2" * 32, payloads=[b"a" * 40])
    tampered = StoredPartRef(
        key=references[0].key, sha256="f" * 64, size_bytes=references[0].size_bytes
    )
    with pytest.raises(ConflictError) as error:
        assemble_parts(
            store=store,
            parts=[tampered],
            destination=io.BytesIO(),
            expected_total_bytes=40,
            expected_sha256=None,
        )
    assert error.value.details["key"] == references[0].key


def test_assemble_parts_detects_a_total_size_mismatch(store: LocalObjectStore) -> None:
    references = _store_parts(store, upload_id="upl_" + "3" * 32, payloads=[b"a" * 40])
    with pytest.raises(ConflictError) as error:
        assemble_parts(
            store=store,
            parts=references,
            destination=io.BytesIO(),
            expected_total_bytes=100,
            expected_sha256=None,
        )
    assert error.value.details["declared_bytes"] == 100
    assert error.value.details["assembled_bytes"] == 40


def test_assemble_parts_detects_a_wrong_declared_digest(store: LocalObjectStore) -> None:
    references = _store_parts(store, upload_id="upl_" + "4" * 32, payloads=[b"a" * 40])
    with pytest.raises(ConflictError) as error:
        assemble_parts(
            store=store,
            parts=references,
            destination=io.BytesIO(),
            expected_total_bytes=40,
            expected_sha256="e" * 64,
        )
    assert error.value.details["declared_sha256"] == "e" * 64


def test_assemble_parts_rejects_out_of_order_parts(store: LocalObjectStore) -> None:
    payloads = [b"a" * 40, b"b" * 40]
    references = _store_parts(store, upload_id="upl_" + "5" * 32, payloads=payloads)
    with pytest.raises(ConflictError):
        assemble_parts(
            store=store,
            parts=list(reversed(references)),
            destination=io.BytesIO(),
            expected_total_bytes=80,
            expected_sha256=sha256_bytes(b"".join(payloads)),
        )


def test_assemble_parts_rejects_missing_parts(store: LocalObjectStore) -> None:
    references = _store_parts(store, upload_id="upl_" + "6" * 32, payloads=[b"a" * 40])
    store.delete(references[0].key)
    with pytest.raises(StorageError):
        assemble_parts(
            store=store,
            parts=references,
            destination=io.BytesIO(),
            expected_total_bytes=40,
            expected_sha256=None,
        )


def test_assemble_parts_validates_the_declared_digest_form(store: LocalObjectStore) -> None:
    references = _store_parts(store, upload_id="upl_" + "7" * 32, payloads=[b"a" * 40])
    with pytest.raises(ValidationError):
        assemble_parts(
            store=store,
            parts=references,
            destination=io.BytesIO(),
            expected_total_bytes=40,
            expected_sha256="not-a-digest",
        )


def test_assemble_parts_rejects_an_empty_part_list(store: LocalObjectStore) -> None:
    with pytest.raises(ValidationError) as error:
        assemble_parts(
            store=store,
            parts=[],
            destination=io.BytesIO(),
            expected_total_bytes=0,
            expected_sha256=None,
        )
    assert "no parts" in str(error.value)


def test_assembly_is_streamed_in_bounded_chunks(store: LocalObjectStore) -> None:
    """A part larger than the read chunk size must still assemble exactly."""
    payload = (b"0123456789abcdef" * (1024 * 128))[: 3 * 1024 * 1024]
    references = _store_parts(store, upload_id="upl_" + "8" * 32, payloads=[payload])
    destination = io.BytesIO()
    result = assemble_parts(
        store=store,
        parts=references,
        destination=destination,
        expected_total_bytes=len(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
    )
    assert result.size_bytes == len(payload)
    assert destination.getvalue() == payload


def test_text_batch_validates_its_shape() -> None:
    batch = TextBatch(
        columns=("a", "b"),
        rows=(("1", "2"), ("3", "")),
        missing=((False, False), (False, True)),
        first_row_index=0,
    )
    assert batch.row_count == 2
    assert batch.missing_cell_count == 1

    with pytest.raises(ValidationError):
        TextBatch(columns=(), rows=(), missing=(), first_row_index=0)
    with pytest.raises(ValidationError):
        TextBatch(
            columns=("a", "b"),
            rows=(("1", "2", "3"),),
            missing=((False, False),),
            first_row_index=0,
        )
    with pytest.raises(ValidationError):
        TextBatch(columns=("a", "b"), rows=(("1", "2"),), missing=((False,),), first_row_index=0)
    with pytest.raises(ValidationError):
        TextBatch(
            columns=("a", "b"),
            rows=(("1", "2"), ("3", "4")),
            missing=((False, False),),
            first_row_index=0,
        )


def test_count_rows_sums_batches() -> None:
    first = TextBatch(
        columns=("a",), rows=(("1",), ("2",)), missing=((False,), (False,)), first_row_index=0
    )
    second = TextBatch(columns=("a",), rows=(("3",),), missing=((False,),), first_row_index=2)
    assert count_rows([first, second]) == 3
    assert count_rows([]) == 0
