FROM python:3.11-slim

WORKDIR /app

COPY mcp-server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp-server/ .

ENV PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "uvicorn http_server:app --host 0.0.0.0 --port ${PORT:-8080}"]
