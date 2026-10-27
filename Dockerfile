FROM python:3.14-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first so this layer is cached across source changes.
# INSTALL_DEV=true adds the [dev] extras (pytest) for a test image.
ARG INSTALL_DEV=false
COPY pyproject.toml README.md LICENSE ./
RUN if [ "$INSTALL_DEV" = "true" ]; then pip install ".[dev]"; else pip install .; fi \
    && rm -rf build *.egg-info README.md

COPY src/ ./

EXPOSE 8000
CMD ["./start-django"]
