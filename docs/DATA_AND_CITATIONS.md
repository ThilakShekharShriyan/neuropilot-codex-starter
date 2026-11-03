# Data sources, provenance, and scientific boundaries

## Connectome discovery
FlyWire's Codex explorer exposes multiple Drosophila connectome datasets, including FlyWire FAFB, BANC, MANC, MAOL, and MCNS. Dataset availability and download routes differ. For bulk analysis, prefer official static downloads where available; use documented project tooling for datasets not downloadable through the same portal.

Useful references:
- FlyWire apps: https://flywire.ai/apps
- Codex FAQ: https://codex.flywire.ai/faq
- CAVEclient: https://github.com/seung-lab/CAVEclient

## Embodied simulation
NeuroMechFly / FlyGym is a digital twin of adult Drosophila with sensory and motor/environment interaction. The current v2 line is a significant rewrite; pin and document the version used.
- https://neuromechfly.org/
- https://github.com/NeLy-EPFL/flygym

## Provenance record
Every experiment should store:
- dataset name, snapshot/version, source URL, access date, citation, license/terms;
- source file hashes and import script version;
- simulator/library versions;
- config, random seed, and environment;
- whether input is measured, simulated, synthetic, or replayed;
- metrics and uncertainty.

## Scientific limits
A connectome is a wiring diagram, not by itself a complete executable model of neural dynamics or behavior. A simulation result is conditional on the model, parameters, and environment. State what is directly measured versus inferred or simulated.
