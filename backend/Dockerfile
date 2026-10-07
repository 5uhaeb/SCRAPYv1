FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

WORKDIR /app

COPY requirements.txt ./

# Playwright's --with-deps needs root during image build so Chromium's shared
# libraries are baked into the container instead of depending on Render's native runtime.
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium

COPY . .

RUN useradd --create-home appuser && chown -R appuser:appuser /app /opt/playwright
USER appuser

CMD uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}
