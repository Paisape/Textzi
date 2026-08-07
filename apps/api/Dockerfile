FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8000
# --no-access-log: uvicorn's default access log prints the full request line, including query
# strings -- a real leak for GET /v1/sms/send-url, whose api_key travels as a query param. The
# app's own DB-backed ApiLog (main.py) already covers legitimate request auditing without ever
# storing the query string, so this loses no real visibility.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
