#!/bin/bash
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017-2018 Antoine Martin <antoine@xpra.org>
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
$PACMAN --noconfirm -S ${XPKG}lz4 ${XPKG}lzo2 ${XPKG}xxhash ${XPKG}libsodium openssh sshpass
#python3 GStreamer bindings:
$PACMAN --noconfirm -S ${XPKG}gst-python
#development tools and libs for building extra packages:
$PACMAN --noconfirm -S base-devel ${XPKG}yasm ${XPKG}nasm subversion rsync zip gtk-doc ${XPKG}cmake ${XPKG}gcc ${XPKG}pkg-config ${XPKG}libffi ${XPKG}gss ${XPKG}openldap
#python libraries and packaging tools:
for x in cryptography cffi pycparser numpy pillow cx_Freeze appdirs paramiko comtypes netifaces rencode; do
	$PACMAN --noconfirm -S ${XPKG}python2-${x}
	$PACMAN --noconfirm -S ${XPKG}python3-${x}
done
$PACMAN --noconfirm -S ${XPKG}cython2 ${XPKG}python2-setuptools
$PACMAN --noconfirm -S ${XPKG}cython
#using easy-install for python libraries which are not packaged by mingw:
#build pynacl against the system library:
export SODIUM_INSTALL=system
easy_install-2.7 -U -Z enum34 enum-compat
for x in lz4 websocket-client websockify nvidia-ml-py setproctitle pyu2f python-ldap ldap3 bcrypt pynacl; do
    easy_install-2.7 -U -Z $x
    easy_install-3.7 -U -Z $x
done
#last version to support python2:
easy_install-2.7 -U -Z zeroconf==0.19.1
easy_install-3.7 -U -Z zeroconf

#pyopengl problems:
#use 3.1.1a1 as there are bugs in later versions on win32:
easy_install-2.7 -U -Z PyOpenGL==3.1.1a1
easy_install-2.7 -U -Z PyOpenGL_accelerate==3.1.1a1
#get the latest:
easy_install-3.7 -U -Z PyOpenGL
#doesn't build with python 3.7:
#easy_install-3.7 -U -Z PyOpenGL_accelerate==3.1.1a1

#cx_Freeze gets very confused about sqlite DLL location
#don't fight it and just symlink it where it will be found:
mkdir /mingw64/DLLs
pushd /mingw64/DLLs
ln -sf /mingw64/lib/sqlite3*/sqlite3*.dll sqlite3.dll
popd

#for webcam support:
#$PACMAN --noconfirm -S ${XPKG}opencv ${XPKG}hdf5 ${XPKG}tesseract-ocr
