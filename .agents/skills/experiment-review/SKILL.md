---
name: experiment-review
description: Use before accepting a NeuroPilot milestone or scientific experiment; audit reproducibility, provenance, tests, metrics, uncertainty, performance, and claim validity.
---

# Experiment review checklist

1. Identify milestone and acceptance criteria.
2. Verify the run command from a clean environment.
3. Verify dataset/model provenance and licensing.
4. Check random seeds, configuration capture, and software versions.
5. Inspect train/test or baseline/perturbation splits for leakage where applicable.
6. Check sample counts, uncertainty, and negative results.
7. Verify that UI labels distinguish measured, simulated, synthetic, and replayed data.
8. Run relevant formatters, linters, tests, integration tests, and smoke tests.
9. Inspect logs, resource use, frame-time and latency metrics.
10. Reject unsupported scientific claims and request corrections before sign-off.
