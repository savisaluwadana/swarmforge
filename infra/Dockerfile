FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/services/swarmforge/src
COPY services/swarmforge/requirements-benchmark.txt services/swarmforge/requirements-persistence.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements-persistence.txt && useradd --create-home app
COPY services/swarmforge/src services/swarmforge/src
COPY db db
COPY contracts contracts
USER app
CMD ["python","-m","swarmforge.worker.main"]
