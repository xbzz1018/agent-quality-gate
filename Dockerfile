FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt requirements-runtime.txt pyproject.toml README.md ./
COPY requirements-runtime-server.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt \
    && pip install --no-cache-dir -r requirements-runtime-server.txt
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY datasets ./datasets
RUN pip install --no-cache-dir --no-deps .

CMD ["uvicorn", "agent_quality_harness.main:app", "--host", "0.0.0.0", "--port", "8000"]
