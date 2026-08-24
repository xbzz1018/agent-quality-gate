FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements-runtime.lock ./
RUN pip install --no-cache-dir --no-deps -r requirements-runtime.lock
COPY requirements.txt pyproject.toml README.md ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY datasets ./datasets
RUN pip install --no-cache-dir --no-deps --no-build-isolation .

CMD ["uvicorn", "agent_quality_harness.main:app", "--host", "0.0.0.0", "--port", "8000"]
