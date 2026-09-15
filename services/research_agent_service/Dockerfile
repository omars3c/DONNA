FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

COPY . .

EXPOSE 8003

CMD ["uvicorn", "services.research_agent_service.app:app", "--host", "0.0.0.0", "--port", "8003"]
