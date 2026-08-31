FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY graphiti_mcp.py .

EXPOSE 8000

CMD ["python", "graphiti_mcp.py", "--server"]
