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
XDISPLAY="${XDISPLAY:-:10}"
TOOLS="${TOOLS:-0}"
APPS="${APPS:-libreoffice lxterminal vlc gimp}"
FIREFOX="${FIREFOX:-1}"
TARGET_USER="${TARGET_USER:-desktop-user}"
TARGET_PASSWORD="${TARGET_PASSWORD:-thepassword}"
TARGET_USER_GROUPS="${TARGET_USER_GROUPS:-audio,pulse,video}"
TARGET_UID="${TARGET_UID:-1000}"
TARGET_GID="${TARGET_GID:-1000}"
# LANG="${LANG:-C}"

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
buildah run $CONTAINER apt-get install pulseaudio pavucontrol --no-install-recommends -y
buildah run $CONTAINER apt-get install winbar --no-install-recommends -y
buildah run $CONTAINER winbar --create-cache
buildah run $CONTAINER apt-get install $APPS

# remove the default "ubuntu" user, and add our one:
buildah run $CONTAINER deluser --remove-home --remove-all-files --quiet "ubuntu"
buildah run $CONTAINER groupadd -r -g "${TARGET_GID}" "${TARGET_USER}"
buildah run $CONTAINER adduser -uid "${TARGET_UID}" -gid "${TARGET_GID}" --disabled-password --comment "no-comment" --shell /bin/bash "${TARGET_USER}"
buildah run $CONTAINER usermod -aG "${TARGET_USER_GROUPS}" "${TARGET_USER}"
buildah run $CONTAINER sh -c "echo \"${TARGET_USER}:${TARGET_PASSWORD}\" | chpasswd"
buildah run $CONTAINER setpriv --reuid "${TARGET_UID}" --regid "${TARGET_GID}" --init-groups --reset-env winbar --create-cache

if [ "${FIREFOX}" == "1" ]; then
  buildah copy $CONTAINER "mozilla-firefox" /etc/apt/preferences.d/
  buildah run $CONTAINER apt install software-properties-common --no-install-recommends
  buildah run $CONTAINER add-apt-repository -y ppa:mozillateam/ppa
  buildah run $CONTAINER apt install firefox --no-install-recommends
fi

# to install xpra in this container:
# buildah run $CONTAINER apt-get install xpra-server xserver-xorg-video-dummy xpra-codecs xpra-audio-server xpra-codecs-extras xpra-x11 xpra-html5 --no-install-recommends
if [ "${TOOLS}" == "1" ]; then
  # add some applications:
  buildah run $CONTAINER apt-get install xterm strace net-tools iputils-ping --no-install-recommends -y
  # toys useful for testing video encoders, costs ~30MB:
  buildah run $CONTAINER apt-get install mesa-utils --no-install-recommends -y
  buildah run $CONTAINER sh -c "wget https://github.com/VirtualGL/virtualgl/releases/download/3.1.3/virtualgl_3.1.3_amd64.deb;apt-get install ./virtualgl_3.1.3_amd64.deb -y"
  # xrandr, xdpyinfo etc, costs ~15MB:
  buildah run $CONTAINER apt-get install x11-xserver-utils x11-utils libegl1-mesa --no-install-recommends -y
fi

buildah config --entrypoint "setpriv --no-new-privs --reuid ${TARGET_UID} --regid ${TARGET_GID} --init-groups --reset-env /bin/bash -c \"DISPLAY=${XDISPLAY} winbar\"" $CONTAINER
buildah commit $CONTAINER $IMAGE_NAME
