# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements.lock ./
# Install the pinned Linux set from ./wheels if present (see `make wheels`), otherwise from PyPI.
COPY wheels/ /wheels/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-index --find-links /wheels -r requirements.lock \
    || pip install --default-timeout=120 --retries 10 -r requirements.lock
COPY backend ./backend
COPY frontend ./frontend
COPY data ./data
COPY tests ./tests
COPY pytest.ini .
EXPOSE 8000
# Hosting platforms (Render, Railway, Fly) pass the port in $PORT; default 8000.
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
