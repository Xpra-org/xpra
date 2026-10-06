#!/bin/bash
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

set -e

PORT="${PORT:-10000}"
# the address the port is published on, the default only allows local connections,
# use `HOST_ADDRESS=0.0.0.0` to allow connections from other hosts:
HOST_ADDRESS="${HOST_ADDRESS:-127.0.0.1}"
XDISPLAY=":10"
# the application has no network access unless `APP_NETWORK=1`,
# which gives it its own network, separate from the one used by xpra:
APP_NETWORK="${APP_NETWORK:-0}"
# the clipboard is disabled unless a direction is specified: `to-server`, `to-client` or `both`:
CLIPBOARD="${CLIPBOARD:-none}"

# ensure that the images we need exist,
# the 'xvfb' and 'xpra' images are the ones used by the 'split' pod:
SPLIT_DIR="$(dirname "$0")/../split"
if ! podman image inspect --format '{{.Config.Env}}' xvfb 2> /dev/null | grep -q "XAUTH="; then
  # the image must support `--env XAUTH=...` to enable access control
  (cd "$SPLIT_DIR" && bash ./xvfb.sh)
fi
if ! buildah inspect -t image xpra &> /dev/null; then
  (cd "$SPLIT_DIR" && bash ./xpra.sh)
fi
if ! buildah inspect -t image app &> /dev/null; then
  (cd "$(dirname "$0")" && bash ./app.sh)
fi

POD_NAME="xpra-secure"
podman pod rm --force --ignore "$POD_NAME"

PUBLIC_NET="publicnet"
if ! podman network exists "$PUBLIC_NET"; then
  podman network create "$PUBLIC_NET"
fi
APP_NET="xpra-secure-app"
if [ "${APP_NETWORK}" == "1" ]; then
  if ! podman network exists "$APP_NET"; then
    podman network create "$APP_NET"
  fi
  APP_NETWORK_ARG="--network=${APP_NET}"
else
  APP_NETWORK_ARG="--network=none"
fi

# the X11 socket directory is the only resource shared with the application,
# the volume is populated from the 'xvfb' image, which creates '/tmp/.X11-unix' with mode 1777:
X11_VOLUME="xpra-secure-x11"
podman volume rm --force "$X11_VOLUME"
podman volume create "$X11_VOLUME"

# the X11 cookie and the xpra password are generated for each session,
# and given to the containers as read-only secrets, instead of sharing a writable volume.
# the cookie uses the 'FamilyWild' address family ('ffff'), so that it does not depend on the hostname:
XAUTH_SECRET="xpra-secure-xauthority"
PASSWORD_SECRET="xpra-secure-password"
SECRETS_DIR=$(mktemp -d)
trap 'rm -f "$SECRETS_DIR/host" "$SECRETS_DIR/xauthority" "$SECRETS_DIR/password"; rmdir "$SECRETS_DIR"' EXIT
xauth -f "$SECRETS_DIR/host" add "${XDISPLAY}" MIT-MAGIC-COOKIE-1 "$(mcookie)" 2> /dev/null
xauth -f "$SECRETS_DIR/host" nlist | sed -e 's/^..../ffff/' | xauth -f "$SECRETS_DIR/xauthority" nmerge - 2> /dev/null
PASSWORD=$(head -c 24 /dev/urandom | base64 | tr -d '/+=')
echo -n "$PASSWORD" > "$SECRETS_DIR/password"
for secret in "$XAUTH_SECRET" "$PASSWORD_SECRET"; do
  podman secret rm "$secret" &> /dev/null || true
done
podman secret create "$XAUTH_SECRET" "$SECRETS_DIR/xauthority" > /dev/null
podman secret create "$PASSWORD_SECRET" "$SECRETS_DIR/password" > /dev/null
XAUTH_MOUNT="--secret=${XAUTH_SECRET},target=/run/secrets/xauthority,mode=0444"

# no namespaces are shared by the pod, so there is no infra container,
# the pod is only used to manage the containers together:
podman pod create \
  --name ${POD_NAME} \
  --share=none

# the options common to all the containers:
# no capabilities, no privilege escalation, read-only root filesystem and limits:
HARDEN=(
  --cap-drop=all
  --security-opt=no-new-privileges
  --read-only --read-only-tmpfs=true
  --pids-limit=256
)

# 'xvfb' and 'xpra' share the ipc namespace for XShm,
# so they must have the same SELinux MCS level, which no other container uses:
C1=$((RANDOM % 512))
C2=$((512 + RANDOM % 512))
XPRA_LABEL="--security-opt=label=level:s0:c${C1},c${C2}"

# Start the X server, with access control, without any network access or abstract socket.
# 'RECORD' lets any client capture all the input events, but it cannot be disabled:
# Xorg uses the same flag for 'XTEST', which xpra requires.
# (`su-exec` needs SETUID and SETGID to switch to the X server's user, the capabilities are lost once it has)
podman run -dt \
  --pod ${POD_NAME} \
  --replace \
  --name xpra-secure-xvfb \
  --hostname xvfb \
  --network=none \
  --ipc=shareable \
  "${HARDEN[@]}" \
  --cap-add=SETUID,SETGID \
  --memory=2g \
  "$XPRA_LABEL" \
  "$XAUTH_MOUNT" \
  --env XAUTH=/run/secrets/xauthority \
  --env "XARGS=-nolisten local" \
  --volume "${X11_VOLUME}:/tmp/.X11-unix:rw,z" \
  xvfb

# Start xpra, with `--minimal=yes` to disable all the features which are not strictly required:
# no audio, clipboard, file transfers, printing, notifications, dbus, start menu, starting commands, etc
# re-enable the ones which are only used between the xpra server and its clients:
# the HTML5 client, cursors, the mouse wheel and the video encoders.
# xpra runs as the target user, it does not need any capabilities,
# its sockets are in a private tmpfs, and it uses the read-only X11 cookie:
if [ "${CLIPBOARD}" == "none" ]; then
  CLIPBOARD_ARGS=("--clipboard=no")
else
  CLIPBOARD_ARGS=("--clipboard=yes" "--clipboard-direction=${CLIPBOARD}")
fi
AUTH="auth=file:filename=/run/secrets/xpra-password"
podman run -dt \
  --pod ${POD_NAME} \
  --replace \
  --name xpra-secure-xpra \
  --hostname xpra \
  --user 1000:1000 \
  --ipc=container:xpra-secure-xvfb \
  --network "$PUBLIC_NET" \
  -p ${HOST_ADDRESS}:${PORT}:${PORT}/tcp \
  -p ${HOST_ADDRESS}:${PORT}:${PORT}/udp \
  "${HARDEN[@]}" \
  --memory=2g \
  "$XPRA_LABEL" \
  "$XAUTH_MOUNT" \
  --secret "${PASSWORD_SECRET},target=/run/secrets/xpra-password,mode=0400,uid=1000" \
  --tmpfs /run/user/1000:rw,mode=0700,U \
  --env XDG_RUNTIME_DIR=/run/user/1000 \
  --env XAUTHORITY=/run/secrets/xauthority \
  --env XPRA_VFB_WAIT=30 \
  --env XPRA_POWER_EVENTS=0 \
  --volume "${X11_VOLUME}:/tmp/.X11-unix:rw,z" \
  --entrypoint '["/usr/bin/xpra"]' \
  xpra \
  seamless "${XDISPLAY}" --use-display=yes --no-daemon \
  --minimal=yes \
  "--bind-tcp=0.0.0.0:${PORT},${AUTH}" "--bind-quic=0.0.0.0:${PORT},${AUTH}" \
  --socket-dirs=/run/user/1000/xpra \
  --websocket-upgrade=yes --cursors=yes --mousewheel=on --video=yes --encodings=all \
  "${CLIPBOARD_ARGS[@]}" \
  --border=red,5 --seccomp=strict --landlock=strict \
  --exit-with-windows=yes

# Start the application:
# it only has access to the X11 socket, read-only so that it cannot replace it,
# it uses its own user namespace, so that its user is not the same as the one running xpra and the X server,
# it has its own ipc namespace, so the application cannot access the XShm segments of xpra and the X server,
# and its home directory is a tmpfs, so nothing it writes is kept:
podman run -dt \
  --pod ${POD_NAME} \
  --replace \
  --name xpra-secure-app \
  --hostname app \
  --init \
  "$APP_NETWORK_ARG" \
  --ipc=private \
  --uidmap 0:40000:2000 --gidmap 0:40000:2000 \
  "${HARDEN[@]}" \
  --memory=2g \
  "$XAUTH_MOUNT" \
  --tmpfs /home/app-user:rw,mode=0700,U \
  --volume "${X11_VOLUME}:/tmp/.X11-unix:ro,z" \
  app

echo "Containers running:"
podman ps --filter "pod=${POD_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Networks}}\t{{.Ports}}"
echo

echo "Waiting for port ${PORT}"
if curl --version >& /dev/null; then
  while ! curl --output /dev/null --silent --head --fail http://127.0.0.1:$PORT; do
    sleep 1 && echo -n .
  done
  echo
else
  sleep 10
fi

URL="http://127.0.0.1:${PORT}/?password=${PASSWORD}"
echo "Connect using: ${URL}"
echo " or: xpra attach tcp://:${PASSWORD}@127.0.0.1:${PORT}/"
xdg-open "${URL}"
