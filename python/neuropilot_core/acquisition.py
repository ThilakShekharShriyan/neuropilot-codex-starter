"""Secure, sequential acquisition of the approved Codex FAFB products.

This module owns network access.  It deliberately does not share an HTTP
client with the importer, and it never exposes authenticated URLs in errors
or logs.
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import io
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlparse

import httpx

from .importer import (
    MAX_DECOMPRESSED_BYTES,
    PRODUCT_SCHEMAS,
    ValidationError,
    _read_rows,
    pair_threshold,
    validate_bundle,
)

DATASET = "fafb"
SNAPSHOT = "783"
PORTAL_URL = "https://codex.flywire.ai/api/download"
RESOURCE_URL = "https://codex.flywire.ai/api/download_resource"
PRODUCTS = tuple(PRODUCT_SCHEMAS)
LICENSE = "CC BY-NC 4.0"
CITATIONS = (
    "https://flywire.ai/guidelines",
    "https://codex.flywire.ai/faq",
)
DEFAULT_MAX_COMPRESSED_BYTES = 512 * 1024 * 1024
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)
TOKEN_PATTERN = re.compile(r"(?i)(api_token=)[^&\s]+")
REDIRECT_HOST = "storage.googleapis.com"
LOGGER = logging.getLogger(__name__)
VERSIONS_DIRNAME = "versions"
CURRENT_POINTER = "CURRENT.json"


class AcquisitionError(RuntimeError):
    """A safe, user-facing acquisition failure without request credentials."""


@dataclass(frozen=True)
class AcquisitionConfig:
    output_dir: Path
    max_compressed_bytes: int = DEFAULT_MAX_COMPRESSED_BYTES
    max_decompressed_bytes: int = MAX_DECOMPRESSED_BYTES
    timeout: httpx.Timeout = field(default_factory=lambda: DEFAULT_TIMEOUT)
    max_retries: int = 3
    retry_backoff_seconds: float = 0.05
    retry_jitter_seconds: float = 0.05
    importer_commit: str = "unknown"


@dataclass(frozen=True)
class ProductObservation:
    product: str
    filename: str
    sha256: str
    compressed_bytes: int
    row_count: int
    schema_columns: tuple[str, ...]
    status_code: int
    content_type: str | None
    content_length: str | None
    etag: str | None
    last_modified: str | None
    generation: str | None
    observed_at_utc: str


def redact(text: str) -> str:
    """Redact query-string tokens from diagnostics, including URL text."""
    return TOKEN_PATTERN.sub(r"\1<redacted>", text)


def _safe_error(message: str) -> AcquisitionError:
    return AcquisitionError(redact(message))


def _is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code <= 599


def _content_type_allowed(value: str | None) -> bool:
    if value is None:
        return False
    media_type = value.split(";", 1)[0].strip().lower()
    return media_type in {
        "application/gzip",
        "application/octet-stream",
        "application/x-gzip",
        "text/csv",
        "text/plain",
    }


def _validated_storage_redirect(location: str | None) -> str:
    """Allow Codex's documented storage redirect without forwarding credentials."""
    if not location:
        raise _safe_error("unexpected redirect")
    parsed = urlparse(location)
    if parsed.scheme != "https" or parsed.hostname != REDIRECT_HOST or parsed.query:
        raise _safe_error("unexpected redirect")
    return location


def _write_stream(stream: BinaryIO, destination: Path, limit: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with destination.open("wb") as output:
        for chunk in stream.iter_bytes(1024 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > limit:
                raise _safe_error("compressed response exceeds configured size limit")
            digest.update(chunk)
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    return digest.hexdigest(), total


def _atomic_write_bytes(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=destination.parent, prefix=f".{destination.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _rename_path(source: Path, destination: Path) -> None:
    source.rename(destination)


def _read_current_pointer(output_dir: Path) -> tuple[str, str]:
    try:
        pointer = json.loads((output_dir / CURRENT_POINTER).read_text(encoding="utf-8"))
        version = pointer["version"]
        manifest_sha256 = pointer["manifest_sha256"]
    except (OSError, KeyError, TypeError, ValueError):
        raise _safe_error("current FAFB publication pointer is invalid") from None
    if (
        not isinstance(version, str)
        or not re.fullmatch(r"v-[0-9a-f]{16}", version)
        or not isinstance(manifest_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256)
    ):
        raise _safe_error("current FAFB publication pointer is invalid")
    return version, manifest_sha256


def resolve_current(output_dir: Path) -> Path:
    """Resolve and validate the atomically selected complete dataset version."""
    version, expected_hash = _read_current_pointer(output_dir)
    version_dir = output_dir / VERSIONS_DIRNAME / version
    manifest_path = version_dir / "manifest.json"
    try:
        manifest_bytes_value = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes_value)
    except (OSError, ValueError):
        raise _safe_error("current FAFB publication is incomplete") from None
    if hashlib.sha256(manifest_bytes_value).hexdigest() != expected_hash:
        raise _safe_error("current FAFB publication manifest hash mismatch")
    try:
        product_names = {product["name"] for product in manifest["products"]}
    except (KeyError, TypeError):
        raise _safe_error("current FAFB publication has incomplete product inventory") from None
    if product_names != set(PRODUCTS):
        raise _safe_error("current FAFB publication has incomplete product inventory")
    if any(not (version_dir / f"{product}.csv.gz").is_file() for product in PRODUCTS):
        raise _safe_error("current FAFB publication is missing a product")
    return version_dir


def _write_current_pointer(output_dir: Path, version: str, manifest_sha256: str) -> None:
    payload = {
        "manifest_sha256": manifest_sha256,
        "version": version,
    }
    _atomic_write_bytes(output_dir / CURRENT_POINTER, manifest_bytes(payload))


def _publish_staged(staging: Path, output_dir: Path) -> Path:
    """Publish a validated staging directory through an atomic pointer switch."""
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    versions_dir = output_dir / VERSIONS_DIRNAME
    versions_dir.mkdir(parents=True, exist_ok=True)
    staged_manifest = staging / "manifest.json"
    manifest_hash = hashlib.sha256(staged_manifest.read_bytes()).hexdigest()
    version = f"v-{manifest_hash[:16]}"
    version_dir = versions_dir / version
    if version_dir.exists():
        raise _safe_error("publication version already exists")
    _rename_path(staging, version_dir)
    if not (version_dir / "manifest.json").is_file():
        raise _safe_error("staged publication is incomplete")
    _write_current_pointer(output_dir, version, manifest_hash)
    return resolve_current(output_dir)


def manifest_bytes(manifest: dict[str, object]) -> bytes:
    """Serialize acquisition provenance deterministically."""
    return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _current_importer_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    commit = result.stdout.strip()
    if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{7,64}", commit):
        return commit
    return "unknown"


class CodexAcquirer:
    """Sequential Codex downloader with bounded retries and atomic outputs."""

    def __init__(
        self,
        token: str,
        config: AcquisitionConfig,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        if not token or any(character.isspace() for character in token):
            raise AcquisitionError("CODEX_API_TOKEN is missing or invalid")
        if config.max_compressed_bytes <= 0 or config.max_decompressed_bytes <= 0:
            raise AcquisitionError("size limits must be positive")
        if (
            config.max_retries < 0
            or config.retry_backoff_seconds < 0
            or config.retry_jitter_seconds < 0
        ):
            raise AcquisitionError("retry settings must not be negative")
        self._token = token
        self._config = config
        self._client = client or httpx.Client(
            follow_redirects=False,
            timeout=config.timeout,
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> CodexAcquirer:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def discover_inventory(self, *, approved_contract: bool = False) -> tuple[str, ...]:
        """Return only the explicitly reviewed product contract.

        Codex does not document an authenticated inventory endpoint. The
        default remains fail-closed; proceeding requires explicit human
        approval of the reviewed four-product contract.
        """
        if not approved_contract:
            raise AcquisitionError(
                "Codex has no supported authenticated product-inventory mechanism; "
                "refusing to scrape the sign-in portal or guess product identifiers"
            )
        return PRODUCTS

    def _backoff_seconds(self, attempt: int) -> float:
        base = self._config.retry_backoff_seconds * (2**attempt)
        jitter = secrets.SystemRandom().uniform(0, self._config.retry_jitter_seconds)
        return min(base + jitter, 30.0)

    def download_product(
        self, product: str, *, destination: Path | None = None
    ) -> ProductObservation:
        if product not in PRODUCT_SCHEMAS:
            raise AcquisitionError(f"unsupported product: {product}")
        destination = destination or self._config.output_dir
        destination.mkdir(parents=True, exist_ok=True)
        filename = f"{product}.csv.gz"
        final_path = destination / filename
        temporary_path: Path | None = None
        last_retryable: str | None = None
        try:
            for attempt in range(self._config.max_retries + 1):
                try:
                    with contextlib.ExitStack() as stack:
                        response = stack.enter_context(
                            self._client.stream(
                                "GET",
                                RESOURCE_URL,
                                params={
                                    "data_product": product,
                                    "dataset": DATASET,
                                    "api_token": self._token,
                                },
                            )
                        )
                        if response.is_redirect or 300 <= response.status_code < 400:
                            redirect_url = _validated_storage_redirect(
                                response.headers.get("location")
                            )
                            response = stack.enter_context(
                                self._client.stream("GET", redirect_url)
                            )
                        if response.is_redirect or 300 <= response.status_code < 400:
                            raise _safe_error(f"{product}: unexpected redirect")
                        if response.status_code in (401, 403):
                            raise _safe_error(f"{product}: authentication failed")
                        if _is_retryable_status(response.status_code):
                            last_retryable = f"{product}: transient HTTP {response.status_code}"
                            LOGGER.warning(
                                "Codex product request is retryable",
                                extra={"product": product, "status_code": response.status_code},
                            )
                            if attempt < self._config.max_retries:
                                time.sleep(self._backoff_seconds(attempt))
                                continue
                            raise _safe_error(last_retryable)
                        if response.status_code >= 400:
                            raise _safe_error(f"{product}: HTTP request failed")
                        content_type = response.headers.get("content-type")
                        if not _content_type_allowed(content_type):
                            raise _safe_error(f"{product}: unexpected content type")
                        with tempfile.NamedTemporaryFile(
                            mode="wb",
                            dir=destination,
                            prefix=f".{product}.",
                            suffix=".partial",
                            delete=False,
                        ) as handle:
                            temporary_path = Path(handle.name)
                        sha256, compressed_bytes = _write_stream(
                            response, temporary_path, self._config.max_compressed_bytes
                        )
                        payload = temporary_path.read_bytes()
                        try:
                            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as gzip_stream:
                                decompressed = gzip_stream.read(
                                    self._config.max_decompressed_bytes + 1
                                )
                        except (OSError, EOFError, zlib.error):
                            raise _safe_error(f"{product}: invalid gzip payload") from None
                        if len(decompressed) > self._config.max_decompressed_bytes:
                            raise _safe_error(f"{product}: decompressed response exceeds limit")
                        try:
                            headers, rows = _read_rows(product, payload)
                        except (ValidationError, OSError):
                            raise _safe_error(f"{product}: schema validation failed") from None
                        temporary_path.replace(final_path)
                        temporary_path = None
                        return ProductObservation(
                            product=product,
                            filename=filename,
                            sha256=sha256,
                            compressed_bytes=compressed_bytes,
                            row_count=len(rows),
                            schema_columns=tuple(headers),
                            status_code=response.status_code,
                            content_type=content_type,
                            content_length=response.headers.get("content-length"),
                            etag=response.headers.get("etag"),
                            last_modified=response.headers.get("last-modified"),
                            generation=response.headers.get("x-goog-generation"),
                            observed_at_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                        )
                except httpx.TimeoutException:
                    if temporary_path is not None:
                        temporary_path.unlink(missing_ok=True)
                        temporary_path = None
                    last_retryable = f"{product}: request timed out"
                    LOGGER.warning("Codex product request timed out", extra={"product": product})
                    if attempt < self._config.max_retries:
                        time.sleep(self._backoff_seconds(attempt))
                        continue
                    raise _safe_error(last_retryable) from None
                except httpx.RequestError:
                    if temporary_path is not None:
                        temporary_path.unlink(missing_ok=True)
                        temporary_path = None
                    last_retryable = f"{product}: network request failed"
                    LOGGER.warning("Codex product request failed", extra={"product": product})
                    if attempt < self._config.max_retries:
                        time.sleep(self._backoff_seconds(attempt))
                        continue
                    raise _safe_error(last_retryable) from None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        raise _safe_error(last_retryable or f"{product}: acquisition failed")

    def acquire_all(self) -> tuple[ProductObservation, ...]:
        output_dir = self._config.output_dir
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".fafb-v783-staging-", dir=output_dir.parent
        ) as staging_name:
            staging = Path(staging_name)
            observations = tuple(
                self.download_product(product, destination=staging) for product in PRODUCTS
            )
            bundle = {
                observation.product: (staging / observation.filename).read_bytes()
                for observation in observations
            }
            report = validate_bundle(bundle)
            if not report.valid:
                raise _safe_error("downloaded FAFB bundle failed cross-product validation")
            _, connection_rows = _read_rows(
                "connections_princeton", bundle["connections_princeton"]
            )
            threshold = pair_threshold(connection_rows)
            manifest = {
                "manifest_version": 1,
                "data_kind": "observed",
                "dataset": "flywire-fafb",
                "snapshot": SNAPSHOT,
                "portal_url": f"{PORTAL_URL}?dataset={DATASET}",
                "resource_url_template": (
                    f"{RESOURCE_URL}?data_product={{product}}&dataset={DATASET}"
                    "&api_token=<redacted>"
                ),
                "license": LICENSE,
                "citations": list(CITATIONS),
                "importer_commit": self._config.importer_commit,
                "inventory": {
                    "source": "human-approved-reviewed-contract",
                    "portal_enumerated": False,
                    "products": list(PRODUCTS),
                },
                "validation": {
                    "valid": report.valid,
                    "source_rows_below_five": report.products[
                        "connections_princeton"
                    ].source_rows_below_five,
                    "pairs_below_five": sum(
                        total < 5 for total in threshold.pair_totals.values()
                    ),
                    "threshold_policy": "pair-level-sum-across-neuropils",
                    "threshold_synapses": threshold.threshold,
                },
                "products": [
                    {"name": observation.product, **observation.__dict__}
                    for observation in observations
                ],
            }
            _atomic_write_bytes(staging / "manifest.json", manifest_bytes(manifest))
            _publish_staged(staging, output_dir)
            return observations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acquire approved FlyWire FAFB v783 products")
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/fafb_v783"))
    parser.add_argument(
        "--approved-reviewed-contract",
        action="store_true",
        help=(
            "proceed with the human-approved four-product contract when "
            "Codex inventory is unavailable"
        ),
    )
    args = parser.parse_args(argv)
    token = os.environ.get("CODEX_API_TOKEN")
    if not token:
        print("CODEX_API_TOKEN is not set; no acquisition was attempted", file=sys.stderr)
        return 2
    try:
        config = AcquisitionConfig(
            output_dir=args.output_dir,
            importer_commit=_current_importer_commit(),
        )
        with CodexAcquirer(token, config) as acquirer:
            acquirer.discover_inventory(approved_contract=args.approved_reviewed_contract)
            observations = acquirer.acquire_all()
        print(json.dumps([observation.__dict__ for observation in observations], sort_keys=True))
        return 0
    except AcquisitionError as exc:
        print(redact(str(exc)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
