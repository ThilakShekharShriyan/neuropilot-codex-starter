.PHONY: check python-check rust-check frontend-check

check: python-check rust-check frontend-check

python-check:
	uv run --project . ruff check python
	uv run --project . pytest

rust-check:
	cargo fmt --all -- --check
	cargo clippy --workspace --all-targets --all-features -- -D warnings
	cargo test --workspace

frontend-check:
	cd apps/dashboard && pnpm typecheck && pnpm build
