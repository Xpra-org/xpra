#!/bin/bash
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

DISTRO="alpine"
IMAGE_NAME="xvfb"
DISPLAY="${DISPLAY:-:10}"
CONTAINER="$DISTRO-$IMAGE_NAME"
# Xdummy needs xauth, which is a pain
XDUMMY="${XDUMMY:-0}"
OPENGL="${OPENGL:-1}"
TRIM="${TRIM:-1}"
TOOLS="${TOOLS:-0}"

buildah rm $CONTAINER
buildah rmi -f $IMAGE_NAME
buildah from --name $CONTAINER $DISTRO
buildah run $CONTAINER apk update

if [ "${XDUMMY}" == "1" ]; then
  buildah run $CONTAINER apk add xf86-video-dummy xorg-server
else
  buildah run $CONTAINER apk add xvfb
fi

if [ "${OPENGL}" == "1" ]; then
  buildah run $CONTAINER apk add mesa-gl mesa-dri-gallium
fi

if [ "${TOOLS}" == "1" ]; then
  # for debugging:
  buildah run $CONTAINER apk add socat util-linux-misc ghostscript-fonts
  buildah run $CONTAINER apk add xterm mesa-utils mesa-osmesa
  # vgl is currently only available in the 'testing' repo:
  buildah run $CONTAINER apk add virtualgl --repository=http://dl-cdn.alpinelinux.org/alpine/edge/testing/
fi

if [ "${TRIM}" == "1" ]; then
  # trim down unused directories:
  buildah run $CONTAINER rm -fr /media /mnt /opt /srv /usr/local /usr/share/apk /usr/share/aclocal /usr/share/man /usr/share/util-macros
  buildah run $CONTAINER rm -fr /etc/apk /etc/crontabs /etc/logrotate.d /etc/network /etc/nsswitch.conf /etc/periodic /etc/profile* /etc/ssl* /etc/udhcpc /etc/opt
  # extra OpenGL drivers:
  # buildah run $CONTAINER rm -fr /usr/share/util-macros /usr/lib/gallium-pipe/pipe_crocus.so /usr/lib/gallium-pipe/pipe_i915.so /usr/lib/gallium-pipe/pipe_iris.so /usr/lib/gallium-pipe/pipe_nouveau.so /usr/lib/gallium-pipe/pipe_r300.so /usr/lib/gallium-pipe/pipe_r600.so /usr/lib/gallium-pipe/pipe_radeonsi.so /usr/lib/gallium-pipe/pipe_vmwgfx.so
  # remove the ability to install more packages:
  buildah run $CONTAINER rm -fr /lib/apk /var/*
  # ideally:
  # buildah run $CONTAINER apk remove busybox
fi

if [ "${XDUMMY}" == "1" ]; then
  rm -f xorg.conf
  wget https://raw.githubusercontent.com/Xpra-org/xpra/refs/heads/master/fs/etc/xpra/xorg.conf
  buildah run $CONTAINER mkdir /etc/X11
  buildah copy $CONTAINER xorg.conf /etc/X11
  buildah config --entrypoint "/usr/bin/Xorg -novtswitch -logfile /tmp/Xorg.log -config /etc/X11/xorg.conf +extension Composite +extension GLX +extension RANDR +extension RENDER -extension DOUBLE-BUFFER -nolisten tcp -noreset -ac $DISPLAY" $CONTAINER
else
  buildah config --entrypoint "/usr/bin/Xvfb -ac -noreset +extension GLX +extension Composite +extension RANDR +extension Render -extension DOUBLE-BUFFER -nolisten tcp -ac $DISPLAY" $CONTAINER
fi
buildah commit $CONTAINER $IMAGE_NAME
