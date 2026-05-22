FROM python:3.11-slim

WORKDIR /app

# Install LiteLLM
RUN pip install --no-cache-dir "litellm[proxy]"

# Copy config — secrets come from Railway environment variables
COPY litellm_config.yaml .

# Railway sets $PORT dynamically
ENV PORT=4000

EXPOSE 4000

CMD ["sh", "-c", "litellm --config litellm_config.yaml --port ${PORT} --host 0.0.0.0"]
