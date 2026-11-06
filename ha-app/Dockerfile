# The Home Assistant app image. GitHub Actions builds it from the repo root:
#   docker build -f ha-app/Dockerfile .
# and pushes it to ghcr.io/urosgruber/hisense-washer-ha-amd64:<version>.
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:bookworm
FROM ${BUILD_FROM}

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates openssl python3 \
      python3-paho-mqtt python3-aiohttp python3-websocket \
 && rm -rf /var/lib/apt/lists/*

COPY washer /opt/hisense-washer/washer
COPY dist/hisense-washer-card.js /usr/share/hisense-washer/hisense-washer-card.js
COPY ha-app/register_card.py /register_card.py
COPY ha-app/notify.py /notify.py
COPY ha-app/run.sh /run.sh
RUN chmod a+x /run.sh

ARG BUILD_VERSION=dev
ENV CARD_VERSION=${BUILD_VERSION}
LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="addon" \
      io.hass.arch="amd64" \
      org.opencontainers.image.source="https://github.com/urosgruber/hisense-washer-ha"

CMD ["/run.sh"]
