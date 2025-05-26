#!/bin/bash
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

DISTRO="${DISTRO:-fedora}"
RELEASE="${RELEASE:-42}"
IMAGE_NAME="xpra"
CONTAINER="$DISTRO-$RELEASE-$IMAGE_NAME"
REPO="${REPO:-xpra-beta}"
XDISPLAY="${XDISPLAY:-:10}"
PORT="${PORT:-10000}"
AUDIO="${AUDIO:-1}"
CODECS="${CODECS:-1}"
TOOLS="${TOOLS:-0}"
TARGET_USER="${TARGET_USER:-xpra-user}"
TARGET_PASSWORD="${TARGET_PASSWORD:-thepassword}"
TARGET_USER_GROUPS="${TARGET_USER_GROUPS:-audio,pulse,video}"
TARGET_UID="${TARGET_UID:-1000}"
TARGET_GID="${TARGET_GID:-1000}"
DEBUG="${DEBUG:-none}"

buildah rm $CONTAINER
buildah rmi -f $IMAGE_NAME
buildah from --name $CONTAINER $DISTRO:$RELEASE
buildah run $CONTAINER dnf install -y https://download1.rpmfusion.org/free/${DISTRO}/rpmfusion-free-release-${RELEASE}.noarch.rpm
buildah run $CONTAINER dnf update -y
buildah run $CONTAINER dnf install -y wget --setopt=install_weak_deps=False
buildah run $CONTAINER wget -O "/etc/yum.repos.d/${REPO}.repo" "https://raw.githubusercontent.com/Xpra-org/xpra/master/packaging/repos/Fedora/${REPO}.repo"
buildah run $CONTAINER dnf install -y xpra-filesystem xpra-server xpra-x11 xpra-html5 python3-aioquic python3-pyxdg dbus-daemon dbus-x11 dbus-tools desktop-backgrounds-compat libjxl-utils python3-cups cups-filters cups-pdf --setopt=install_weak_deps=False
# EL10: system-backgrounds system-logos
if [ "${AUDIO}" == "1" ]; then
  buildah run $CONTAINER dnf install -y xpra-audio-server
fi
if [ "${CODECS}" == "1" ]; then
  buildah run $CONTAINER dnf install -y xpra-codecs
fi

if [ "${TOOLS}" == "1" ]; then
  buildah run $CONTAINER dnf install -y strace xterm net-tools lsof xpra-client socat glxgears mesa-demos xdpyinfo VirtualGL pavucontrol --setopt=install_weak_deps=False
fi

buildah run $CONTAINER groupadd -r -g "${TARGET_GID}" "${TARGET_USER}"
buildah run $CONTAINER adduser -u "${TARGET_UID}" -g "${TARGET_GID}" --shell /bin/bash "${TARGET_USER}"
buildah run $CONTAINER usermod -aG "${TARGET_USER_GROUPS}" "${TARGET_USER}"
buildah run $CONTAINER sh -c "echo \"${TARGET_USER}:${TARGET_PASSWORD}\" | chpasswd"

buildah run $CONTAINER sh -c "mkdir -m 755 -p /var/lib/dbus;dbus-uuidgen > /var/lib/dbus/machine-id"
buildah copy $CONTAINER allow-all.conf /etc/dbus-1/system.d/

# to only use the display from the 'xvfb' container
# set `--use-display=yes`:
buildah config --entrypoint "/usr/bin/xpra seamless --uid ${TARGET_UID} --gid ${TARGET_GID} ${XDISPLAY} --bind-quic=0.0.0.0:${PORT} --bind-tcp=0.0.0.0:${PORT} --no-daemon --use-display=auto --system-tray=no --ssh-upgrade=no --env=XPRA_POWER_EVENTS=0 -d ${DEBUG}" $CONTAINER
buildah commit $CONTAINER $IMAGE_NAME
