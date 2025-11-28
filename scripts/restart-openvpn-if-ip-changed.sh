#!/bin/bash
STATE_FILE="/var/run/wan_ip"
CURRENT_IP=$(curl -s https://api.ipify.org)

if [ -f "$STATE_FILE" ]; then
    OLD_IP=$(cat "$STATE_FILE")
else
    OLD_IP=""
fi

if [ "$CURRENT_IP" != "$OLD_IP" ]; then
    echo "$CURRENT_IP" > "$STATE_FILE"
    systemctl restart openvpn@client
fi