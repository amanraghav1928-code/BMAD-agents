FROM ghcr.io/berriai/litellm:main-latest

WORKDIR /app

# Copy only the config — secrets come from Railway environment variables
COPY litellm_config.yaml .

# Railway injects $PORT dynamically — we must listen on it
CMD ["sh", "-c", "litellm --config litellm_config.yaml --port ${PORT:-4000} --host 0.0.0.0"]
