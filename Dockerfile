FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir poetry && poetry config virtualenvs.create false

COPY pyproject.toml ./
RUN poetry install --only main --no-root --no-interaction --no-ansi

COPY . .

# Build Tailwind CSS
RUN ./bin/tailwindcss -i static/css/input.css -o static/css/styles.css --minify

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
