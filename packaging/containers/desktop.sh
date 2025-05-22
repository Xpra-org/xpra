#!/bin/bash
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

DISTRO="${DISTRO:-ubuntu}"
RELEASE="${RELEASE:-plucky}"
IMAGE_NAME="apps"
CONTAINER="$DISTRO-$RELEASE-$IMAGE_NAME"
REPO="${REPO:-xpra-beta}"
DISPLAY="${DISPLAY:-:10}"
TOOLS="${TOOLS:-0}"

buildah rm $CONTAINER
buildah rmi -f $IMAGE_NAME
buildah from --name $CONTAINER $DISTRO:$RELEASE
buildah run $CONTAINER apt-get update

# add xpra repo:
buildah run $CONTAINER apt-get install wget ca-certificates --no-install-recommends -y
buildah run $CONTAINER wget -O "/usr/share/keyrings/xpra.asc" "https://xpra.org/xpra.asc"
buildah run $CONTAINER wget -O "/etc/apt/sources.list.d/${REPO}.sources" "https://raw.githubusercontent.com/Xpra-org/xpra/master/packaging/repos/${RELEASE}/${REPO}.sources"
buildah run $CONTAINER apt-get update
# install winbar as desktop environment:
buildah run $CONTAINER apt-get install winbar --no-install-recommends -y
# to install xpra in this container:
# buildah run $CONTAINER apt-get install xpra-server xserver-xorg-video-dummy xpra-codecs xpra-audio-server xpra-codecs-extras xpra-x11 xpra-html5 --no-install-recommends

if [ "${TOOLS}" == "1" ]; then
  # add some applications:
  buildah run $CONTAINER apt-get install xterm --no-install-recommends -y
  # toys useful for testing video encoders, costs ~30MB:
  buildah run $CONTAINER apt-get install mesa-utils --no-install-recommends -y
  buildah run $CONTAINER sh -c "wget https://github.com/VirtualGL/virtualgl/releases/download/3.1.3/virtualgl_3.1.3_amd64.deb;apt-get install ./virtualgl_3.1.3_amd64.deb -y"
  # xrandr, xdpyinfo etc, costs ~15MB:
  buildah run $CONTAINER apt-get install x11-xserver-utils x11-utils --no-install-recommends -y
fi

buildah config --entrypoint "DISPLAY=${DISPLAY} winbar" $CONTAINER
buildah commit $CONTAINER $IMAGE_NAME
