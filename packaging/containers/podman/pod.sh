#!/bin/bash
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

set -e

PORT=10000

# when building and configuring the containers,
# SEAMLESS switches between seamless mode (preferred) and desktop mode (slower):
export SEAMLESS=1

# ensure that the containers we need exist:
if ! buildah inspect -t image xvfb &> /dev/null; then
  sh ./xvfb.sh
fi
if ! buildah inspect -t image xpra &> /dev/null; then
  sh ./xpra.sh
fi
if ! buildah inspect -t image apps &> /dev/null; then
  sh ./desktop.sh
fi

# Create public network (standard podman bridge with internet access)
PUBLIC_NET="publicnet"
if ! podman network exists "$PUBLIC_NET"; then
  podman network create "$PUBLIC_NET"
fi

RUN_VOLUME="run"
if ! podman volume exists "$RUN_VOLUME"; then
  # rootless containers can't use ro,nodev,noexec
  # or "--opt device=tmpfs"
  podman volume create "$RUN_VOLUME"
fi
TMP_VOLUME="tmp"
if ! podman volume exists "$TMP_VOLUME"; then
  # rootless containers can't use ro,nodev,noexec
  # or "--opt device=tmpfs"
  podman volume create --opt device=tmpfs --opt type=tmpfs --opt o=size=128M,nodev,noexec "$TMP_VOLUME"
  mkdir .X11-unix
  chmod 1777 .X11-unix
  tar -cv .X11-unix | podman volume import tmp -
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

# Start xvfb, exposes ipc to other containers for XShm
podman run -dt \
  --pod ${POD_NAME} \
  --replace \
  --name xvfb \
  --hostname xpra \
  --uts private \
  --ipc shareable \
  --cgroupns private \
  --network "$PUBLIC_NET" \
  -p ${PORT}:${PORT}/tcp \
  -p ${PORT}:${PORT}/udp \
  --read-only \
  --volume ${TMP_VOLUME}:/tmp:rw \
  --security-opt label=type:container_runtime_t \
  xvfb

# Start xpra
podman run -dt \
  --pod ${POD_NAME} \
  --replace \
  --name xpra \
  --uts container:xvfb \
  --ipc container:xvfb \
  --cgroupns container:xvfb \
  --network container:xvfb \
  --volume ${RUN_VOLUME}:/run:rw \
  --security-opt label=type:container_runtime_t \
  --volumes-from xvfb:rw \
  --read-only --read-only-tmpfs=true \
  xpra

# Start app container running the desktop environment applications:
podman run -dt \
  --pod ${POD_NAME} \
  --replace \
  --name apps \
  --uts container:xvfb \
  --ipc container:xvfb \
  --cgroupns container:xvfb \
  --network container:xvfb \
  --security-opt label=type:container_runtime_t \
  --volumes-from xvfb:rw \
  --volumes-from xpra:rw \
  apps
# this can be used to expose the host GPU / displays:
#  -v /tmp/.X11-unix:/tmp/.X11-unix \
#  -v /dev/dri:/dev/dri \

# Output status
echo "Containers running:"
podman ps --format "table {{.Names}}\t{{.Status}}\t{{.Networks}}\t{{.Ports}}"

echo
echo "Network info:"
echo "- $PUBLIC_NET:"
podman network inspect "$PUBLIC_NET" | grep -iE '"Name":|"Subnet":|"Gateway":'
echo

echo "Waiting for port ${PORT}"
curl --version >& /dev/null
if [ $? -eq 0 ]; then
  while ! curl --output /dev/null --silent --head --fail http://127.0.0.1:$PORT; do
    sleep 1 && echo -n .
  done
else
  sleep 10
fi

timeout 10 bash -c 'until printf "" 2>>/dev/null >>/dev/tcp/$0/$1; do sleep 1; done' 127.0.0.1 $PORT
xdg-open "http://127.0.0.1:${PORT}/"
