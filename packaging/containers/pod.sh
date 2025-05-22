#!/bin/bash
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

set -e

PORT=10000

# Create public network (standard podman bridge with internet access)
PUBLIC_NET="publicnet"
if ! podman network exists "$PUBLIC_NET"; then
  podman network create "$PUBLIC_NET"
fi

POD_NAME="xpra"
if ! podman pod exists "$POD_NAME"; then
  podman pod create \
    --name ${POD_NAME} \
    --memory 4g \
    --shm-size=1g \
    --uts=private
#    --network "${PUBLIC_NET}" \
#    -p 10000:10000/tcp \
#    -p 10000:10000/udp
#    --infra-image=xvfb --infra-name=xvfb
#    --infra-command=??
#    --share=ipc,net,uts
#    --share=ipc,net,uts,cgroup
fi

# Start xvfb (isolated from host network)
podman run -dt \
  --pod ${POD_NAME} \
  --name xvfb \
  --hostname xpra \
  --uts private \
  --ipc shareable \
  --cgroupns private \
  --network "$PUBLIC_NET" \
  -p ${PORT}:${PORT}/tcp \
  -p ${PORT}:${PORT}/udp \
  --read-only --read-only-tmpfs=true \
  xvfb

# Start xpra (isolated, but exposes port 10000 on host)
podman run -dt \
  --pod ${POD_NAME} \
  --name xpra \
  --uts container:xvfb \
  --ipc container:xvfb \
  --cgroupns container:xvfb \
  --network container:xvfb \
  --read-only --read-only-tmpfs=true \
  xpra

# Start play with two networks: internal + internet
podman run -dt \
  --pod ${POD_NAME} \
  --name apps \
  --uts container:xvfb \
  --ipc container:xvfb \
  --cgroupns container:xvfb \
  --network container:xvfb \
  apps

# Output status
echo "Containers running:"
podman ps --format "table {{.Names}}\t{{.Status}}\t{{.Networks}}\t{{.Ports}}"

echo
echo "Network info:"
for NET in "$INTERNAL_NET" "$PUBLIC_NET"; do
  echo "- $NET:"
  podman network inspect "$NET" | grep -E '"Name":|"Subnet":|"Gateway":'
  echo
done

xdg-open "http://localhost:${PORT}/"
