PYTHON ?= python3
export PYTHONPATH := services/swarmforge/src

.PHONY: test demo replay
test:
	$(PYTHON) -m unittest discover -s services/swarmforge/tests -v

demo:
	$(PYTHON) -m swarmforge.cli run examples/two-robot-outage.json --seed 42 --output artifacts/demo.json

replay:
	$(PYTHON) -m swarmforge.cli replay artifacts/demo.json

.PHONY: demo-scoped replay-scoped
demo-scoped:
	$(PYTHON) -m swarmforge.cli run examples/two-robot-outage.json --algorithm scoped_lease --seed 42 --output artifacts/scoped.json

replay-scoped:
	$(PYTHON) -m swarmforge.cli replay artifacts/scoped.json

.PHONY: demo-auction replay-auction
demo-auction:
	$(PYTHON) -m swarmforge.cli run examples/two-robot-outage.json --algorithm local_auction --seed 42 --output artifacts/auction.json

replay-auction:
	$(PYTHON) -m swarmforge.cli replay artifacts/auction.json
