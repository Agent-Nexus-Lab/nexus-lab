FROM python:3.10-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements-dev.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 增加/app/database，routers就能直接导入
ENV PYTHONPATH=/app:/app/database:/app/experiments:/app/backend
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
