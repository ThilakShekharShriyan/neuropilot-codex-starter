# Development setup (macOS / Apple Silicon)

## Principles
- Use Homebrew for system tools, `rustup` for Rust, `uv` for Python, and `pnpm` for frontend dependencies.
- Pin versions in project manifests/lockfiles once the scaffold is created.
- Do not install every optional scientific package on day one.

## Inspect first

```bash
uname -m
sw_vers
df -h .
system_profiler SPHardwareDataType
xcode-select -p
git --version
rustc --version
cargo --version
python3 --version
uv --version
node --version
pnpm --version
```

## Prerequisites

Install only missing items, after reviewing the inspection report:

```bash
xcode-select --install
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install git rustup-init uv node pnpm
```

If `rustup-init` is not the preferred Homebrew package available on the machine, use the official rustup installation instructions at https://rustup.rs.

For Rust:
```bash
rustup default stable
rustup component add rustfmt clippy
```

For Python:
```bash
uv python install 3.12
```

For frontend:
```bash
corepack enable
```

## Project commands (once scaffolded)

```bash
# Python
uv sync --dev
uv run pytest
uv run ruff check .
uv run ruff format --check .

# Rust
cargo fmt --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace

# Frontend
pnpm install
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

## FlyGym

Start with the upstream installation guide and interactive viewer:
- https://neuromechfly.org/
- https://neuromechfly.org/2.1.0/installation/

Use the CPU path first. FlyGym 2.x is a major API rewrite compared with 1.x; do not mix old tutorials or old package assumptions with the v2 API. Verify current release and Python compatibility before pinning.

GPU/Warp instructions are environment-specific. The documented GPU path expects a GPU runtime; do not assume macOS Apple Silicon is supported by the same Warp/MJWarp path. Validate exact support or use a Linux NVIDIA cloud machine only after a CPU baseline exists.

## Optional desktop packaging

Tauri 2 can package a Vite frontend with a Rust backend. Add it only after the web dashboard is useful and stable. Official prerequisites: https://tauri.app/start/prerequisites/
