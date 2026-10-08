FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/lepis0/deck-roon" \
      org.opencontainers.image.description="Weekly Last.fm-based album picks, played in Roon through TIDAL" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && printf '#!/bin/sh\nexec python -m deck "$@"\n' > /usr/local/bin/deck \
 && chmod +x /usr/local/bin/deck
COPY deck ./deck
# The weekly run's host script and prompt: the host reads them with `docker exec`.
COPY bin/deck-curate ./bin/
COPY curate ./curate

ENV DECK_DATA=/data DECK_PORT=8795 PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8795
CMD ["python", "-m", "deck", "serve"]
