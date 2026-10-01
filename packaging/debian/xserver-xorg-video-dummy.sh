#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -z "${REPO_ARCH_PATH}" ]; then
	REPO_ARCH_PATH="`pwd`/../repo"
fi

DUMMY_TAR_XZ=`ls ../pkgs/xf86-video-dummy-*.tar.xz`
dirname=`echo ${DUMMY_TAR_XZ} | sed 's+../pkgs/++g' | sed 's/.tar.xz//' | sort -V | tail -n 1`
rm -fr "./${dirname}"
tar -Jxf ${DUMMY_TAR_XZ}
pushd "./${dirname}"
ln -sf ../xserver-xorg-video-dummy ./debian

#install build dependencies:
if ! mk-build-deps --install --tool='apt-get -o Debug::pkgProblemResolver=yes --yes' debian/control; then
	echo "failed to install xserver-xorg-video-dummy build dependencies" >&2
	exit 1
fi
rm -f xserver-xorg-video-dummy-build-deps*

if [ `arch` == "aarch64" ]; then
  debuild -us -uc -b --no-lintian -Zxz
else
  debuild -us -uc -b -Zxz
fi
ls -la ../xserver-xorg-video-dummy*deb
"${SCRIPT_DIR}/verify-debs.sh" ../xserver-xorg-video-dummy*deb || exit 1
mv ../xserver-xorg-video-dummy*deb ../xserver-xorg-video-dummy*changes "$REPO_ARCH_PATH"
popd
