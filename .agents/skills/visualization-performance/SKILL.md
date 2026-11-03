---
name: visualization-performance
description: Use when building or profiling NeuroPilot React, TypeScript, Three.js visualizations, interactive connectome graphs, timelines, or simulation dashboards.
---

# Visualization workflow

1. Build from real schema-backed data; do not make mock values look scientific.
2. Profile the scene before optimizing.
3. Target 60 FPS for the normal local scene; record frame-time p50/p95.
4. Keep simulation/network processing outside the render loop.
5. Bound event history and decimate long time series.
6. Reuse geometry/materials and use instancing/LOD for repeated objects.
7. Update only changed buffers; avoid per-frame allocations.
8. Provide loading, empty, error, disconnected, and degraded states.
9. Support keyboard controls and reduced motion.
10. Display source, dataset snapshot, and live/replay/synthetic status.
