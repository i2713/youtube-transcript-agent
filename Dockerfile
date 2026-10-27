FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY transcript.py server.py ./
RUN useradd --create-home appuser
USER appuser
ENV PORT=8000
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-access-log"]
