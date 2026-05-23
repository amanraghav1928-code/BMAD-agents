FROM python:3.11-slim

WORKDIR /app

# Install LiteLLM with proxy extras + prisma for PostgreSQL support
RUN pip install --no-cache-dir "litellm[proxy]" prisma

# Run prisma generate so the DB client is ready
RUN python -c "import litellm; print('litellm ok')"

# Copy config — secrets come from Railway environment variables
COPY litellm_config.yaml .

# Railway sets $PORT dynamically
ENV PORT=4000

EXPOSE 4000

CMD ["sh", "-c", "prisma generate --schema /usr/local/lib/python3.11/site-packages/litellm/proxy/schema.prisma 2>/dev/null || true && litellm --config litellm_config.yaml --port ${PORT} --host 0.0.0.0"]
