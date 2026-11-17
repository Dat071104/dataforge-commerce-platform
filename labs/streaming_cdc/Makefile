PYTHON ?= python

.PHONY: w8-up w8-down w8-register-connector w8-seed w8-mutate w8-reset

w8-up:
	cd ../.. && $(PYTHON) -m labs.streaming_cdc.cli up

w8-down:
	cd ../.. && $(PYTHON) -m labs.streaming_cdc.cli down

w8-register-connector:
	cd ../.. && $(PYTHON) -m labs.streaming_cdc.cli register-connector

w8-seed:
	cd ../.. && $(PYTHON) -m labs.streaming_cdc.cli seed

w8-mutate:
	cd ../.. && $(PYTHON) -m labs.streaming_cdc.cli mutate

w8-reset:
	cd ../.. && $(PYTHON) -m labs.streaming_cdc.cli reset
