FROM python:3.12-slim

# 系统依赖：psycopg 需要 libpq + gcc
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# pip 源：使用清华镜像（国内加速，避免超时）
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn

# 先装 requirements（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷源码
COPY . .

EXPOSE 8000

ENV PYTHONUNBUFFERED=1
ENV MEM0_TELEMETRY=false

# 启动前跑数据库迁移，再启动服务
CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000"]
