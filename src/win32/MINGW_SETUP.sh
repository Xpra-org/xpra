#!/bin/bash
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

if [ -z "$1" ]; then
	if [ "$MSYSTEM" == "MINGW64" ]; then
		export XPKG="mingw-w64-x86_64-"
	elif [ "$MSYSTEM" == "MINGW32" ]; then
		export XPKG="mingw-w64-i686-"
	else
		echo "failed to detect msys platform, MSYSTEM=$MSYSTEM"
		exit 1
	fi
elif [ "$1" == "x86_64" ]; then
	export XPKG="mingw-w64-x86_64-"
elif [ "$1" == "i386" ]; then
	export XPKG="mingw-w64-i686-"
else
	echo "invalid argument '$1'"
	echo "usage: $0 [x86_64|i386]"
	exit 1
fi

PACMAN="pacman"
#PACMAN="echo pacman"

#most packages get installed here: (python, gtk, etc):
$PACMAN --noconfirm -S ${XPKG}python2 ${XPKG}python2-pygtk ${XPKG}gtkglext ${XPKG}python2-gobject ${XPKG}libnotify
#media libraries (more than we actually need):
$PACMAN --noconfirm -S ${XPKG}ffmpeg ${XPKG}gst-plugins-good ${XPKG}gst-plugins-bad ${XPKG}gst-plugins-ugly
#network layer libraries:
$PACMAN --noconfirm -S ${XPKG}lz4 ${XPKG}lzo2 ${XPKG}xxhash ${XPKG}libsodium
#python3 GStreamer bindings:
$PACMAN --noconfirm -S ${XPKG}gst-python
#development tools and libs for building extra packages:
$PACMAN --noconfirm -S base-devel ${XPKG}yasm ${XPKG}nasm subversion rsync zip gtk-doc ${XPKG}cmake ${XPKG}gcc ${XPKG}pkg-config ${XPKG}libffi ${XPKG}gss ${XPKG}openldap
#python libraries and packaging tools:
for x in cryptography cffi pycparser numpy pillow cx_Freeze appdirs; do
	$PACMAN --noconfirm -S ${XPKG}python2-${x}
	$PACMAN --noconfirm -S ${XPKG}python3-${x}
done
$PACMAN --noconfirm -S ${XPKG}cython2 ${XPKG}python2-setuptools
$PACMAN --noconfirm -S ${XPKG}cython
#using easy-install for python libraries which are not packaged by mingw:
#build pynacl against the system library:
export SODIUM_INSTALL=system
easy_install-2.7 -U -Z enum34 enum-compat
for x in rencode xxhash zeroconf lz4 websocket-client netifaces comtypes PyOpenGL PyOpenGL_accelerate websockify nvidia-ml-py setproctitle pyu2f python-ldap ldap3 bcrypt pynacl paramiko; do
    easy_install-2.7 -U -Z $x
    easy_install-3.7 -U -Z $x
done

#for webcam support:
#$PACMAN --noconfirm -S ${XPKG}opencv ${XPKG}hdf5 ${XPKG}tesseract-ocr
