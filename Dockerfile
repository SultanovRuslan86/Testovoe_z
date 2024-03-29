FROM python:3.9-slim

ENV ENVIRONMENT=production

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "our_bot.py"]