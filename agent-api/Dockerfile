FROM python:3.11-slim

WORKDIR /app

# Copy the full project (agent-api needs access to core/)
COPY . .

# Install all dependencies (requirements.txt is in agent-api/)
RUN pip install --no-cache-dir -r agent-api/requirements.txt

EXPOSE 8000

CMD ["sh", "-c", "uvicorn agent-api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
