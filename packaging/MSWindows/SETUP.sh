#!/bin/bash
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

set -e

SCRIPT_DIR="$(dirname "$0")"
export XPKG="${MINGW_PACKAGE_PREFIX}-"
PACMAN=${PACMAN:-"pacman --noconfirm --needed -S"}
#PACMAN="echo pacman"

#most packages get installed here: (python, gtk, etc):
$PACMAN ${XPKG}python ${XPKG}libnotify ${XPKG}gtk3
#media libraries (more than we actually need):
$PACMAN ${XPKG}libavif ${XPKG}libyuv ${XPKG}gst-plugins-good ${XPKG}gst-plugins-bad ${XPKG}gst-plugins-ugly
#Intel oneVPL: HEVC 4:4:4 hardware decode on Intel GPUs:
$PACMAN ${XPKG}libvpl
#more codecs:
$PACMAN ${XPKG}libde265 ${XPKG}libx264 ${XPKG}libvpx ${XPKG}openh264 ${XPKG}dav1d ${XPKG}aom ${XPKG}libwebp ${XPKG}openjph
#network layer libraries:
$PACMAN ${XPKG}lz4 ${XPKG}zstd ${XPKG}xxhash heimdal-libs ${XPKG}libsodium
#pinentry is not available for aarch64 yet:
$PACMAN ${XPKG}pinentry
#make qr codes:
$PACMAN ${XPKG}qrencode
#python GStreamer bindings:
$PACMAN ${XPKG}gst-python
#development tools and libs for building extra packages:
$PACMAN base-devel ${XPKG}yasm ${XPKG}nasm gcc subversion rsync zip gtk-doc ${XPKG}cmake ${XPKG}gcc ${XPKG}pkgconf ${XPKG}libffi ${XPKG}python-pandocfilters
#python extensions:
for x in cryptography cffi pycparser numpy pillow appdirs asyncssh paramiko comtypes netifaces setproctitle pyu2f fido2 ldap ldap3 bcrypt pynacl pyopengl pyopengl-accelerate nvidia-ml zeroconf certifi py-cpuinfo winkerberos coverage psutil oauthlib pysocks pyopenssl importlib_resources pylsqpack aioquic service_identity pyvda watchdog winloop pyglet; do
	$PACMAN ${XPKG}python-${x}
done
#not yet available for aarch64?:
for x in cx-freeze gssapi; do
	$PACMAN ${XPKG}python-${x}
done
for x in markupsafe typing_extensions platformdirs pip idna; do
	$PACMAN ${XPKG}python-${x}
done
$PACMAN ${XPKG}cython
$PACMAN openssl-devel
#scram authentication (#1771), needs to be converted to PKGBUILD:
pip3 install --break-system-packages scramp
# to keep these libraries updated, you may need:
# SETUPTOOLS_USE_DISTUTILS=stdlib pip install --upgrade $PACKAGE

curl -sL "https://api.nuget.org/v3-flatcontainer/verpatch/1.0.14/verpatch.1.0.14.nupkg" -o "verpatch.nupkg"
python -c "import zipfile; zipfile.ZipFile('verpatch.nupkg').extract('lib/win/verpatch.exe', '.')"
mv lib/win/verpatch.exe "$MINGW_PREFIX/bin/"
rmdir lib/win && rmdir lib
rm "verpatch.nupkg"

# VA-API Compatibility Pack (libva.dll + vaon12_drv_video.dll):
VACP_VERSION="1.0.2"
VACP_ID="microsoft.direct3d.videoaccelerationcompatibilitypack"
curl -sL "https://api.nuget.org/v3-flatcontainer/${VACP_ID}/${VACP_VERSION}/${VACP_ID}.${VACP_VERSION}.nupkg" \
    -o "vacp.nupkg"
case "${MSYSTEM_CARCH}" in
    aarch64) NUGET_ARCH="arm64" ;;
    *)       NUGET_ARCH="x64"   ;;
esac
python -c "
import zipfile
src = 'build/native/${NUGET_ARCH}/bin/'
with zipfile.ZipFile('vacp.nupkg') as z:
    for name in z.namelist():
        if name.startswith(src) and not name.endswith('/'):
            z.extract(name, '.')
            print('extracted', name)
"
mv "build/native/${NUGET_ARCH}/bin/"* "$MINGW_PREFIX/bin/"
rm -rf build "vacp.nupkg"

pushd "${SCRIPT_DIR}/mingw-w64-pdfium-bin"
rm -f ./mingw-*-pdfium-bin-*.pkg.tar.*
makepkg -sCLf
pacman --noconfirm -U ./mingw-*-pdfium-bin-*.pkg.tar.*
popd

# InnoSetup:
INNO_VERSION="6.7.1"
INNO_TAG="is-$(echo "${INNO_VERSION}" | tr '.' '_')"
INSTALLER="innosetup-${INNO_VERSION}.exe"
DOWNLOAD_URL="https://github.com/jrsoftware/issrc/releases/download/${INNO_TAG}/${INSTALLER}"
INSTALL_DIR="C:\\Program Files (x86)\\Inno Setup 6"
if [[ ! -f "$INSTALLER" ]]; then
    echo "Downloading Inno Setup ${INNO_VERSION}..."
    curl -fL -o "$INSTALLER" "$DOWNLOAD_URL"
fi
echo "Installing Inno Setup ${INNO_VERSION}..."
./"$INSTALLER" \
    //VERYSILENT \
    //NORESTART \
    //SUPPRESSMSGBOXES \
    //DIR="${INSTALL_DIR}"

echo "to generate the MSI, install MSIWrapper:"
echo "https://www.exemsi.com/"
echo
echo "for non-light builds, run SETUP_EXTRAS.sh"
echo
echo "for SBOM, run SETUP_SBOM.sh"
echo
