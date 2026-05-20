FROM python:3.12-alpine
WORKDIR /app
COPY api.py .
RUN pip install --no-cache-dir fastapi uvicorn psycopg2-binary
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
