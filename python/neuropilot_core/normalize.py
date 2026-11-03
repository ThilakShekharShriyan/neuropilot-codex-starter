"""Build a bounded, deterministic JSONL graph artifact from an acquired bundle."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
from typing import TextIO

from .acquisition import resolve_current

DATASET = "flywire-fafb"
SNAPSHOT = "783"
SCHEMA_VERSION = 1


def _rows(path: Path) -> TextIO:
    return gzip.open(path, "rt", encoding="utf-8", newline="")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    with path.open("wb") as handle:
        for row in rows:
            payload = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
            handle.write(payload)
            digest.update(payload)
    return digest.hexdigest()


def normalize(input_dir: Path, output_dir: Path) -> dict[str, object]:
    """Normalize the current acquired version without inventing annotations."""
    version_dir = resolve_current(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    annotations: dict[str, dict[str, object]] = {}
    with _rows(version_dir / "classification.csv.gz") as handle:
        for row in csv.DictReader(handle):
            annotations[row["root_id"]] = {
                key: (value or None)
                for key, value in row.items()
                if key != "root_id"
            }
    with _rows(version_dir / "consolidated_cell_types.csv.gz") as handle:
        for row in csv.DictReader(handle):
            annotations.setdefault(row["root_id"], {}).update(
                {
                    "primary_type": row["primary_type"] or None,
                    "additional_types": row["additional_type(s)"] or None,
                }
            )

    neurons: list[dict[str, object]] = []
    with _rows(version_dir / "neurons.csv.gz") as handle:
        for row in csv.DictReader(handle):
            root_id = row["root_id"]
            neuron = {
                "root_id": root_id,
                "primary_type": annotations.get(root_id, {}).get("primary_type"),
                "group": row["group"] or None,
                "nt_type": row["nt_type"] or None,
            }
            neurons.append(neuron)

    totals: dict[tuple[str, str], int] = {}
    with _rows(version_dir / "connections_princeton.csv.gz") as handle:
        for row in csv.DictReader(handle):
            pair = (row["pre_root_id"], row["post_root_id"])
            totals[pair] = totals.get(pair, 0) + int(row["syn_count"])

    neuron_ids = {row["root_id"] for row in neurons}
    edges: list[dict[str, object]] = []
    with _rows(version_dir / "connections_princeton.csv.gz") as handle:
        for row in csv.DictReader(handle):
            pair = (row["pre_root_id"], row["post_root_id"])
            if totals[pair] < 5:
                continue
            if pair[0] not in neuron_ids or pair[1] not in neuron_ids:
                raise ValueError("connection endpoint is absent from neurons")
            edges.append(
                {
                    "pre_root_id": pair[0],
                    "post_root_id": pair[1],
                    "neuropil": row["neuropil"],
                    "synapse_count": int(row["syn_count"]),
                    "nt_type": row["nt_type"] or None,
                }
            )
    neurons.sort(key=lambda row: int(str(row["root_id"])))
    edges.sort(
        key=lambda row: (
            str(row["pre_root_id"]),
            str(row["post_root_id"]),
            str(row["neuropil"]),
        )
    )
    neuron_hash = _write_jsonl(output_dir / "neurons.jsonl", neurons)
    edge_hash = _write_jsonl(output_dir / "edges.jsonl", edges)
    artifact_hash = hashlib.sha256(f"{neuron_hash}:{edge_hash}".encode()).hexdigest()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "data_kind": "observed",
        "dataset": DATASET,
        "snapshot": SNAPSHOT,
        "artifact_hash": artifact_hash,
        "source_manifest": str((version_dir / "manifest.json").name),
        "threshold_policy": "pair-level-sum-across-neuropils",
        "threshold_synapses": 5,
        "threshold_applied": True,
        "rows": {"neurons": len(neurons), "edges": len(edges)},
        "source_product": "connections_princeton",
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize acquired FAFB v783 data")
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw/fafb_v783"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/normalized/fafb_v783"))
    args = parser.parse_args()
    print(json.dumps(normalize(args.input_dir, args.output_dir), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
