FROM python:3.12-slim

# Установка необходимых системных утилит
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Создание непривилегированного пользователя appuser (UID/GID 10001)
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/false -m -d /home/appuser appuser

WORKDIR /app

# Копирование ТОЛЬКО backend/requirements.txt для кэширования слоев
COPY backend/requirements.txt /app/requirements.txt

# Установка зависимостей Python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

# Копирование исходного кода бэкенда и доверенных сертификатов
COPY backend/ /app/backend/
COPY backend/certs/ /app/certs/

# Назначение прав пользователю appuser
RUN chown -R appuser:appgroup /app

# Переключение на непривилегированного пользователя
USER appuser

# Рабочая директория
WORKDIR /app/backend

ENV PYTHONPATH=/app/backend
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
