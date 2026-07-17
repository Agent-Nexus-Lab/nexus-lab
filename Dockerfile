FROM python:3.10-slim

WORKDIR /app
COPY . .
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
RUN pip install --no-cache-dir -r requirements-dev.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
ENV PYTHONPATH=/app:/app/database:/app/experiments:/app/backend
