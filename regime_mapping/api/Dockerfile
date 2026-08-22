FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# core/ is imported by api/, worker/ and mcp_server/ alike, so the whole
# project is copied rather than just this service's directory.
COPY . .
EXPOSE 8100
CMD ["python", "api/main.py"]
