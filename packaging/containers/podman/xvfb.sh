#!/bin/bash
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

set -e

DISTRO="alpine"
IMAGE_NAME="xvfb"
XDISPLAY="${XDISPLAY:-:10}"
CONTAINER="$DISTRO-$IMAGE_NAME"
XDUMMY="${XDUMMY:-1}"
OPENGL="${OPENGL:-1}"
TRIM="${TRIM:-1}"
TOOLS="${TOOLS:-0}"
TARGET_USER="${TARGET_USER:-xvfb-user}"
TARGET_UID="${TARGET_UID:-1000}"

run () {
  buildah run $CONTAINER "$@"
}

copy () {
  buildah copy $CONTAINER "$@"
}

add () {
  run apk add "$@"
}

buildah rm $CONTAINER || true
buildah rmi -f $IMAGE_NAME || true
buildah from --name $CONTAINER $DISTRO
run apk update
run apk add su-exec

run adduser -D -H -u "${TARGET_UID}" "${TARGET_USER}"
# the X11 socket directory, usually shared with other containers using a volume:
run mkdir -m 1777 /tmp/.X11-unix


if [ "${XDUMMY}" == "1" ]; then
  add xf86-video-dummy xorg-server
else
  add xvfb
fi

if [ "${OPENGL}" == "1" ]; then
  add mesa-gl mesa-dri-gallium
fi

if [ "${TOOLS}" == "1" ]; then
  # for debugging:
  add socat util-linux-misc ghostscript-fonts
  add xterm mesa-utils mesa-osmesa
  # vgl is currently only available in the 'testing' repo:
  add virtualgl --repository=http://dl-cdn.alpinelinux.org/alpine/edge/testing/
fi

if [ "${TRIM}" == "1" ]; then
  # trim down unused directories:
  run rm -fr /media /mnt /opt /srv /usr/local /usr/share/apk /usr/share/aclocal /usr/share/man /usr/share/util-macros
  # (use a shell inside the container to expand the globs, not the host's)
  run sh -c "rm -fr /etc/apk /etc/crontabs /etc/logrotate.d /etc/network /etc/nsswitch.conf /etc/periodic /etc/profile* /etc/ssl* /etc/udhcpc /etc/opt"
  # extra OpenGL drivers:
  # run rm -fr /usr/share/util-macros /usr/lib/gallium-pipe/pipe_crocus.so /usr/lib/gallium-pipe/pipe_i915.so /usr/lib/gallium-pipe/pipe_iris.so /usr/lib/gallium-pipe/pipe_nouveau.so /usr/lib/gallium-pipe/pipe_r300.so /usr/lib/gallium-pipe/pipe_r600.so /usr/lib/gallium-pipe/pipe_radeonsi.so /usr/lib/gallium-pipe/pipe_vmwgfx.so
  # remove the ability to install more packages:
  run sh -c "rm -fr /lib/apk /var/*"
  # ideally:
  # run apk remove busybox
fi

if [ "${XDUMMY}" == "1" ]; then
  run mkdir "/etc/X11"
  copy "../../../fs/etc/xpra/xorg.conf" "/etc/X11"
  # the setuid wrapper only allows console users to start the X server, we don't need it:
  run rm -f /usr/libexec/Xorg.wrap
  XVFB_COMMAND="/usr/libexec/Xorg -novtswitch -logfile /tmp/Xorg.log -config /etc/X11/xorg.conf +extension Composite +extension GLX +extension RANDR +extension RENDER -extension DOUBLE-BUFFER -nolisten tcp -noreset -ac $XDISPLAY"
else
  XVFB_COMMAND="/usr/bin/Xvfb -ac -noreset +extension GLX +extension Composite +extension RANDR +extension Render -extension DOUBLE-BUFFER -nolisten tcp -ac $XDISPLAY"
fi
ENTRYPOINT="su-exec ${TARGET_USER} ${XVFB_COMMAND}"
buildah config --entrypoint "${ENTRYPOINT}" $CONTAINER
buildah commit $CONTAINER $IMAGE_NAME
