FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY bon_llm ./bon_llm
COPY config ./config
RUN pip install --no-cache-dir .

ENV BON_CONFIG_PATH=/app/config/config.yaml
EXPOSE 8000
CMD ["uvicorn", "bon_llm.api:app", "--host", "0.0.0.0", "--port", "8000"]
