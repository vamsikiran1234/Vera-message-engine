FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .
COPY vera_engine ./vera_engine

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn bot:app --host 0.0.0.0 --port ${PORT}"]
