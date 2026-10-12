#!/usr/bin/with-contenv bash
CONFIG_PATH=/data/options.json
PASSWORD=$(jq --raw-output ".password // empty" $CONFIG_PATH)

echo "Starting Mobile Code Studio..."

if [ -n "$PASSWORD" ]; then
    export PASSWORD="$PASSWORD"
    exec code-server --bind-addr 0.0.0.0:8443 --auth password /config
else
    exec code-server --bind-addr 0.0.0.0:8443 --auth none /config
fi
