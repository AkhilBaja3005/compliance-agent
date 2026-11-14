.PHONY: install test eval lint audit demo doctor serve docker

install:
	python -m venv .venv && .venv/bin/pip install -e ".[dev]"

test:
	.venv/bin/python -m pytest -q

eval:
	.venv/bin/graphite eval

lint:
	.venv/bin/ruff check src tests

audit:
	.venv/bin/pip-audit

demo:
	.venv/bin/graphite demo

doctor:
	.venv/bin/graphite doctor

serve:
	.venv/bin/uvicorn src.api:app --reload --port 8000

docker:
	docker build -t graphite .
