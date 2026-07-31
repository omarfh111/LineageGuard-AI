FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
# Build isolation installs the setuptools version declared by pyproject. Use
# patient network settings because the local hackathon environment can have
# intermittent access to PyPI during a Docker rebuild. Install dependencies
# before copying application code so ordinary source changes reuse this layer.
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=5
RUN mkdir app \
    && touch app/__init__.py \
    && python -m pip install --no-cache-dir . \
    && rm -rf app

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
