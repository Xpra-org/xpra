#!/bin/bash
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Extra components required for the full (non-light) builds,
# run `SETUP.sh` first.

set -e

MSWINDOWS_DIR=$(dirname "$(readlink -f "$0")")
SRC_DIR=$(readlink -f "${MSWINDOWS_DIR}/../..")
cd "${MSWINDOWS_DIR}"

export XPKG="${MINGW_PACKAGE_PREFIX}-"
PACMAN=${PACMAN:-"pacman --noconfirm --needed -S"}
#PACMAN="echo pacman"
WINGET=${WINGET:-"$(cygpath -u "${LOCALAPPDATA}")/Microsoft/WindowsApps/winget.exe"}
WINGET_INSTALL="${WINGET} install --exact --silent --accept-package-agreements --accept-source-agreements --id"

#qt6 client:
$PACMAN ${XPKG}python-pyqt6
#dbus:
$PACMAN ${XPKG}dbus-glib
#yaml:
$PACMAN ${XPKG}python-yaml
#AMD AMF encoder:
$PACMAN ${XPKG}amf-headers
#bundled openssh client:
$PACMAN openssh sshpass
#manual (`groff`):
$PACMAN groff

#dependencies of browser_cookie3 and pycuda,
#best to manage them via pacman rather than have them installed via pip,
#so we get automatic updates:
#(pycryptodome* is not yet available for aarch64?)
for x in mako pycryptodome pycryptodomex keyring; do
	$PACMAN ${XPKG}python-${x}
done
#these need to be converted to PKGBUILD:
for x in browser-cookie3 pyaes pbkdf2 pytools; do
	pip3 install --break-system-packages $x
done

# Visual Studio Build Tools:
# * `cl.exe` for building the CUDA kernels (`nvcc` needs it)
# * `link.exe` and the Windows SDK (`mc.exe`, `rc.exe`) for the system service
# * `msbuild` and the .NET Framework for `DesktopLogon`
# (`--includeRecommended` pulls in the Windows SDK, which also provides `signtool.exe`)
VS_INSTALLER="vs_buildtools.exe"
if [[ ! -f "$VS_INSTALLER" ]]; then
	echo "Downloading Visual Studio Build Tools..."
	curl -fL -o "$VS_INSTALLER" "https://aka.ms/vs/18/release/vs_buildtools.exe"
fi
echo "Installing Visual Studio Build Tools..."
./"$VS_INSTALLER" --quiet --wait --norestart --nocache \
	--add Microsoft.VisualStudio.Workload.VCTools \
	--add Microsoft.VisualStudio.Workload.ManagedDesktopBuildTools \
	--includeRecommended || {
	# 3010: success, but a reboot is required
	r=$?
	if [[ $r -ne 3010 ]]; then
		echo "Visual Studio Build Tools installation failed: $r"
		exit $r
	fi
	echo "Visual Studio Build Tools installed, a reboot is required"
}

# TortoisePlink:
$WINGET_INSTALL TortoiseSVN.TortoiseSVN

# paexec:
curl -fL -o "${MINGW_PREFIX}/bin/paexec.exe" "https://www.poweradmin.com/paexec/paexec.exe"

# pandoc:
PANDOC_VERSION="3.9"
BASE_URL="https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}"
ARCHIVE="pandoc-${PANDOC_VERSION}-windows-x86_64.zip"
DOWNLOAD_URL="${BASE_URL}/${ARCHIVE}"
if [[ ! -f "$ARCHIVE" ]]; then
    echo "Downloading Pandoc ${PANDOC_VERSION}..."
    curl -fL -o "$ARCHIVE" "$DOWNLOAD_URL"
fi
echo "Installing Pandoc ${PANDOC_VERSION} to ${MINGW_PREFIX}/bin..."
$PACMAN ${XPKG}unzip
unzip -o "$ARCHIVE" "pandoc-${PANDOC_VERSION}/pandoc.exe" -d pandoc_tmp
mv "pandoc_tmp/pandoc-${PANDOC_VERSION}/pandoc.exe" "${MINGW_PREFIX}/bin/"
rm -rf pandoc_tmp

# html5 client, minified using yuicompressor (which needs java):
if [[ ! -d "${SRC_DIR}/xpra-html5" ]]; then
	git clone https://github.com/Xpra-org/xpra-html5 "${SRC_DIR}/xpra-html5"
fi
$WINGET_INSTALL Microsoft.OpenJDK.21
pip3 install --break-system-packages yuicompressor

echo
echo "if 'java' is not found in your \$PATH, set the 'JAVA' environment variable"
echo
echo "to bundle 'DesktopLogon', build 'service/DesktopLogon/DesktopLogon.sln' using 'msbuild'"
echo "and copy 'AxMSTSCLib.dll', 'MSTSCLib.dll' and 'DesktopLogon.dll' to '$MINGW_PREFIX/bin'"
echo
echo "to support NVIDIA hardware accelerated encoders NVENC, NVJPEG"
echo "and NVFBC screen capture:"
echo "* install CUDA into './cuda' in the xpra source tree,"
echo "  making sure to include the 'CUDA Runtime' component ('cuda_cudart'),"
echo "  which provides 'library_types.h', 'cuda_runtime_api.h' and 'cuda.lib'"
echo "* or install it in its default location and link it into the source tree:"
echo " 'pushd /c/Program\ Files/NVIDIA\ GPU\ Computing\ Toolkit/CUDA/;ln -sf v13.4 current;popd'"
echo " 'ln -sf /c/Program\ Files/NVIDIA\ GPU\ Computing\ Toolkit/CUDA/current ./cuda'"
echo "  (without 'MSYS=winsymlinks:nativestrict', 'ln -s' makes a full copy)"
echo "* install 'NVidia_Capture' into '$MINGW_PREFIX/lib/nvenc'"
echo "* add the pkg-config files:"
echo " 'cp pkgconfig/*.pc $MINGW_PREFIX/lib/pkgconfig/'"
echo "* install python-setuptools python-numpy python-pip"
echo
