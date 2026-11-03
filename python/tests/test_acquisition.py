from __future__ import annotations

import gzip
import hashlib
import traceback
from pathlib import Path

import httpx
import neuropilot_core.acquisition as acquisition
import pytest
from neuropilot_core.acquisition import (
    PRODUCTS,
    AcquisitionConfig,
    AcquisitionError,
    CodexAcquirer,
    _publish_staged,
    manifest_bytes,
    redact,
)
from neuropilot_core.fixtures import synthetic_bundle


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def _config(tmp_path: Path, **kwargs) -> AcquisitionConfig:
    return AcquisitionConfig(
        output_dir=tmp_path, retry_backoff_seconds=0, retry_jitter_seconds=0, **kwargs
    )


def test_missing_token_fails_before_network(tmp_path: Path) -> None:
    with pytest.raises(AcquisitionError, match="missing or invalid"):
        CodexAcquirer("", _config(tmp_path))


def test_successful_stream_is_validated_and_atomically_finalized(tmp_path: Path) -> None:
    payload = synthetic_bundle()["neurons"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["data_product"] == "neurons"
        assert request.url.params["dataset"] == "fafb"
        assert request.url.params["api_token"] == "secret-token"
        return httpx.Response(
            200,
            headers={"content-type": "application/gzip", "etag": "observed"},
            content=payload,
            request=request,
        )

    with CodexAcquirer("secret-token", _config(tmp_path), client=_client(handler)) as acquirer:
        observation = acquirer.download_product("neurons")

    final_path = tmp_path / "neurons.csv.gz"
    assert final_path.read_bytes() == payload
    assert observation.sha256 == hashlib.sha256(payload).hexdigest()
    assert observation.row_count == 3
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_are_not_retried_or_leaked(tmp_path: Path, status: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, content=b'{"error":"bad"}', request=request)

    with CodexAcquirer("secret-token", _config(tmp_path), client=_client(handler)) as acquirer:
        with pytest.raises(AcquisitionError, match="authentication failed") as failure:
            acquirer.download_product("neurons")
    assert calls == 1
    assert "secret-token" not in str(failure.value)
    assert "api_token=" not in str(failure.value)


def test_redirects_are_rejected_without_following(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "https://evil.example/?api_token=secret-token"},
            request=request,
        )

    with CodexAcquirer("secret-token", _config(tmp_path), client=_client(handler)) as acquirer:
        with pytest.raises(AcquisitionError, match="unexpected redirect") as failure:
            acquirer.download_product("neurons")
    assert "secret-token" not in str(failure.value)


def test_transient_429_retries_then_succeeds(tmp_path: Path) -> None:
    payload = synthetic_bundle()["neurons"]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, request=request)
        return httpx.Response(
            200, headers={"content-type": "application/gzip"}, content=payload, request=request
        )

    with CodexAcquirer("secret-token", _config(tmp_path), client=_client(handler)) as acquirer:
        acquirer.download_product("neurons")
    assert calls == 2


def test_transient_5xx_is_bounded(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, request=request)

    with CodexAcquirer(
        "secret-token", _config(tmp_path, max_retries=2), client=_client(handler)
    ) as acquirer:
        with pytest.raises(AcquisitionError, match="transient HTTP 503"):
            acquirer.download_product("neurons")
    assert calls == 3


def test_timeout_cleans_partial_file(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret-token in an unsafe exception", request=request)

    with CodexAcquirer(
        "secret-token", _config(tmp_path, max_retries=1), client=_client(handler)
    ) as acquirer:
        with pytest.raises(AcquisitionError, match="timed out") as failure:
            acquirer.download_product("neurons")
    formatted = "".join(
        traceback.format_exception(failure.type, failure.value, failure.tb)
    )
    assert "secret-token" not in str(failure.value)
    assert "secret-token" not in formatted
    assert "api_token=" not in formatted
    assert failure.value.__cause__ is None
    assert failure.value.__suppress_context__
    assert "secret-token" not in caplog.text
    assert "api_token=" not in caplog.text
    assert not list(tmp_path.iterdir())


def test_connection_failure_traceback_is_credential_free(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "failed https://codex.flywire.ai/api/download_resource?api_token=secret-token",
            request=request,
        )

    with CodexAcquirer(
        "secret-token", _config(tmp_path, max_retries=1), client=_client(handler)
    ) as acquirer:
        with pytest.raises(AcquisitionError, match="network request failed") as failure:
            acquirer.download_product("neurons")
    formatted = "".join(traceback.format_exception(failure.type, failure.value, failure.tb))
    assert "secret-token" not in formatted
    assert "api_token=" not in formatted
    assert failure.value.__cause__ is None
    assert failure.value.__suppress_context__
    assert "secret-token" not in caplog.text
    assert "api_token=" not in caplog.text


def test_retry_exhaustion_traceback_and_logs_are_credential_free(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    with CodexAcquirer(
        "secret-token", _config(tmp_path, max_retries=1), client=_client(handler)
    ) as acquirer:
        with pytest.raises(AcquisitionError, match="transient HTTP 503") as failure:
            acquirer.download_product("neurons")
    formatted = "".join(traceback.format_exception(failure.type, failure.value, failure.tb))
    assert "secret-token" not in formatted
    assert "api_token=" not in formatted
    assert "secret-token" not in caplog.text
    assert "api_token=" not in caplog.text


def test_interrupted_transfer_cleans_partial_file(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise KeyboardInterrupt

    with CodexAcquirer("secret-token", _config(tmp_path), client=_client(handler)) as acquirer:
        with pytest.raises(KeyboardInterrupt):
            acquirer.download_product("neurons")
    assert not list(tmp_path.iterdir())


def test_oversized_compressed_response_is_rejected_and_cleaned(tmp_path: Path) -> None:
    payload = synthetic_bundle()["neurons"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "application/gzip"}, content=payload, request=request
        )

    with CodexAcquirer(
        "secret-token",
        _config(tmp_path, max_compressed_bytes=len(payload) - 1),
        client=_client(handler),
    ) as acquirer:
        with pytest.raises(AcquisitionError, match="compressed response exceeds"):
            acquirer.download_product("neurons")
    assert not list(tmp_path.iterdir())


def test_decompressed_size_limit_is_enforced(tmp_path: Path) -> None:
    payload = synthetic_bundle()["neurons"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "application/gzip"}, content=payload, request=request
        )

    with CodexAcquirer(
        "secret-token", _config(tmp_path, max_decompressed_bytes=1), client=_client(handler)
    ) as acquirer:
        with pytest.raises(AcquisitionError, match="decompressed response exceeds"):
            acquirer.download_product("neurons")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("payload", "message"),
    [(b"not gzip", "invalid gzip"), (gzip.compress(b"\xff\xfe"), "schema validation")],
)
def test_invalid_payloads_are_rejected(tmp_path: Path, payload: bytes, message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "application/gzip"}, content=payload, request=request
        )

    with CodexAcquirer("secret-token", _config(tmp_path), client=_client(handler)) as acquirer:
        with pytest.raises(AcquisitionError, match=message):
            acquirer.download_product("neurons")
    assert not list(tmp_path.iterdir())


def test_unexpected_content_type_and_schema_are_rejected(tmp_path: Path) -> None:
    payload = synthetic_bundle()["neurons"]

    def wrong_type(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "application/json"}, content=payload, request=request
        )

    with CodexAcquirer("secret-token", _config(tmp_path), client=_client(wrong_type)) as acquirer:
        with pytest.raises(AcquisitionError, match="unexpected content type"):
            acquirer.download_product("neurons")

    bad_csv = gzip.compress(b"wrong,header\nvalue\n")

    def wrong_schema(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "application/gzip"}, content=bad_csv, request=request
        )

    with CodexAcquirer("secret-token", _config(tmp_path), client=_client(wrong_schema)) as acquirer:
        with pytest.raises(AcquisitionError, match="schema validation"):
            acquirer.download_product("neurons")


def test_inventory_discovery_fails_closed_without_supported_mechanism(tmp_path: Path) -> None:
    def unexpected_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError("inventory discovery must not scrape the portal")

    with CodexAcquirer(
        "secret-token", _config(tmp_path), client=_client(unexpected_network)
    ) as acquirer:
        with pytest.raises(AcquisitionError, match="no supported authenticated"):
            acquirer.discover_inventory()


def test_acquire_all_writes_token_free_manifest_and_all_products(tmp_path: Path) -> None:
    bundle = synthetic_bundle()

    def handler(request: httpx.Request) -> httpx.Response:
        product = request.url.params["data_product"]
        return httpx.Response(
            200,
            headers={"content-type": "application/gzip"},
            content=bundle[product],
            request=request,
        )

    with CodexAcquirer("secret-token", _config(tmp_path), client=_client(handler)) as acquirer:
        observations = acquirer.acquire_all()

    assert tuple(observation.product for observation in observations) == PRODUCTS
    manifest = (tmp_path / "manifest.json").read_bytes()
    assert b"secret-token" not in manifest
    assert b"api_token=<redacted>" in manifest
    assert b'"pairs_below_five":1' in manifest
    assert b'"source_rows_below_five":3' in manifest
    assert all((tmp_path / f"{product}.csv.gz").exists() for product in PRODUCTS)


def test_bundle_validation_failure_removes_previously_finalized_products(tmp_path: Path) -> None:
    bundle = synthetic_bundle()
    bundle["connections_princeton"] = b"invalid gzip"

    def handler(request: httpx.Request) -> httpx.Response:
        product = request.url.params["data_product"]
        return httpx.Response(
            200,
            headers={"content-type": "application/gzip"},
            content=bundle[product],
            request=request,
        )

    with CodexAcquirer("secret-token", _config(tmp_path), client=_client(handler)) as acquirer:
        with pytest.raises(AcquisitionError):
            acquirer.acquire_all()
    assert not list(tmp_path.iterdir())


def test_staging_failure_preserves_preexisting_output(tmp_path: Path) -> None:
    existing = tmp_path / "neurons.csv.gz"
    existing.write_bytes(b"previous-valid-output")
    bundle = synthetic_bundle()
    bundle["connections_princeton"] = b"invalid gzip"

    def handler(request: httpx.Request) -> httpx.Response:
        product = request.url.params["data_product"]
        return httpx.Response(
            200,
            headers={"content-type": "application/gzip"},
            content=bundle[product],
            request=request,
        )

    with CodexAcquirer("secret-token", _config(tmp_path), client=_client(handler)) as acquirer:
        with pytest.raises(AcquisitionError):
            acquirer.acquire_all()
    assert existing.read_bytes() == b"previous-valid-output"
    assert not list(tmp_path.glob(".fafb-v783-staging-*"))


def test_manifest_write_failure_preserves_preexisting_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = tmp_path / "neurons.csv.gz"
    existing.write_bytes(b"previous-valid-output")
    bundle = synthetic_bundle()

    def handler(request: httpx.Request) -> httpx.Response:
        product = request.url.params["data_product"]
        return httpx.Response(
            200,
            headers={"content-type": "application/gzip"},
            content=bundle[product],
            request=request,
        )

    def fail_manifest(destination: Path, payload: bytes) -> None:
        raise OSError("manifest write failed")

    monkeypatch.setattr("neuropilot_core.acquisition._atomic_write_bytes", fail_manifest)
    with CodexAcquirer("secret-token", _config(tmp_path), client=_client(handler)) as acquirer:
        with pytest.raises(OSError, match="manifest write failed"):
            acquirer.acquire_all()
    assert existing.read_bytes() == b"previous-valid-output"
    assert not list(tmp_path.glob(".fafb-v783-staging-*"))


def test_publication_failure_rolls_back_complete_previous_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "fafb_v783"
    staging = tmp_path / ".fafb-v783-staging-test"
    output.mkdir()
    staging.mkdir()
    previous = {
        "neurons.csv.gz": b"old-neurons",
        "classification.csv.gz": b"old-classification",
        "consolidated_cell_types.csv.gz": b"old-types",
        "connections_princeton.csv.gz": b"old-connections",
        "manifest.json": b"old-manifest",
    }
    replacement = {
        name: value.replace(b"old-", b"new-") for name, value in previous.items()
    }
    for name, value in previous.items():
        (output / name).write_bytes(value)
    for name, value in replacement.items():
        (staging / name).write_bytes(value)

    original_rename = acquisition._rename_path

    def fail_new_directory(source: Path, destination: Path) -> None:
        if source == staging:
            raise OSError("injected publication failure")
        original_rename(source, destination)

    monkeypatch.setattr("neuropilot_core.acquisition._rename_path", fail_new_directory)
    with pytest.raises(OSError, match="injected publication failure"):
        _publish_staged(staging, output)

    assert {path.name: path.read_bytes() for path in output.iterdir()} == previous
    assert {path.name: path.read_bytes() for path in staging.iterdir()} == replacement
    assert not list(tmp_path.glob(".fafb_v783.previous-*"))


def test_manifest_serialization_is_deterministic_and_token_free() -> None:
    manifest = {
        "products": [{"name": "neurons", "sha256": "abc"}],
        "resource_url_template": "https://example.invalid?api_token=<redacted>",
    }
    encoded = manifest_bytes(manifest)
    assert encoded == manifest_bytes(manifest)
    assert b"secret-token" not in encoded
    assert b"api_token=<redacted>" in encoded


def test_redaction_covers_authenticated_urls() -> None:
    diagnostic = redact("GET https://example.invalid?api_token=secret-token&dataset=fafb")
    assert "secret-token" not in diagnostic
    assert "api_token=<redacted>" in diagnostic


def test_products_are_sequentially_defined() -> None:
    assert PRODUCTS == (
        "neurons",
        "classification",
        "consolidated_cell_types",
        "connections_princeton",
    )
