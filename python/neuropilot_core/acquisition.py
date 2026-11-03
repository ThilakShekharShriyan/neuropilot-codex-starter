"""Secure, sequential acquisition of the approved Codex FAFB products.

This module owns network access.  It deliberately does not share an HTTP
client with the importer, and it never exposes authenticated URLs in errors
or logs.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

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
        if config.max_retries < 0:
            raise AcquisitionError("max_retries must not be negative")
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

    def inspect_portal(self) -> httpx.Response:
        """Fetch only the portal page; product bytes are never requested."""
        try:
            response = self._client.get(PORTAL_URL, params={"dataset": DATASET})
        except httpx.TimeoutException as exc:
            raise _safe_error("Codex portal inspection timed out") from exc
        except httpx.RequestError as exc:
            raise _safe_error("Codex portal inspection failed") from exc
        if response.is_redirect or 300 <= response.status_code < 400:
            raise _safe_error("Codex portal returned an unexpected redirect")
        if response.status_code >= 400:
            raise _safe_error(f"Codex portal returned HTTP {response.status_code}")
        missing = [product for product in PRODUCTS if product not in response.text]
        if missing:
            raise _safe_error("Codex portal inventory did not expose all approved products")
        return response

    def download_product(self, product: str) -> ProductObservation:
        if product not in PRODUCT_SCHEMAS:
            raise AcquisitionError(f"unsupported product: {product}")
        self._config.output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{product}.csv.gz"
        final_path = self._config.output_dir / filename
        temporary_path: Path | None = None
        last_retryable: str | None = None
        try:
            for attempt in range(self._config.max_retries + 1):
                try:
                    with self._client.stream(
                        "GET",
                        RESOURCE_URL,
                        params={
                            "data_product": product,
                            "dataset": DATASET,
                            "api_token": self._token,
                        },
                    ) as response:
                        if response.is_redirect or 300 <= response.status_code < 400:
                            raise _safe_error(f"{product}: unexpected redirect")
                        if response.status_code in (401, 403):
                            raise _safe_error(f"{product}: authentication failed")
                        if _is_retryable_status(response.status_code):
                            last_retryable = f"{product}: transient HTTP {response.status_code}"
                            if attempt < self._config.max_retries:
                                time.sleep(self._config.retry_backoff_seconds * (2**attempt))
                                continue
                            raise _safe_error(last_retryable)
                        if response.status_code >= 400:
                            raise _safe_error(f"{product}: HTTP request failed")
                        content_type = response.headers.get("content-type")
                        if not _content_type_allowed(content_type):
                            raise _safe_error(f"{product}: unexpected content type")
                        with tempfile.NamedTemporaryFile(
                            mode="wb",
                            dir=self._config.output_dir,
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
                        except (OSError, EOFError, zlib.error) as exc:
                            raise _safe_error(f"{product}: invalid gzip payload") from exc
                        if len(decompressed) > self._config.max_decompressed_bytes:
                            raise _safe_error(f"{product}: decompressed response exceeds limit")
                        try:
                            headers, rows = _read_rows(product, payload)
                        except (ValidationError, OSError) as exc:
                            raise _safe_error(f"{product}: schema validation failed") from exc
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
                except httpx.TimeoutException as exc:
                    if temporary_path is not None:
                        temporary_path.unlink(missing_ok=True)
                        temporary_path = None
                    last_retryable = f"{product}: request timed out"
                    if attempt < self._config.max_retries:
                        time.sleep(self._config.retry_backoff_seconds * (2**attempt))
                        continue
                    raise _safe_error(last_retryable) from exc
                except httpx.RequestError as exc:
                    if temporary_path is not None:
                        temporary_path.unlink(missing_ok=True)
                        temporary_path = None
                    last_retryable = f"{product}: network request failed"
                    if attempt < self._config.max_retries:
                        time.sleep(self._config.retry_backoff_seconds * (2**attempt))
                        continue
                    raise _safe_error(last_retryable) from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        raise _safe_error(last_retryable or f"{product}: acquisition failed")

    def acquire_all(self) -> tuple[ProductObservation, ...]:
        observations_list: list[ProductObservation] = []
        try:
            for product in PRODUCTS:
                observations_list.append(self.download_product(product))
        except BaseException:
            for observation in observations_list:
                (self._config.output_dir / observation.filename).unlink(missing_ok=True)
            raise
        observations = tuple(observations_list)
        bundle = {
            observation.product: (self._config.output_dir / observation.filename).read_bytes()
            for observation in observations
        }
        report = validate_bundle(bundle)
        if not report.valid:
            for observation in observations:
                (self._config.output_dir / observation.filename).unlink(missing_ok=True)
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
            "products": [observation.__dict__ for observation in observations],
        }
        _atomic_write_bytes(self._config.output_dir / "manifest.json", manifest_bytes(manifest))
        return observations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acquire approved FlyWire FAFB v783 products")
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/fafb_v783"))
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
            acquirer.inspect_portal()
            observations = acquirer.acquire_all()
        print(json.dumps([observation.__dict__ for observation in observations], sort_keys=True))
        return 0
    except AcquisitionError as exc:
        print(redact(str(exc)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
