PYTHON ?= python3
export PYTHONPATH := services/swarmforge/src

.PHONY: test demo replay
test:
	$(PYTHON) -m unittest discover -s services/swarmforge/tests -v

demo:
	$(PYTHON) -m swarmforge.cli run examples/two-robot-outage.json --seed 42 --output artifacts/demo.json

replay:
	$(PYTHON) -m swarmforge.cli replay artifacts/demo.json
