PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: setup demo live dev test samples record record-private frontend

setup:            ## create the Python venv and install everything
	python3 -m venv .venv
	$(PIP) install -q -r backend/requirements.txt
	cd frontend && npm install --no-audit --no-fund
	@test -f .env || cp .env.example .env

frontend:         ## rebuild the UI (a prebuilt copy is committed in frontend/dist)
	cd frontend && npm run build

demo:             ## replay mode: no API keys needed -> http://localhost:8000
	LEDGERLINE_MODE=replay .venv/bin/uvicorn --app-dir backend ledgerline.api:app --port 8000

live:             ## live mode: uses MODEL_API_KEY / BASETEN_API_KEY from .env
	LEDGERLINE_MODE=live .venv/bin/uvicorn --app-dir backend ledgerline.api:app --port 8000

dev:              ## backend with reload; run `cd frontend && npm run dev` in a second terminal
	LEDGERLINE_MODE=live .venv/bin/uvicorn --app-dir backend ledgerline.api:app --port 8000 --reload

test:
	cd backend && ../.venv/bin/python -m pytest -q

samples:          ## regenerate the synthetic batch (macOS fonts)
	$(PY) backend/scripts/generate_samples.py

record:           ## live run on Muse Spark 1.3 + save as replay
	$(PY) backend/scripts/record.py --provider meta --save meta-sample

record-private:   ## live run on Muse Spark Open (Baseten) + save as replay
	$(PY) backend/scripts/record.py --provider private --save private-sample
