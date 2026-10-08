FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/lepis0/deck-roon" \
      org.opencontainers.image.description="Weekly Last.fm-based album picks, played in Roon through TIDAL" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY deck ./deck

ENV DECK_DATA=/data DECK_PORT=8795 PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8795
CMD ["python", "-m", "deck", "serve"]
