#!/bin/bash
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017-2019 Antoine Martin <antoine@xpra.org>
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
$PACMAN --noconfirm -S ${XPKG}ffmpeg ${XPKG}libyuv-git ${XPKG}gst-plugins-good ${XPKG}gst-plugins-bad ${XPKG}gst-plugins-ugly
#network layer libraries:
$PACMAN --noconfirm -S ${XPKG}lz4 ${XPKG}lzo2 heimdal-libs openssh sshpass libsodium
#python3 GStreamer bindings:
$PACMAN --noconfirm -S ${XPKG}gst-python
#development tools and libs for building extra packages:
$PACMAN --noconfirm -S base-devel ${XPKG}yasm ${XPKG}nasm subversion rsync zip gtk-doc ${XPKG}cmake ${XPKG}gcc ${XPKG}pkg-config ${XPKG}libffi
#python libraries and packaging tools:
$PACMAN --noconfirm -S ${XPKG}python2-enum34
for x in cryptography cffi pycparser numpy pillow cx_Freeze appdirs paramiko comtypes netifaces rencode setproctitle pyu2f ldap ldap3 bcrypt pynacl lz4 lzo brotli PyOpenGL nvidia-ml zeroconf certifi yaml py-cpuinfo; do
	$PACMAN --noconfirm -S ${XPKG}python2-${x}
	$PACMAN --noconfirm -S ${XPKG}python3-${x}
done
#python2-cryptography 2.4.2 has an undeclared dependency on:
$PACMAN --noconfirm -S ${XPKG}python2-ipaddress
$PACMAN --noconfirm -S ${XPKG}cython2 ${XPKG}python2-setuptools
$PACMAN --noconfirm -S ${XPKG}cython

#cx_Freeze gets very confused about sqlite DLL location
#don't fight it and just symlink it where it will be found:
mkdir /mingw64/DLLs
pushd /mingw64/DLLs
ln -sf /mingw64/lib/sqlite3*/sqlite3*.dll sqlite3.dll
popd

#for webcam support:
#$PACMAN --noconfirm -S ${XPKG}opencv ${XPKG}hdf5 ${XPKG}tesseract-ocr

echo "for printing support, install libpdfium"
echo "by downloading the plain x64 pdfium binary from"
echo "https://github.com/bblanchon/pdfium-binaries"
echo "and place the `pdfium.dll` in '$MINGW_PREFIX/bin'"
