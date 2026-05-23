FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for layer caching
COPY agent-api/requirements.txt .

# Install all dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the full project (agent-api needs access to core/)
COPY . .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn agent-api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
