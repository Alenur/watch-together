FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 app
COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app
COPY tests ./tests
USER app

CMD ["python", "-m", "app"]
