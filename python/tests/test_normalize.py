from __future__ import annotations

import hashlib
import json
from pathlib import Path

from neuropilot_core.fixtures import synthetic_bundle
from neuropilot_core.normalize import normalize


def test_normalized_manifest_preserves_source_product_provenance(tmp_path: Path) -> None:
    bundle = synthetic_bundle()
    raw = tmp_path / "raw" / "versions" / "v-0000000000000000"
    raw.mkdir(parents=True)
    products = []
    for product, payload in bundle.items():
        filename = f"{product}.csv.gz"
        (raw / filename).write_bytes(payload)
        products.append(
            {
                "name": product,
                "product": product,
                "filename": filename,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "row_count": 3,
            }
        )
    source = {
        "dataset": "flywire-fafb",
        "snapshot": "783",
        "license": "CC BY-NC 4.0",
        "citations": ["https://codex.flywire.ai/faq"],
        "products": products,
    }
    source_bytes = json.dumps(source, sort_keys=True, separators=(",", ":")).encode()
    (raw / "manifest.json").write_bytes(source_bytes)
    pointer = tmp_path / "raw" / "CURRENT.json"
    pointer.write_text(
        json.dumps(
            {
                "version": "v-0000000000000000",
                "manifest_sha256": hashlib.sha256(source_bytes).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    manifest = normalize(tmp_path / "raw", tmp_path / "normalized")
    assert manifest["source_manifest_sha256"] == hashlib.sha256(source_bytes).hexdigest()
    provenance = manifest["source_provenance"]
    assert provenance["license"] == "CC BY-NC 4.0"
    assert len(provenance["products"]) == 4
    assert provenance["products"][0]["sha256"] == products[0]["sha256"]
