.PHONY: generate-cim check-cim test lint

generate-cim:
	python3 scripts/generate_cim.py

check-cim: generate-cim
	git diff --exit-code src/observra/core/cim.py

test:
	pytest tests/ -x

test-all:
	pytest tests/ src/observra/adapters -x

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

format:
	ruff format src/ tests/
