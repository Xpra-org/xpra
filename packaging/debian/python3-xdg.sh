#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -z "${REPO_ARCH_PATH}" ]; then
	REPO_ARCH_PATH="`pwd`/../repo"
fi

PYXDG_TAR_GZ=`ls ../pkgs/pyxdg-*.tar.gz | sort -V | tail -n 1`
if [ -z "${PYXDG_TAR_GZ}" ]; then
	echo "no pyxdg source found"
	exit 0
fi
#ie: github tag 'v0.29-rc2' extracts to 'pyxdg-0.29-rc2':
dirname=`tar -ztf ${PYXDG_TAR_GZ} | head -n 1 | sed 's+/.*++'`
rm -fr "./${dirname}"
tar -zxf ${PYXDG_TAR_GZ} || exit 1
pushd "./${dirname}" || exit 1
ln -sf ../python3-xdg ./debian

#install build dependencies:
if ! mk-build-deps --install --tool='apt-get -o Debug::pkgProblemResolver=yes --no-install-recommends --yes' debian/control; then
	echo "failed to install pyxdg build dependencies" >&2
	exit 1
fi
rm -f pyxdg-build-deps*

if [ `arch` == "aarch64" ]; then
	debuild --no-lintian -us -uc -b
else
	debuild -us -uc -b
fi
ls -la ../python3-xdg*deb
"${SCRIPT_DIR}/verify-debs.sh" ../python3-xdg*deb || exit 1
mv ../python3-xdg*deb ../pyxdg*changes "$REPO_ARCH_PATH"
popd
