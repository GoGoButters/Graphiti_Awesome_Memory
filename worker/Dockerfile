FROM python:3.11-slim

WORKDIR /app

COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/adapter/app /app/app
COPY worker/worker.py .

CMD ["python", "worker.py"]
