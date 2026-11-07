#!/usr/bin/with-contenv bashio
# Start the washer server. The Supervisor provides the MQTT login, so no
# MQTT user is needed.
set -e

export WASHER_DATA_DIR=/data
export WASHER_DEVICE_BIND=0.0.0.0:4444
export WASHER_WEB_BIND=0.0.0.0:8080
# Only the ingress gateway may open the admin page: Home Assistant admins only.
export WASHER_WEB_ALLOWED=172.30.32.2
if bashio::config.has_value 'washer_ip'; then
  export WASHER_WASHER_IP="$(bashio::config 'washer_ip')"
else
  bashio::log.warning "washer_ip is empty: every LAN device may connect to port 4444. Set it to the washer's IP address."
fi
export WASHER_CLOUD_MAX_HOURS="$(bashio::config 'cloud_max_hours' '2')"
export WASHER_CLOUD_RESOLVER="$(bashio::config 'cloud_resolver' '1.1.1.1')"
if bashio::config.has_value 'cloud_address'; then
  export WASHER_CLOUD_ADDRESS="$(bashio::config 'cloud_address')"
fi

# At boot, the MQTT broker app can start after this one. Wait up to 5
# minutes for it.
if bashio::config.true 'mqtt'; then
  for _ in $(seq 1 30); do
    bashio::services.available mqtt && break
    bashio::log.info "Waiting for the MQTT broker..."
    sleep 10
  done
fi

if bashio::config.true 'mqtt' && bashio::services.available mqtt; then
  export WASHER_MQTT_URL="mqtt://$(bashio::services mqtt host):$(bashio::services mqtt port)"
  export WASHER_MQTT_USERNAME="$(bashio::services mqtt username)"
  export WASHER_MQTT_PASSWORD="$(bashio::services mqtt password)"
  bashio::log.info "MQTT on: ${WASHER_MQTT_URL}"
elif bashio::config.true 'mqtt'; then
  bashio::log.warning "MQTT is on, but no MQTT broker is available: no Home Assistant entities. Restart the app when the broker runs."
else
  bashio::log.info "MQTT off"
fi

# Install the dashboard card and register it as a resource. A failure here
# must not stop the server.
python3 /register_card.py || bashio::log.warning "Could not install the dashboard card"

# Send "wash done" to the phones in notify_targets. It runs beside the
# server; if it ends, it starts again after 15 s.
if bashio::config.true 'notify'; then
  ( while true; do python3 /notify.py; sleep 15; done ) &
fi

cd /opt/hisense-washer
exec python3 -m washer
