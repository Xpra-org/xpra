#!/bin/bash
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

set -e

# a minimal image for running a single untrusted application:
# no xpra packages, no runner, no menus, no audio, no shared session bus.
DISTRO="${DISTRO:-fedora}"
RELEASE="${RELEASE:-latest}"
IMAGE_NAME="${IMAGE_NAME:-app}"
CONTAINER="$DISTRO-$RELEASE-$IMAGE_NAME"
# the packages to install, and the command to run:
APP_PACKAGES="${APP_PACKAGES:-xterm dejavu-sans-mono-fonts}"
APP_COMMAND="${APP_COMMAND:-xterm -fa Monospace}"
# run the application with its own private session bus, which is not shared with any other container:
DBUS="${DBUS:-0}"
XDISPLAY="${XDISPLAY:-:10}"
TARGET_USER="${TARGET_USER:-app-user}"
TARGET_UID="${TARGET_UID:-1000}"
TARGET_GID="${TARGET_GID:-1000}"

run () {
  buildah run $CONTAINER "$@"
}

install () {
  run dnf install -y --setopt=install_weak_deps=False "$@"
}

buildah rm $CONTAINER || true
buildah rmi -f $IMAGE_NAME || true
buildah from --pull=newer --name $CONTAINER $DISTRO:$RELEASE
run dnf update -y
install $APP_PACKAGES
START_DBUS=""
if [ "${DBUS}" == "1" ]; then
  install dbus-daemon dbus-tools
  # the base image ships an empty placeholder file, which 'dbus-uuidgen --ensure' rejects:
  run sh -c "test -s /etc/machine-id || rm -f /etc/machine-id"
  run dbus-uuidgen --ensure=/etc/machine-id
  START_DBUS="dbus-run-session --"
fi
run sh -c "rm -fr /var/cache/*dnf* /var/log/dnf*.log*"

run groupadd -g "${TARGET_GID}" "${TARGET_USER}"
run useradd -M -u "${TARGET_UID}" -g "${TARGET_GID}" --shell /sbin/nologin "${TARGET_USER}"

# the container runs as the target user, without any capabilities,
# its home directory is a private tmpfs mounted when the container starts,
# the X11 cookie is a read-only secret, the display is the only resource shared with other containers.
# there is no accessibility bus, 'NO_AT_BRIDGE' stops GTK applications from looking for one:
buildah config --user "${TARGET_UID}:${TARGET_GID}" $CONTAINER
buildah config --workingdir "/home/${TARGET_USER}" $CONTAINER
buildah config --env "HOME=/home/${TARGET_USER}" --env "DISPLAY=${XDISPLAY}" --env "XAUTHORITY=/run/secrets/xauthority" --env NO_AT_BRIDGE=1 $CONTAINER
# the display is provided by another container which may still be starting,
# so wait up to 30 seconds for its socket:
WAIT_FOR_DISPLAY="for i in \$(seq 300); do test -S /tmp/.X11-unix/X${XDISPLAY#:} && break; sleep 0.1; done;"
buildah config --entrypoint "[ \"/bin/sh\", \"-c\", \"${WAIT_FOR_DISPLAY} exec ${START_DBUS} ${APP_COMMAND}\" ]" $CONTAINER
buildah commit $CONTAINER $IMAGE_NAME
