#!/usr/bin/with-contenv bash
CONFIG_PATH=/data/options.json
SAMBA_PASS=$(jq --raw-output '.samba_password // "homeassistant"' "$CONFIG_PATH")

echo "Starting Samba File Sharing..."

# Folders Samba needs (they don't exist in a fresh Alpine container)
mkdir -p /var/lib/samba/private /var/log/samba /run/samba /var/cache/samba

# Samba login user (safe to re-run on restart)
getent group samba_group >/dev/null || addgroup -g 1000 samba_group
id samba_user >/dev/null 2>&1 || adduser -D -H -G samba_group -u 1000 samba_user
printf '%s\n%s\n' "$SAMBA_PASS" "$SAMBA_PASS" | smbpasswd -a -s samba_user

# force user = root so you can actually WRITE to /config, /share, /media
cat > /etc/samba/smb.conf << 'SMB'
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

[Config]
    path = /config
    browsable = yes
    writable = yes
    guest ok = no
    valid users = samba_user
    force user = root
    force group = root

[Share]
    path = /share
    browsable = yes
    writable = yes
    guest ok = no
    valid users = samba_user
    force user = root
    force group = root

[Media]
    path = /media
    browsable = yes
    writable = yes
    guest ok = no
    valid users = samba_user
    force user = root
    force group = root
SMB

# Run Samba in the foreground-but-backgrounded so errors show in the add-on log
nmbd --foreground --no-process-group --debug-stdout &
smbd --foreground --no-process-group --debug-stdout &

echo "Starting File Browser UI..."

# Ingress lives at a long random path. Ask Supervisor what it is.
INGRESS_ENTRY=$(curl -fsS -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
    http://supervisor/addons/self/info | jq -r '.data.ingress_entry')
echo "Ingress path: ${INGRESS_ENTRY}"

# File Browser: no login screen (HA already logged you in through ingress)
if [ ! -f /data/filebrowser.db ]; then
    filebrowser config init --database /data/filebrowser.db --auth.method=noauth
    filebrowser users add admin 'AdminPassword123!' --perm.admin=true --database /data/filebrowser.db
fi
# Keep these in sync every start (ingress path / root can change)
filebrowser config set --database /data/filebrowser.db --root /config --baseurl "${INGRESS_ENTRY}" >/dev/null

filebrowser --database /data/filebrowser.db --address 127.0.0.1 --port 8081 &

# nginx: takes ingress traffic on 8080, adds the ingress prefix, hands to File Browser
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
