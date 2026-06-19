# bbv2 dev — start the backend API and the dashboard together.
#   make dev        backend (:8080) + dashboard (:5173); Ctrl-C stops both
#   make backend    just the bbv2 API
#   make frontend   just the dashboard
#   make install    create venv + python deps + dashboard npm deps

.DEFAULT_GOAL := dev
.PHONY: dev backend frontend install

PORT ?= 8080
PY := .venv/bin/python

dev:
	@test -x $(PY) || { echo "No .venv — run 'make install' first."; exit 1; }
	@test -d dashboard/node_modules || { echo "No dashboard deps — run 'make install' first."; exit 1; }
	@echo "▶ backend   http://localhost:$(PORT)"
	@echo "▶ dashboard http://localhost:5173   (Ctrl-C stops both)"
	@trap 'kill 0' INT TERM EXIT; \
	$(PY) -m bbv2 serve --port $(PORT) & \
	( cd dashboard && npm run dev ) & \
	wait

backend:
	$(PY) -m bbv2 serve --port $(PORT)

frontend:
	cd dashboard && npm run dev

install:
	python3 -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt
	cd dashboard && npm install
