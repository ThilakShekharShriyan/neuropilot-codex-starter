"""M1 contract validation and provenance helpers.

This module intentionally has no network client. Authenticated acquisition is a
separate, reviewed step after the fixture contract is accepted.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import re
import zlib
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MAX_UINT64 = 2**64 - 1
# The approved FAFB v783 connection export is substantially larger than the
# synthetic fixtures. Keep a finite expansion ceiling while accommodating the
# observed static product (roughly 0.5 GiB uncompressed, with headroom).
MAX_DECOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
ASCII_DECIMAL = re.compile(r"[0-9]+\Z")
PORTAL_URL = "https://codex.flywire.ai/api/download?dataset=fafb"
RESOURCE_URL_TEMPLATE = (
    "https://codex.flywire.ai/api/download_resource?"
    "data_product={product}&dataset=fafb&api_token=<redacted>"
)

PRODUCT_SCHEMAS: dict[str, tuple[str, ...]] = {
    "neurons": (
        "root_id",
        "group",
        "nt_type",
        "nt_type_score",
        "da_avg",
        "ser_avg",
        "gaba_avg",
        "glut_avg",
        "ach_avg",
        "oct_avg",
    ),
    "classification": (
        "root_id",
        "flow",
        "super_class",
        "class",
        "sub_class",
        "hemilineage",
        "side",
        "nerve",
    ),
    "consolidated_cell_types": ("root_id", "primary_type", "additional_type(s)"),
    "connections_princeton": (
        "pre_root_id",
        "post_root_id",
        "neuropil",
        "syn_count",
        "nt_type",
    ),
}


class ValidationError(ValueError):
    """Raised when a product or bundle violates the M1 import contract."""


@dataclass
class ProductReport:
    product: str
    row_count: int = 0
    duplicate_id_count: int = 0
    missing_annotation_value_count: int = 0
    dangling_endpoint_count: int = 0
    invalid_uint64_count: int = 0
    invalid_float_count: int = 0
    invalid_synapse_count: int = 0
    pair_total_overflow_count: int = 0
    self_loop_count: int = 0
    source_rows_below_five: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class BundleReport:
    products: dict[str, ProductReport]
    neuron_ids: set[int]
    valid: bool


@dataclass(frozen=True)
class PairThresholdResult:
    threshold: int
    pair_totals: dict[tuple[int, int], int]
    qualifying_pairs: frozenset[tuple[int, int]]
    retained_rows: tuple[Mapping[str, str], ...]


def _decompress(payload: bytes, product: str) -> bytes:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
            decompressed = stream.read(MAX_DECOMPRESSED_BYTES + 1)
    except (gzip.BadGzipFile, EOFError, OSError, zlib.error) as exc:
        raise ValidationError(f"{product}: malformed gzip payload") from exc
    if len(decompressed) > MAX_DECOMPRESSED_BYTES:
        raise ValidationError(
            f"{product}: decompressed payload exceeds {MAX_DECOMPRESSED_BYTES} bytes"
        )
    return decompressed


def parse_uint64(value: str, field_name: str) -> int:
    """Parse an unsigned 64-bit ID without float conversion."""
    if not isinstance(value, str) or ASCII_DECIMAL.fullmatch(value) is None:
        raise ValidationError(f"{field_name} is not an unsigned decimal integer")
    parsed = int(value, 10)
    if parsed > MAX_UINT64:
        raise ValidationError(f"{field_name} exceeds uint64: {value!r}")
    return parsed


def _read_rows(product: str, payload: bytes) -> tuple[list[str], list[dict[str, str]]]:
    decompressed = _decompress(payload, product)
    try:
        reader = csv.DictReader(io.StringIO(decompressed.decode("utf-8")))
    except UnicodeDecodeError as exc:
        raise ValidationError(f"{product}: payload is not UTF-8 CSV") from exc
    headers = reader.fieldnames or []
    if len(headers) != len(set(headers)):
        raise ValidationError(f"{product}: duplicate header names")
    required = PRODUCT_SCHEMAS[product]
    if tuple(headers) != required:
        missing = [column for column in required if column not in headers]
        unexpected = [column for column in headers if column not in required]
        raise ValidationError(
            f"{product}: header mismatch; missing={missing}, unexpected={unexpected}"
        )
    rows: list[dict[str, str]] = []
    for row_number, row in enumerate(reader, start=2):
        if None in row or any(value is None for value in row.values()):
            raise ValidationError(f"{product}: malformed row {row_number}: wrong column count")
        rows.append(row)
    return headers, rows


def pair_threshold(rows: list[Mapping[str, str]], min_synapses: int = 5) -> PairThresholdResult:
    """Apply a pair-level threshold after summing all neuropil rows."""
    if isinstance(min_synapses, bool) or not isinstance(min_synapses, int):
        raise ValidationError("min_synapses must be an integer")
    if min_synapses < 1:
        raise ValidationError("min_synapses must be at least 1")
    totals: defaultdict[tuple[int, int], int] = defaultdict(int)
    for row in rows:
        pre = parse_uint64(row["pre_root_id"], "pre_root_id")
        post = parse_uint64(row["post_root_id"], "post_root_id")
        syn_count = parse_positive_decimal(row["syn_count"], "syn_count")
        total = totals[(pre, post)]
        if total > MAX_UINT64 - syn_count:
            raise ValidationError("connections_princeton: pair synapse total exceeds uint64")
        totals[(pre, post)] = total + syn_count
    qualifying = frozenset(pair for pair, total in totals.items() if total >= min_synapses)
    retained = tuple(
        row
        for row in rows
        if (
            parse_uint64(row["pre_root_id"], "pre_root_id"),
            parse_uint64(row["post_root_id"], "post_root_id"),
        )
        in qualifying
    )
    return PairThresholdResult(min_synapses, dict(totals), qualifying, retained)


def parse_positive_decimal(value: str, field_name: str) -> int:
    """Parse a strictly ASCII positive decimal integer."""
    if not isinstance(value, str) or ASCII_DECIMAL.fullmatch(value) is None:
        raise ValidationError(f"{field_name} is not an unsigned decimal integer")
    parsed = int(value, 10)
    if parsed < 1:
        raise ValidationError(f"{field_name} must be positive")
    if parsed > MAX_UINT64:
        raise ValidationError(f"{field_name} exceeds uint64")
    return parsed


def validate_bundle(bundle: Mapping[str, bytes]) -> BundleReport:
    """Validate all four products and cross-product endpoint integrity."""
    required_products = set(PRODUCT_SCHEMAS)
    missing_products = required_products - set(bundle)
    if missing_products:
        raise ValidationError(f"missing products: {sorted(missing_products)}")
    unexpected_products = set(bundle) - required_products
    if unexpected_products:
        raise ValidationError(f"unexpected products: {sorted(unexpected_products)}")

    reports: dict[str, ProductReport] = {}
    parsed_rows: dict[str, list[dict[str, str]]] = {}
    neuron_ids: set[int] = set()
    for product in PRODUCT_SCHEMAS:
        _, rows = _read_rows(product, bundle[product])
        report = ProductReport(product=product, row_count=len(rows))
        reports[product] = report
        parsed_rows[product] = rows
        if product == "neurons":
            for row in rows:
                try:
                    root_id = parse_uint64(row["root_id"], "root_id")
                    if root_id in neuron_ids:
                        report.duplicate_id_count += 1
                    neuron_ids.add(root_id)
                except ValidationError as exc:
                    report.invalid_uint64_count += 1
                    report.errors.append(str(exc))
                for field_name in (
                    "nt_type_score",
                    "da_avg",
                    "ser_avg",
                    "gaba_avg",
                    "glut_avg",
                    "ach_avg",
                    "oct_avg",
                ):
                    if row[field_name].strip():
                        try:
                            value = float(row[field_name])
                            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                                raise ValueError
                        except ValueError:
                            report.invalid_float_count += 1

    for product in ("classification", "consolidated_cell_types"):
        seen: set[int] = set()
        report = reports[product]
        for row in parsed_rows[product]:
            try:
                root_id = parse_uint64(row["root_id"], "root_id")
            except ValidationError as exc:
                report.invalid_uint64_count += 1
                report.errors.append(str(exc))
                continue
            if root_id in seen:
                report.duplicate_id_count += 1
            seen.add(root_id)
            if any(value.strip() == "" for key, value in row.items() if key != "root_id"):
                report.missing_annotation_value_count += 1

    connections_report = reports["connections_princeton"]
    pair_totals: defaultdict[tuple[int, int], int] = defaultdict(int)
    for row in parsed_rows["connections_princeton"]:
        try:
            pre = parse_uint64(row["pre_root_id"], "pre_root_id")
            post = parse_uint64(row["post_root_id"], "post_root_id")
        except ValidationError as exc:
            connections_report.invalid_uint64_count += 1
            connections_report.errors.append(str(exc))
            continue
        if pre not in neuron_ids:
            connections_report.dangling_endpoint_count += 1
        if post not in neuron_ids:
            connections_report.dangling_endpoint_count += 1
        if pre == post:
            connections_report.self_loop_count += 1
        try:
            syn_count = parse_positive_decimal(row["syn_count"], "syn_count")
        except ValidationError:
            connections_report.invalid_synapse_count += 1
        else:
            if syn_count < 5:
                connections_report.source_rows_below_five += 1
            pair = (pre, post)
            total = pair_totals[pair]
            if total > MAX_UINT64 - syn_count:
                connections_report.pair_total_overflow_count += 1
                connections_report.errors.append(
                    "connections_princeton: pair synapse total exceeds uint64"
                )
            else:
                pair_totals[pair] = total + syn_count

    valid = all(
        report.duplicate_id_count == 0
        and report.invalid_uint64_count == 0
        and report.invalid_float_count == 0
        and report.invalid_synapse_count == 0
        and report.pair_total_overflow_count == 0
        and report.dangling_endpoint_count == 0
        for report in reports.values()
    )
    return BundleReport(products=reports, neuron_ids=neuron_ids, valid=valid)


def assert_valid(report: BundleReport) -> None:
    """Raise a concise error after retaining the full validation report."""
    if report.valid:
        return
    failures = {
        name: report_data.__dict__
        for name, report_data in report.products.items()
        if report_data.errors
        or report_data.duplicate_id_count
        or report_data.invalid_uint64_count
        or report_data.invalid_float_count
        or report_data.invalid_synapse_count
        or report_data.pair_total_overflow_count
        or report_data.dangling_endpoint_count
    }
    raise ValidationError(json.dumps(failures, sort_keys=True))


def redact_secrets(text: str) -> str:
    """Remove Codex tokens from URLs, diagnostics, and exception text."""
    redacted = re.sub(r"(api_token=)[^&\s]+", r"\1<redacted>", text, flags=re.IGNORECASE)
    return re.sub(r"(CODEX_API_TOKEN=)[^\s&]+", r"\1<redacted>", redacted)


def redact_url(url: str) -> str:
    """Return a URL with query-string credentials removed."""
    parts = urlsplit(url)
    query = [
        (key, "<redacted>" if key.lower() == "api_token" else value)
        for key, value in parse_qsl(parts.query)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def build_manifest(
    bundle: Mapping[str, bytes],
    report: BundleReport,
    *,
    importer_commit: str = "synthetic-fixture",
) -> dict[str, object]:
    """Build deterministic synthetic provenance without authenticated URLs."""
    products = []
    for product in sorted(bundle):
        products.append(
            {
                "name": product,
                "filename": f"{product}.csv.gz",
                "sha256": hashlib.sha256(bundle[product]).hexdigest(),
                "content_length_bytes": len(bundle[product]),
                "schema_columns": list(PRODUCT_SCHEMAS[product]),
                "row_count": report.products[product].row_count,
            }
        )
    _, connection_rows = _read_rows("connections_princeton", bundle["connections_princeton"])
    threshold_result = pair_threshold(connection_rows)
    return {
        "manifest_version": 1,
        "data_kind": "synthetic-fixture",
        "dataset": "synthetic-m1-fixture",
        "snapshot": "fixture-1",
        "portal_url": PORTAL_URL,
        "resource_url_template": RESOURCE_URL_TEMPLATE,
        "license": "synthetic fixture; no FlyWire data",
        "citation": [],
        "products": products,
        "validation": {
            "valid": report.valid,
            "neuron_count": len(report.neuron_ids),
            "self_loop_count": report.products["connections_princeton"].self_loop_count,
            "source_rows_below_five": report.products[
                "connections_princeton"
            ].source_rows_below_five,
            "threshold_policy": "pair-level-sum-across-neuropils",
            "threshold_synapses": threshold_result.threshold,
            "qualifying_pair_count": len(threshold_result.qualifying_pairs),
            "qualifying_source_row_count": len(threshold_result.retained_rows),
        },
        "import": {
            "git_commit": importer_commit,
            "transform": "synthetic-fixture-v1",
            "threshold_evaluated": True,
            "threshold_applied": False,
        },
    }


def manifest_bytes(manifest: Mapping[str, object]) -> bytes:
    """Serialize a manifest deterministically for hashing and tests."""
    return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
