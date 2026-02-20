FROM python:3.11-slim

WORKDIR /app

# Сначала копируем ВСЕ файлы из репозитория
COPY . .

# Затем устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Запускаем бота
CMD ["python", "main.py"]
