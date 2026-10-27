PY ?= .venv/bin/python

.PHONY: all data setup build slotting replenishment capacity kpis test clean

all: build slotting replenishment capacity kpis

setup:
	uv venv .venv && uv pip install --python .venv -r requirements.txt

data:
	./scripts/download_data.sh

build:
	$(PY) -m dso.pipeline build

slotting:
	$(PY) -m dso.pipeline slotting

replenishment:
	$(PY) -m dso.pipeline replenishment

capacity:
	$(PY) -m dso.pipeline capacity

kpis:
	$(PY) -m dso.pipeline kpis

test:
	$(PY) -m pytest -q

clean:
	rm -rf data/work results/* docs/img/*
