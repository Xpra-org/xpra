#!/bin/bash
# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
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
$PACMAN --noconfirm -S ${XPKG}python2 ${XPKG}python2-pygtk ${XPKG}gtkglext ${XPKG}python2-gobject
#media libraries (more than we actually need):
$PACMAN --noconfirm -S ${XPKG}ffmpeg ${XPKG}gst-plugins-good ${XPKG}gst-plugins-bad ${XPKG}gst-plugins-ugly
#network layer libraries:
$PACMAN --noconfirm -S ${XPKG}lz4 ${XPKG}lzo2 ${XPKG}xxhash
#python3 GStreamer bindings:
$PACMAN --noconfirm -S ${XPKG}gst-python
#development tools and libs for building extra packages:
$PACMAN --noconfirm -S base-devel ${XPKG}yasm ${XPKG}nasm subversion rsync gtk-doc ${XPKG}cmake ${XPKG}gcc ${XPKG}pkg-config ${XPKG}libffi
#python libraries and install and packaging tools:
$PACMAN --noconfirm -S ${XPKG}python2-numpy ${XPKG}python2-pillow ${XPKG}cython2 ${XPKG}python2-setuptools ${XPKG}python2-cx_Freeze
#python3 versions (not all are really needed if just using python3 for sound):
$PACMAN --noconfirm -S ${XPKG}python3-numpy ${XPKG}python3-pillow ${XPKG}cython ${XPKG}python3-cx_Freeze
#using easy-install for python libraries which are not packaged by mingw:
# Note: a specific version of netifaces is installed as a dependency of 'zeroconf' because of this bug:
# https://bitbucket.org/al45tair/netifaces/issues/39
easy_install-2.7 -U -Z enum34 enum-compat
for x in rencode xxhash zeroconf lz4 websocket-client comtypes PyOpenGL PyOpenGL_accelerate websockify cffi pycparser cryptography nvidia-ml-py; do
    easy_install-2.7 -U -Z $x
    easy_install-3.5 -U -Z $x
done
#for webcam support:
$PACMAN -S ${XPKG}opencv ${XPKG}hdf5 ${XPKG}tesseract-ocr
