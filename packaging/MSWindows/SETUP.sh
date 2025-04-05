#!/bin/bash
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

set -e

export XPKG="${MINGW_PACKAGE_PREFIX}-"
PACMAN=${PACMAN:-"pacman --noconfirm --needed -S"}
#PACMAN="echo pacman"

#most packages get installed here: (python, gtk, etc):
$PACMAN ${XPKG}python ${XPKG}libnotify ${XPKG}gtk3
#media libraries (more than we actually need):
$PACMAN ${XPKG}libspng ${XPKG}libavif ${XPKG}libyuv-git ${XPKG}gst-plugins-good ${XPKG}gst-plugins-bad ${XPKG}gst-plugins-ugly
#network layer libraries:
$PACMAN ${XPKG}lz4 ${XPKG}xxhash heimdal-libs openssh sshpass ${XPKG}libsodium
#pinentry is not available for aarch64 yet:
$PACMAN ${XPKG}pinentry
#not strictly needed:
$PACMAN ${XPKG}dbus-glib
#python GStreamer bindings:
$PACMAN ${XPKG}gst-python
#development tools and libs for building extra packages:
$PACMAN base-devel ${XPKG}yasm ${XPKG}nasm gcc groff subversion rsync zip gtk-doc ${XPKG}cmake ${XPKG}gcc ${XPKG}pkgconf ${XPKG}libffi ${XPKG}python-pandocfilters
#python extensions:
for x in cryptography cffi pycparser numpy pillow appdirs paramiko comtypes netifaces setproctitle pyu2f ldap ldap3 bcrypt pynacl pyopengl pyopengl-accelerate nvidia-ml zeroconf certifi yaml py-cpuinfo winkerberos coverage psutil oauthlib pysocks pyopenssl importlib_resources pylsqpack aioquic service_identity pyvda watchdog pyqt6 wmi; do
	$PACMAN ${XPKG}python-${x}
done
#not yet available for aarch64?:
for x in cx-freeze gssapi; do
	$PACMAN ${XPKG}python-${x}
done
$PACMAN ${XPKG}amf-headers

#dependencies of browser_cookie3 and pycuda,
#best to manage them via pacman rather than have them installed via pip,
#so we get automatic updates:
#(pycryptodome* is not yet available for aarch64?)
for x in mako markupsafe typing_extensions platformdirs pip pycryptodome pycryptodomex keyring idna; do
	$PACMAN ${XPKG}python-${x}
done
$PACMAN ${XPKG}cython
$PACMAN openssl-devel
#these need to be converted to PKGBUILD:
for x in browser-cookie3 pyaes pbkdf2 pytools; do
	pip3 install $x
done
# to keep these libraries updated, you may need:
# SETUPTOOLS_USE_DISTUTILS=stdlib pip install --upgrade $PACKAGE

echo "to package the EXE, install verpatch:"
echo "https://github.com/pavel-a/ddverpatch/releases"
echo "and innosetup":
echo "https://jrsoftware.org/isdl.php"
echo "to generate the MSI, install MSIWrapper:"
echo "https://www.exemsi.com/"
echo "to generate the SBOM, install Python 3.12.x for MS Windows"
echo "then install cyclonedx-py using pip"
echo
echo "for printing support, install libpdfium"
echo "by downloading the plain x64 pdfium binary from"
echo "https://github.com/bblanchon/pdfium-binaries"
echo "and place the 'pdfium.dll' in '$MSYSTEM_PREFIX/bin'"
echo
echo "for generating the documentation, install pandoc"
echo "https://github.com/jgm/pandoc/releases/latest"
echo
echo "for a more seamless theme, install https://b00merang.weebly.com/windows-10.html"
echo "into $MSYSTEM_PREFIX/share/themes/Windows-10/"
echo " (see ticket #2762)"
echo
echo "to support NVIDIA hardware accelerated encoders NVENC, NVJPEG"
echo "and NVFBC screen capture:"
echo "* install CUDA in its default location"
echo "* create symbolic links so the build system can find CUDA more easily:"
echo " 'pushd /c/Program\ Files/NVIDIA\ GPU\ Computing\ Toolkit/CUDA/;ln -sf v12.0 current;popd'"
echo " 'ln -sf /c/Program\ Files/NVIDIA\ GPU\ Computing\ Toolkit/CUDA/current ./cuda'"
echo "* install 'NVidia_Capture' into '$MINGW_PREFIX/lib/nvenc'"
echo "* add the pkg-config files:"
echo " 'cp pkgconfig/*.pc $MINGW_PREFIX/lib/pkgconfig/'"
echo "* install python-setuptools python-numpy python-pip"
echo
echo "for SBOM"
echo "* install Python 3.12 into 'C:\Program Files'"
echo "* add cyclonedx to it: 'Python.exe -m pip install cyclonedx-bom'"
echo
