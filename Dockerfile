FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir poetry && poetry config virtualenvs.create false

COPY pyproject.toml ./
RUN poetry install --only main --no-root --no-interaction --no-ansi

COPY . .

# Download Tailwind CSS standalone CLI and build
ARG TAILWIND_VERSION=v3.4.17
RUN ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "amd64" ]; then TAILWIND_ARCH="x64"; else TAILWIND_ARCH="$ARCH"; fi && \
    mkdir -p bin && \
    apt-get update && apt-get install -y --no-install-recommends curl && \
    curl -sLo bin/tailwindcss "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-${TAILWIND_ARCH}" && \
    chmod +x bin/tailwindcss && \
    apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
RUN ./bin/tailwindcss -i static/css/input.css -o static/css/styles.css --minify

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
