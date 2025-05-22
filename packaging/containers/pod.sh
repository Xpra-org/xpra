#!/bin/bash

set -e

PORT=10000

# Create internal-only network (no external access)
INTERNAL_NET="internalnet"
if ! podman network exists "$INTERNAL_NET"; then
  podman network create --internal "$INTERNAL_NET"
fi

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
  xvfb

# Start xpra (isolated, but exposes port 10000 on host)
podman run -dt \
  --pod ${POD_NAME} \
  --name xpra \
  --uts container:xvfb \
  --ipc container:xvfb \
  --cgroupns container:xvfb \
  --network container:xvfb \
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
