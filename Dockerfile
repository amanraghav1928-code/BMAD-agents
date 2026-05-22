FROM ghcr.io/berriai/litellm:main-latest

WORKDIR /app

# Copy only the config — secrets come from Railway environment variables
COPY litellm_config.yaml .

EXPOSE 4000

CMD ["--config", "litellm_config.yaml", "--port", "4000", "--host", "0.0.0.0"]
