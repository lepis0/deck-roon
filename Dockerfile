FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY deck ./deck

ENV DECK_DATA=/data DECK_PORT=8795 PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8795
CMD ["python", "-m", "deck", "serve"]
