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

buildah rm $CONTAINER
buildah rmi -f $IMAGE_NAME
buildah from --name $CONTAINER $DISTRO:$RELEASE
buildah run $CONTAINER dnf update -y
buildah run $CONTAINER dnf install -y wget --setopt=install_weak_deps=False
buildah run $CONTAINER wget -O "/etc/yum.repos.d/${REPO}.repo" "https://raw.githubusercontent.com/Xpra-org/xpra/master/packaging/repos/Fedora/${REPO}.repo"
buildah run $CONTAINER dnf install -y xpra-filesystem xpra-server xpra-x11 xpra-html5 python3-pyxdg --setopt=install_weak_deps=False
if [ "${AUDIO}" == "1" ]; then
  buildah run $CONTAINER dnf install -y xpra-audio-server
fi
if [ "${CODECS}" == "1" ]; then
  buildah run $CONTAINER dnf install -y xpra-codecs
fi

if [ "${TOOLS}" == "1" ]; then
  buildah run $CONTAINER dnf install -y xterm net-tools lsof xpra-client socat glxgears mesa-demos xdpyinfo --setopt=install_weak_deps=False
fi

# TODO: merge user setup to avoid running as root, once all the permission issues are resolved

# to only use the display from the 'xvfb' container
# set `--use-display=yes`:
buildah config --entrypoint "/usr/bin/xpra seamless ${XDISPLAY} --bind-tcp=0.0.0.0:${PORT} --no-dbus --no-daemon --use-display=auto" $CONTAINER
buildah commit $CONTAINER $IMAGE_NAME
