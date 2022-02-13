#!/bin/bash
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

set -e

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
$PACMAN --noconfirm --needed -S ${XPKG}python ${XPKG}libnotify
#media libraries (more than we actually need):
$PACMAN --noconfirm --needed -S ${XPKG}ffmpeg ${XPKG}libyuv-git ${XPKG}gst-plugins-good ${XPKG}gst-plugins-bad ${XPKG}gst-plugins-ugly
#network layer libraries:
$PACMAN --noconfirm --needed -S ${XPKG}lz4 heimdal-libs openssh sshpass ${XPKG}libsodium ${XPKG}qrencode ${XPKG}pinentry
#python GStreamer bindings:
$PACMAN --noconfirm --needed -S ${XPKG}gst-python
#development tools and libs for building extra packages:
$PACMAN --noconfirm --needed -S base-devel ${XPKG}yasm ${XPKG}nasm subversion rsync zip gtk-doc ${XPKG}cmake ${XPKG}gcc ${XPKG}pkgconf ${XPKG}libffi ${XPKG}python-pandocfilters
for x in cryptography cffi pycparser numpy pillow cx_Freeze appdirs paramiko comtypes netifaces rencode setproctitle pyu2f ldap ldap3 bcrypt pynacl lz4 brotli pyopengl nvidia-ml zeroconf certifi yaml py-cpuinfo winkerberos gssapi coverage psutil libavif; do
	$PACMAN --noconfirm --needed -S ${XPKG}python-${x}
done
$PACMAN --noconfirm --needed -S ${XPKG}cython

#this needs to be converted to a PKGBUILD:
$PACMAN --noconfirm --needed -S ${XPKG}python-pip ${XPKG}gcc
for x in browser-cookie3 qrencode; do
	pip3 install $x
done
#for webcam support:
#$PACMAN --noconfirm --needed -S ${XPKG}opencv ${XPKG}hdf5 ${XPKG}tesseract-ocr

echo "for printing support, install libpdfium"
echo "by downloading the plain x64 pdfium binary from"
echo "https://github.com/bblanchon/pdfium-binaries"
echo "and place the 'pdfium.dll' in '$MINGW_PREFIX/bin'"
echo
echo "for minifying the html5 client,"
echo "install yuicompressor"
echo
echo "for generating the documentation, install pandoc"
echo "https://github.com/jgm/pandoc/releases/latest"
echo
echo "for a more seamless theme, install https://b00merang.weebly.com/windows-10.html"
echo " (see ticket #2762)"
echo
echo "to support NVIDIA hardware accelerated encoders NVENC and NVJPEG,"
echo "install their headers and libraries"
echo "then create a pkgconfig file so the build system will detect them"
