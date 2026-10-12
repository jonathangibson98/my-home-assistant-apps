#!/usr/bin/with-contenv bash
CONFIG_PATH=/data/options.json
SAMBA_PASS=$(jq --raw-output ".samba_password // \"homeassistant\"" $CONFIG_PATH)

echo "Starting Samba File Sharing..."

# Create a secure samba user (mapping to root)
addgroup -g 1000 samba_group
adduser -D -H -G samba_group -u 1000 samba_user
echo -e "$SAMBA_PASS\n$SAMBA_PASS" | smbpasswd -a -s samba_user

# Write simple Samba configuration
cat << EOF > /etc/samba/smb.conf
[global]
    workgroup = WORKGROUP
    server string = Home Assistant Mobile Storage
    security = user
    map to guest = Bad User
    dns proxy = no
    wide links = yes
    unix extensions = no

[Config]
    path = /config
    browsable = yes
    writable = yes
    guest ok = no
    valid users = samba_user

[Share]
    path = /share
    browsable = yes
    writable = yes
    guest ok = no
    valid users = samba_user
EOF

# Start Samba daemons
nmbd -D
smbd -D

echo "Starting File Browser UI..."
# Initialize filebrowser database and create admin with a 12+ character password if it doesn't exist
if [ ! -f /data/filebrowser.db ]; then
    filebrowser config init --database /data/filebrowser.db
    filebrowser config set --database /data/filebrowser.db --root /config
    filebrowser users add admin AdminPassword123! --database /data/filebrowser.db --perm.admin=true
fi

# Run File Browser bound to all interfaces on port 8080
exec filebrowser --database /data/filebrowser.db --address 0.0.0.0 --port 8080 --root /config
