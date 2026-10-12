FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OMP_THREAD_LIMIT=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY core.py transport.py pdf_flow.py bot.py news_selection.py bpsc_rubric.md ./
COPY selection_skill ./selection_skill
COPY tests ./tests
RUN useradd --create-home --uid 10001 agent && mkdir /data && chown agent:agent /data
USER agent
CMD ["python", "bot.py", "serve"]
