#!/usr/bin/with-contenv bash
CONFIG_PATH=/data/options.json

# Define a persistent folder for this addon inside addon_configs
ADDON_CONFIG_DIR="/addon_configs/mobile_file_manager"
mkdir -p "$ADDON_CONFIG_DIR"

SETTINGS_FILE="$ADDON_CONFIG_DIR/settings.json"
FB_DB="$ADDON_CONFIG_DIR/filebrowser.db"

# ---- Persistent settings -------------------------------------------------
DEFAULTS='{"samba_username":"samba_user","samba_password":"changeme","filebrowser_username":"admin","filebrowser_password":"ChangeMe12345!","root_access":false}'
SAVED='{}'
if [ -f "$SETTINGS_FILE" ] && jq -e . "$SETTINGS_FILE" >/dev/null 2>&1; then
    SAVED=$(cat "$SETTINGS_FILE")
fi
MERGED=$(jq -n --argjson d "$DEFAULTS" --argjson o "$(cat "$CONFIG_PATH")" --argjson s "$SAVED" '
  reduce ($d | keys[]) as $k ({};
    ($o[$k]) as $ov
    | .[$k] = (if ($ov != null and $ov != $d[$k]) then $ov
               elif ($s[$k] != null) then $s[$k]
               else $d[$k] end))')
echo "$MERGED" > "$SETTINGS_FILE" && chmod 600 "$SETTINGS_FILE"
echo "Settings saved to $SETTINGS_FILE"

SAMBA_USER=$(echo "$MERGED" | jq -r '.samba_username')
SAMBA_PASS=$(echo "$MERGED" | jq -r '.samba_password')
FB_USER=$(echo "$MERGED" | jq -r '.filebrowser_username')
FB_PASS=$(echo "$MERGED" | jq -r '.filebrowser_password')
ROOT_ACCESS=$(echo "$MERGED" | jq -r '.root_access')

# File Browser refuses passwords shorter than 12 characters
if [ "${#FB_PASS}" -lt 12 ]; then
    echo "ERROR: filebrowser_password must be at least 12 characters. Fix it in the Configuration tab."
    exit 1
fi

echo "Starting Samba File Sharing..."

# Folders Samba needs
mkdir -p /var/lib/samba/private /var/log/samba /run/samba /var/cache/samba

# Samba login user
getent group samba_group >/dev/null || addgroup -g 1000 samba_group
id "$SAMBA_USER" >/dev/null 2>&1 || adduser -D -H -G samba_group "$SAMBA_USER"
rm -f /var/lib/samba/private/passdb.tdb
printf '%s\n%s\n' "$SAMBA_PASS" "$SAMBA_PASS" | smbpasswd -a -s "$SAMBA_USER"
echo "Samba user: ${SAMBA_USER} (password length: ${#SAMBA_PASS})"

# Samba configuration mapping
cat > /etc/samba/smb.conf << SMB
[global]
    workgroup = WORKGROUP
    server string = Home Assistant Mobile Storage
    security = user
    map to guest = Bad User
    dns proxy = no
    wide links = yes
    unix extensions = no
    load printers = no
    printing = bsd
    printcap name = /dev/null
    disable spoolss = yes
    server min protocol = SMB2
    log level = 1 auth:3

[Config]
    path = /config
    browsable = yes
    writable = yes
    guest ok = no
    valid users = ${SAMBA_USER}
    force user = root
    force group = root

[Share]
    path = /share
    browsable = yes
    writable = yes
    guest ok = no
    valid users = ${SAMBA_USER}
    force user = root
    force group = root

[Media]
    path = /media
    browsable = yes
    writable = yes
    guest ok = no
    valid users = ${SAMBA_USER}
    force user = root
    force group = root
SMB

nmbd --foreground --no-process-group --debug-stdout &
smbd --foreground --no-process-group --debug-stdout &

# Self-test
(
    sleep 6
    if smbclient -L //127.0.0.1 -U "${SAMBA_USER}%${SAMBA_PASS}" >/dev/null 2>&1; then
        echo ">>> SAMBA SELF-TEST: login OK for user ${SAMBA_USER}"
    else
        echo ">>> SAMBA SELF-TEST: login FAILED for user ${SAMBA_USER}"
    fi
) &

echo "Starting File Browser UI..."

INGRESS_ENTRY=$(curl -fsS -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
    http://supervisor/addons/self/info | jq -r '.data.ingress_entry')
echo "Ingress path: ${INGRESS_ENTRY}"

# Initialize the persistent File Browser database only if it doesn't already exist
if [ ! -f "$FB_DB" ]; then
    filebrowser config init --database "$FB_DB" --auth.method=proxy --auth.header=X-Forwarded-User
    if [ "$ROOT_ACCESS" = "true" ]; then FB_ROOT="/"; else FB_ROOT="/config"; fi
    filebrowser config set --database "$FB_DB" --root "$FB_ROOT" --baseURL "${INGRESS_ENTRY}" >/dev/null
    filebrowser users add "$FB_USER" "$FB_PASS" --perm.admin=true --database "$FB_DB"
fi

# Run File Browser pointing to the persistent database file
filebrowser --database "$FB_DB" --address 127.0.0.1 --port 8081 &

# Nginx setup
cat > /etc/nginx/nginx.conf << NGINX
worker_processes 1;
pid /run/nginx.pid;
error_log /dev/stderr warn;
events { worker_connections 256; }
http {
    access_log off;
    client_max_body_size 0;
    server {
        listen 8080;
        allow 172.30.32.2;
        deny all;
        location / {
            rewrite ^(.*)\$ ${INGRESS_ENTRY}\$1 break;
            proxy_pass http://127.0.0.1:8081;
            proxy_http_version 1.1;
            proxy_set_header Host \$host;
            proxy_set_header X-Forwarded-User "${FB_USER}";
            proxy_set_header Upgrade \$http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_request_buffering off;
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
        }
    }
}
NGINX

exec nginx -g 'daemon off;'
