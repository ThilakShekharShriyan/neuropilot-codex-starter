import gzip
import json

import neuropilot_core.importer as importer
import pytest
from neuropilot_core.fixtures import synthetic_bundle
from neuropilot_core.importer import (
    PRODUCT_SCHEMAS,
    ValidationError,
    assert_valid,
    build_manifest,
    manifest_bytes,
    pair_threshold,
    redact_secrets,
    redact_url,
    validate_bundle,
)


def test_valid_fixture_and_deterministic_manifest() -> None:
    first = synthetic_bundle()
    second = synthetic_bundle()
    assert first == second
    report = validate_bundle(first)
    assert report.valid
    assert report.products["connections_princeton"].self_loop_count == 1
    manifest = build_manifest(first, report)
    assert manifest_bytes(manifest) == manifest_bytes(
        build_manifest(second, validate_bundle(second))
    )
    encoded = manifest_bytes(manifest)
    assert b"CODEX_API_TOKEN" not in encoded
    assert b"api_token=secret" not in encoded
    assert manifest["data_kind"] == "synthetic-fixture"
    assert manifest["validation"]["threshold_synapses"] == 5
    assert manifest["validation"]["qualifying_pair_count"] == 2
    assert manifest["validation"]["qualifying_source_row_count"] == 3
    assert manifest["import"]["threshold_evaluated"] is True
    assert manifest["import"]["threshold_applied"] is False


def test_malformed_gzip_is_rejected() -> None:
    bundle = synthetic_bundle()
    bundle["neurons"] = b"not gzip"
    with pytest.raises(ValidationError, match="malformed gzip"):
        validate_bundle(bundle)


def test_missing_required_header_is_rejected() -> None:
    bundle = synthetic_bundle()
    raw = gzip.decompress(bundle["classification"]).decode()
    bundle["classification"] = gzip.compress(raw.replace(",nerve\n", "\n").encode(), mtime=0)
    with pytest.raises(ValidationError, match="header mismatch"):
        validate_bundle(bundle)


def test_corrupted_gzip_stream_is_rejected() -> None:
    bundle = synthetic_bundle()
    bundle["neurons"] = bundle["neurons"][:-4]
    with pytest.raises(ValidationError, match="malformed gzip"):
        validate_bundle(bundle)


def test_decompressed_size_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = synthetic_bundle()
    monkeypatch.setattr(importer, "MAX_DECOMPRESSED_BYTES", 32)
    with pytest.raises(ValidationError, match="decompressed payload exceeds"):
        validate_bundle(bundle)


def test_invalid_utf8_is_rejected() -> None:
    bundle = synthetic_bundle()
    bundle["neurons"] = gzip.compress(b"\xff\xfe", mtime=0)
    with pytest.raises(ValidationError, match="not UTF-8 CSV"):
        validate_bundle(bundle)


def test_row_with_too_many_fields_is_rejected() -> None:
    bundle = synthetic_bundle()
    raw = gzip.decompress(bundle["neurons"]).decode()
    lines = raw.splitlines()
    lines[1] += ",extra"
    bundle["neurons"] = gzip.compress(("\n".join(lines) + "\n").encode(), mtime=0)
    with pytest.raises(ValidationError, match=r"neurons: malformed row 2"):
        validate_bundle(bundle)


def test_duplicate_and_unexpected_headers_are_rejected() -> None:
    bundle = synthetic_bundle()
    header = ",".join((*PRODUCT_SCHEMAS["neurons"], "unexpected"))
    raw = gzip.decompress(bundle["neurons"]).decode()
    bundle["neurons"] = gzip.compress(
        (header + "\n" + "\n".join(raw.splitlines()[1:])).encode(), mtime=0
    )
    with pytest.raises(ValidationError, match="header mismatch"):
        validate_bundle(bundle)

    duplicate_header = ",".join((*PRODUCT_SCHEMAS["neurons"][:-1], "oct_avg", "oct_avg"))
    bundle["neurons"] = gzip.compress(
        (duplicate_header + "\n" + "\n".join(raw.splitlines()[1:])).encode(), mtime=0
    )
    with pytest.raises(ValidationError, match="duplicate header"):
        validate_bundle(bundle)


def test_short_csv_row_is_rejected_with_product_and_row() -> None:
    bundle = synthetic_bundle()
    raw = gzip.decompress(bundle["neurons"]).decode()
    bundle["neurons"] = gzip.compress(
        ("\n".join(raw.splitlines()[:-1] + ["100,fixture"]) + "\n").encode(),
        mtime=0,
    )
    with pytest.raises(ValidationError, match=r"neurons: malformed row 4"):
        validate_bundle(bundle)


def test_duplicate_neuron_id_is_invalid() -> None:
    bundle = synthetic_bundle()
    raw = gzip.decompress(bundle["neurons"]).decode()
    bundle["neurons"] = gzip.compress((raw + raw.splitlines()[1] + "\n").encode(), mtime=0)
    report = validate_bundle(bundle)
    assert not report.valid
    assert report.products["neurons"].duplicate_id_count == 1
    with pytest.raises(ValidationError):
        assert_valid(report)


def test_duplicate_annotation_id_is_invalid() -> None:
    bundle = synthetic_bundle()
    raw = gzip.decompress(bundle["classification"]).decode()
    bundle["classification"] = gzip.compress((raw + raw.splitlines()[1] + "\n").encode(), mtime=0)
    report = validate_bundle(bundle)
    assert not report.valid
    assert report.products["classification"].duplicate_id_count == 1


def test_invalid_neuron_float_is_invalid() -> None:
    bundle = synthetic_bundle()
    raw = gzip.decompress(bundle["neurons"]).decode().replace(",0.9,", ",not-a-float,", 1)
    bundle["neurons"] = gzip.compress(raw.encode(), mtime=0)
    report = validate_bundle(bundle)
    assert not report.valid
    assert report.products["neurons"].invalid_float_count == 1


@pytest.mark.parametrize("bad_value", ["nan", "inf", "-inf", "1.1", "-0.1"])
def test_non_finite_or_out_of_range_neuron_float_is_invalid(bad_value: str) -> None:
    bundle = synthetic_bundle()
    raw = gzip.decompress(bundle["neurons"]).decode().replace(",0.9,", f",{bad_value},", 1)
    bundle["neurons"] = gzip.compress(raw.encode(), mtime=0)
    report = validate_bundle(bundle)
    assert not report.valid
    assert report.products["neurons"].invalid_float_count == 1


def test_pair_threshold_sums_neuropils_and_preserves_unaggregated_rows() -> None:
    rows = [
        {
            "pre_root_id": "100",
            "post_root_id": "200",
            "neuropil": "A",
            "syn_count": "2",
            "nt_type": "ACh",
        },
        {
            "pre_root_id": "100",
            "post_root_id": "200",
            "neuropil": "B",
            "syn_count": "3",
            "nt_type": "ACh",
        },
        {
            "pre_root_id": "200",
            "post_root_id": "100",
            "neuropil": "A",
            "syn_count": "1",
            "nt_type": "GABA",
        },
    ]
    result = pair_threshold(rows, min_synapses=5)
    assert result.pair_totals[(100, 200)] == 5
    assert (100, 200) in result.qualifying_pairs
    assert len(result.retained_rows) == 2
    assert {row["neuropil"] for row in result.retained_rows} == {"A", "B"}


def test_pair_threshold_rejects_pair_total_overflow() -> None:
    rows = [
        {
            "pre_root_id": "100",
            "post_root_id": "200",
            "neuropil": "A",
            "syn_count": "18446744073709551615",
            "nt_type": "ACh",
        },
        {
            "pre_root_id": "100",
            "post_root_id": "200",
            "neuropil": "B",
            "syn_count": "1",
            "nt_type": "ACh",
        },
    ]
    with pytest.raises(ValidationError, match="pair synapse total exceeds uint64"):
        pair_threshold(rows, min_synapses=5)


def test_pair_below_threshold_is_excluded_and_reciprocal_pair_is_separate() -> None:
    rows = [
        {
            "pre_root_id": "100",
            "post_root_id": "200",
            "neuropil": "A",
            "syn_count": "4",
            "nt_type": "ACh",
        },
        {
            "pre_root_id": "200",
            "post_root_id": "100",
            "neuropil": "A",
            "syn_count": "5",
            "nt_type": "GABA",
        },
    ]
    result = pair_threshold(rows, min_synapses=5)
    assert (100, 200) not in result.qualifying_pairs
    assert (200, 100) in result.qualifying_pairs
    assert [(row["pre_root_id"], row["post_root_id"]) for row in result.retained_rows] == [
        ("200", "100")
    ]


@pytest.mark.parametrize("bad_threshold", [0, -1, 5.0, True])
def test_pair_threshold_requires_positive_integer(bad_threshold: object) -> None:
    with pytest.raises(ValidationError, match="min_synapses"):
        pair_threshold([], min_synapses=bad_threshold)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["neurons", "connections_princeton"])
def test_invalid_uint64_is_rejected(field: str) -> None:
    bundle = synthetic_bundle()
    raw = gzip.decompress(bundle[field]).decode()
    raw = raw.replace("100", "18446744073709551616", 1)
    bundle[field] = gzip.compress(raw.encode(), mtime=0)
    report = validate_bundle(bundle)
    assert not report.valid
    assert report.products[field].invalid_uint64_count == 1


@pytest.mark.parametrize("bad_id", ["+100", "1_000", "１２３"])
def test_root_ids_require_ascii_decimal_digits(bad_id: str) -> None:
    bundle = synthetic_bundle()
    raw = gzip.decompress(bundle["neurons"]).decode().replace("100,fixture", f"{bad_id},fixture", 1)
    bundle["neurons"] = gzip.compress(raw.encode(), mtime=0)
    report = validate_bundle(bundle)
    assert not report.valid
    assert report.products["neurons"].invalid_uint64_count == 1


def test_invalid_synapse_count_is_rejected() -> None:
    bundle = synthetic_bundle()
    raw = gzip.decompress(bundle["connections_princeton"]).decode().replace(",1,GABA", ",0,GABA")
    bundle["connections_princeton"] = gzip.compress(raw.encode(), mtime=0)
    report = validate_bundle(bundle)
    assert not report.valid
    assert report.products["connections_princeton"].invalid_synapse_count == 1


@pytest.mark.parametrize("bad_value", ["+5", "5.0", "1_000", "18446744073709551616"])
def test_non_decimal_synapse_count_is_rejected(bad_value: str) -> None:
    bundle = synthetic_bundle()
    raw = (
        gzip.decompress(bundle["connections_princeton"])
        .decode()
        .replace(",2,ACh", f",{bad_value},ACh", 1)
    )
    bundle["connections_princeton"] = gzip.compress(raw.encode(), mtime=0)
    report = validate_bundle(bundle)
    assert not report.valid
    assert report.products["connections_princeton"].invalid_synapse_count == 1


def test_unexpected_bundle_product_is_rejected() -> None:
    bundle = synthetic_bundle()
    bundle["extra"] = bundle["neurons"]
    with pytest.raises(ValidationError, match="unexpected products"):
        validate_bundle(bundle)


def test_dangling_endpoint_is_rejected_but_annotation_only_ids_do_not_validate_it() -> None:
    bundle = synthetic_bundle()
    raw = gzip.decompress(bundle["connections_princeton"]).decode().replace("300,300", "999,300")
    bundle["connections_princeton"] = gzip.compress(raw.encode(), mtime=0)
    report = validate_bundle(bundle)
    assert not report.valid
    assert report.products["connections_princeton"].dangling_endpoint_count == 1


def test_token_redaction_covers_urls_and_error_text() -> None:
    secret = "super-secret-token"
    authenticated = f"https://codex.flywire.ai/api/download_resource?data_product=neurons&api_token={secret}&dataset=fafb"
    safe = redact_url(authenticated)
    assert secret not in safe
    assert "api_token=%3Credacted%3E" in safe
    diagnostic = redact_secrets(f"request failed for {authenticated} CODEX_API_TOKEN={secret}")
    assert secret not in diagnostic
    assert "api_token=" in diagnostic and "<redacted>" in diagnostic


def test_manifest_is_json_and_contains_only_token_free_templates() -> None:
    bundle = synthetic_bundle()
    report = validate_bundle(bundle)
    manifest = build_manifest(bundle, report)
    parsed = json.loads(manifest_bytes(manifest))
    assert parsed["portal_url"] == "https://codex.flywire.ai/api/download?dataset=fafb"
    assert "<redacted>" in parsed["resource_url_template"]
    assert "super-secret" not in json.dumps(parsed)
