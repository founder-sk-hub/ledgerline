# Public demo image: replay mode, no API keys, serves the prebuilt UI.
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY data/samples data/samples
COPY data/replays data/replays
COPY frontend/dist frontend/dist
ENV LEDGERLINE_MODE=replay PORT=7860 LEDGERLINE_DB=/tmp/ledgerline.db LEDGERLINE_RUNTIME=/tmp/ledgerline-runtime
EXPOSE 7860
CMD ["sh", "-c", "uvicorn --app-dir backend ledgerline.api:app --host 0.0.0.0 --port ${PORT}"]
