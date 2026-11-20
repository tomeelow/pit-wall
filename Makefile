.PHONY: setup verify verify-pipeline verify-web contract contract-check ingest export build dev

PY := cd pipeline && uv run --frozen
WEB := cd web && npm run -s

setup:
	cd pipeline && uv sync --frozen
	cd web && npm ci

# The one command CI runs. Green here means green in CI.
verify: verify-pipeline verify-web contract-check

verify-pipeline:
	$(PY) ruff check .
	$(PY) ruff format --check .
	$(PY) pyright
	$(PY) pytest

verify-web:
	$(WEB) typecheck
	$(WEB) lint
	$(WEB) test

# Regenerate JSON Schema and TypeScript types after editing pipeline/src/pitwall/export/contract.py.
contract:
	$(PY) pitwall contract --out ../contract
	$(WEB) contract

# Fails if the committed schemas or generated types differ from what the contract produces.
contract-check:
	@tmp=$$(mktemp -d) && \
	(cd pipeline && uv run --frozen pitwall contract --out $$tmp/schema 2>/dev/null) && \
	(cd web && node scripts/gen-contract.mjs $$tmp/schema $$tmp/ts) && \
	diff -r contract $$tmp/schema && diff -r web/src/contract $$tmp/ts; \
	status=$$?; rm -rf $$tmp; \
	if [ $$status -ne 0 ]; then echo "contract is stale: run 'make contract'"; exit 1; fi; \
	echo "contract up to date"

# One race with ROUND, otherwise every finished race of SEASON.
ingest:
	@test -n "$(SEASON)" || { echo "usage: make ingest SEASON=2024 [ROUND=1]"; exit 2; }
	$(PY) pitwall ingest --season $(SEASON) $(if $(ROUND),--round $(ROUND))

export:
	$(PY) pitwall export

build:
	$(WEB) build

dev:
	$(WEB) dev
