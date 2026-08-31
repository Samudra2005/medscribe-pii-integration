# Packages the middleware so any machine with Docker can run an
# identical copy — no manual Python/package setup needed on their end.

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY span_types.py detectors.py mask_pii.py api.py ./

# Replace this at run time with a real secret — see the docker run
# command below. Never ship a real deployment with this default.
ENV MASKING_API_KEY=changeme-in-real-deployment

EXPOSE 8000

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
