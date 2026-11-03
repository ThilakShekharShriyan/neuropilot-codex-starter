"""Deterministic schema-matched M1 synthetic fixture."""

from __future__ import annotations

import csv
import gzip
import io

from .importer import PRODUCT_SCHEMAS


def _gzip_csv(product: str, rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=PRODUCT_SCHEMAS[product], lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return gzip.compress(output.getvalue().encode("utf-8"), mtime=0)


def synthetic_bundle() -> dict[str, bytes]:
    return {
        "neurons": _gzip_csv(
            "neurons",
            [
                {
                    "root_id": "100",
                    "group": "fixture",
                    "nt_type": "ACh",
                    "nt_type_score": "0.9",
                    "da_avg": "",
                    "ser_avg": "",
                    "gaba_avg": "",
                    "glut_avg": "",
                    "ach_avg": "0.9",
                    "oct_avg": "",
                },
                {
                    "root_id": "200",
                    "group": "fixture",
                    "nt_type": "GABA",
                    "nt_type_score": "0.8",
                    "da_avg": "",
                    "ser_avg": "",
                    "gaba_avg": "0.8",
                    "glut_avg": "",
                    "ach_avg": "",
                    "oct_avg": "",
                },
                {
                    "root_id": "300",
                    "group": "fixture",
                    "nt_type": "Glu",
                    "nt_type_score": "0.7",
                    "da_avg": "",
                    "ser_avg": "",
                    "gaba_avg": "",
                    "glut_avg": "0.7",
                    "ach_avg": "",
                    "oct_avg": "",
                },
            ],
        ),
        "classification": _gzip_csv(
            "classification",
            [
                {
                    "root_id": "100",
                    "flow": "central",
                    "super_class": "central",
                    "class": "fixture",
                    "sub_class": "fixture",
                    "hemilineage": "fixture",
                    "side": "left",
                    "nerve": "",
                },
                {
                    "root_id": "200",
                    "flow": "central",
                    "super_class": "central",
                    "class": "fixture",
                    "sub_class": "fixture",
                    "hemilineage": "fixture",
                    "side": "right",
                    "nerve": "",
                },
            ],
        ),
        "consolidated_cell_types": _gzip_csv(
            "consolidated_cell_types",
            [
                {"root_id": "100", "primary_type": "fixture_source", "additional_type(s)": ""},
                {"root_id": "200", "primary_type": "fixture_target", "additional_type(s)": ""},
            ],
        ),
        "connections_princeton": _gzip_csv(
            "connections_princeton",
            [
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
                {
                    "pre_root_id": "300",
                    "post_root_id": "300",
                    "neuropil": "C",
                    "syn_count": "5",
                    "nt_type": "Glu",
                },
            ],
        ),
    }
