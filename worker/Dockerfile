FROM mcr.microsoft.com/playwright/python:v1.51.0-noble
WORKDIR /worker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
ENV BROWSER_HEADLESS=true
EXPOSE 8090
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8090"]
