FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
# Build isolation installs the setuptools version declared by pyproject. Use
# patient network settings because the local hackathon environment can have
# intermittent access to PyPI during a Docker rebuild.
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=5
RUN python -m pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
