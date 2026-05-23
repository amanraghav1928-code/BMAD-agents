FROM ghcr.io/berriai/litellm:main-latest

WORKDIR /app

# Copy config — secrets come from Railway environment variables
COPY litellm_config.yaml .

# Override ENTRYPOINT so we can use sh for $PORT expansion
ENTRYPOINT []
CMD ["sh", "-c", "litellm --config litellm_config.yaml --port ${PORT} --host 0.0.0.0"]
