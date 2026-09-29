FROM mcr.microsoft.com/playwright/python:v1.51.0-noble
WORKDIR /worker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
ENV BROWSER_HEADLESS=true \
    WORKER_CONCURRENCY=1 \
    PORT=8090
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8090')+'/health',timeout=4)" || exit 1
# Railway (and most PaaS hosts) inject $PORT at runtime; shell form lets it expand.
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-8090}
