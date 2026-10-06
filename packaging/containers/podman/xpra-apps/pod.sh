#!/bin/bash
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

set -e

PORT=10000

# when building and configuring the containers,
# SEAMLESS switches between seamless mode (preferred) and desktop mode (slower):
export SEAMLESS=1

# ensure that the containers we need exist,
# the images are the same ones used by the 'split' pod, without the 'xvfb' container:
SPLIT_DIR="$(dirname "$0")/../split"
if ! buildah inspect -t image xpra &> /dev/null; then
  (cd "$SPLIT_DIR" && bash ./xpra.sh)
fi
if ! buildah inspect -t image apps &> /dev/null; then
  (cd "$SPLIT_DIR" && bash ./desktop.sh)
fi

# Create public network (standard podman bridge with internet access)
PUBLIC_NET="publicnet"
if ! podman network exists "$PUBLIC_NET"; then
  podman network create "$PUBLIC_NET"
fi

# remove any previous instance of the pod,
# so that we can start with empty volumes, without stale sockets or files from a previous session:
POD_NAME="xpra-apps"
podman pod rm --force --ignore "$POD_NAME"

RUN_VOLUME="xpra-apps-run"
# only the X11 socket directory is shared, each container keeps its own private '/tmp'.
# the volume is populated from the 'xpra' image, which creates '/tmp/.X11-unix' with mode 1777:
X11_VOLUME="xpra-apps-x11"
for volume in "$RUN_VOLUME" "$X11_VOLUME"; do
  podman volume rm --force "$volume"
  podman volume create "$volume"
done

podman pod create \
  --name ${POD_NAME} \
  --restart on-failure \
  --memory 4g \
  --shm-size=1g \
  --uts=private

# the xpra server loads the application menus and their icons from the 'apps' image,
# mounted read-only at the same locations, so that the menus show the applications installed there,
# the 'apps' image also provides the SVG icons cached as PNG:
MENU_MOUNTS=()
for dir in /etc/xdg/menus /usr/share/applications /usr/share/desktop-directories /usr/share/icons /usr/share/pixmaps /var/cache/xpra/menu-icons; do
  MENU_MOUNTS+=(--mount "type=image,source=apps,destination=${dir},subpath=${dir}")
done

# Start xpra, which also starts the X server,
# and exposes ipc to the other container for XShm.
# xpra uses the session bus started by the 'apps' container,
# nothing in the pod needs a system bus, so xpra must not start one (as root) in the xpra container:
# the applications are installed in the 'apps' container, so xpra starts them there using the 'xpra runner',
# the OpenGL probe also goes through the runner, so it tests OpenGL in the 'apps' container:
podman run -dt \
  --pod ${POD_NAME} \
  --replace \
  --name xpra-apps-xpra \
  --hostname xpra \
  --env USE_DISPLAY=no \
  --env DBUS=wait \
  --env XPRA_SYSTEM_DBUS=0 \
  --env "EXEC_WRAPPER=xpra run socket:///run/user/1000/runner/socket --" \
  --uts private \
  --ipc shareable \
  --cgroupns private \
  --network "$PUBLIC_NET" \
  -p ${PORT}:${PORT}/tcp \
  -p ${PORT}:${PORT}/udp \
  --volume ${RUN_VOLUME}:/run:rw \
  --volume ${X11_VOLUME}:/tmp/.X11-unix:rw \
  --security-opt label=type:container_runtime_t \
  --read-only --read-only-tmpfs=true \
  "${MENU_MOUNTS[@]}" \
  xpra

# Start app container running the desktop environment applications:
# `--init` reaps the orphaned processes, ie: services started by the session bus,
# the desktop environment command does not do it
podman run -dt \
  --pod ${POD_NAME} \
  --replace \
  --name xpra-apps-apps \
  --init \
  --uts container:xpra-apps-xpra \
  --ipc container:xpra-apps-xpra \
  --cgroupns container:xpra-apps-xpra \
  --network container:xpra-apps-xpra \
  --security-opt label=type:container_runtime_t \
  --volumes-from xpra-apps-xpra:rw \
  apps

# Output status
echo "Containers running:"
podman ps --filter "pod=${POD_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Networks}}\t{{.Ports}}"
echo

echo "Waiting for port ${PORT}"
if curl --version >& /dev/null; then
  while ! curl --output /dev/null --silent --head --fail http://127.0.0.1:$PORT; do
    sleep 1 && echo -n .
  done
else
  sleep 10
fi

timeout 10 bash -c 'until printf "" 2>>/dev/null >>/dev/tcp/$0/$1; do sleep 1; done' 127.0.0.1 $PORT
xdg-open "http://127.0.0.1:${PORT}/"
