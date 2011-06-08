#!/bin/bash

XPRA_VERSION=`PYTHONPATH="./src/:${PYTHONPATH}" python -c "from xpra import __version__; print __version__;"`
BUILD_NO=${BUILD_NO:=1}

unset DISTRIB_CODENAME
if [ -r "/etc/lsb-release" ]; then
	. /etc/lsb-release
fi
if [ -z "${DISTRIB_CODENAME}" ]; then
	DISTRIB_CODENAME=`lsb_release -c | awk '{print $2}'`
fi
if [ "${DISTRIB_CODENAME}" == "n/a" ]; then
	DISTRIB_CODENAME=""
fi
if [ -z "${DISTRIB_CODENAME}" ]; then
	DISTRIB_CODENAME=`cat /etc/debian_version | awk -F/ '{print $2}'`
fi
if [ -z "${DISTRIB_CODENAME}" ]; then
	echo "cannot find distro codename"
	exit 1
fi
PY_MAJOR=`python -V 2>&1  | awk  '{print $2}' | awk -F . '{print $1}'`
PY_MINOR=`python -V 2>&1  | awk  '{print $2}' | awk -F . '{print $2}'`
PY_DIR="python${PY_MAJOR}.${PY_MINOR}"
ARCH=`uname -m | sed 's/x86_64/amd64/' | sed 's/i686/i386/'`
PKG="xpra-${XPRA_VERSION}-${BUILD_NO}.${ARCH}.deb"
PKG_FILE_PATH="dists/${DISTRIB_CODENAME}/main/binary-${ARCH}"
TARGET="../../../${PKG_FILE_PATH}"
echo "Building ${PKG} for ${DISTRIB_CODENAME}"

rm -fr deb build install
rm -f xpra/wait_for_x_server.c
rm -f wimpiggy/lowlevel/bindings.c

./do-build

if [[ ! -r "./install/lib64/python/wimpiggy/lowlevel/bindings.so" && ! -r "./install/lib/python/wimpiggy/lowlevel/bindings.so" ]]; then
	echo "bindings.so failed"
	exit 1
fi
if [[ ! -r "./install/lib64/python/xpra/wait_for_x_server.so" && ! -r "./install/lib/python/xpra/wait_for_x_server.so" ]]; then
	echo "wait_for_x_server.so failed"
	exit 1
fi


SIZE=`du -sm install | awk '{print $1}'`

mkdir deb
mkdir -p deb/usr/lib/${PY_DIR}
cp -apr install/lib/python/* deb/usr/lib/${PY_DIR}
mkdir -p deb/usr/bin
cp -apr install/bin deb/usr/
cp -apr install/share deb/usr/
mkdir -p deb/DEBIAN
cp xpra.dsc deb/DEBIAN/control
echo "Architecture: ${ARCH}" >> deb/DEBIAN/control
#echo "Distribution: ${DISTRIB_CODENAME}" >> deb/DEBIAN/control
echo "Installed-Size: ${SIZE}" >> deb/DEBIAN/control
#echo "Filename: ${PKG_FILE_PATH}/${PKG}" >> deb/DEBIAN/control
echo "" >> deb/DEBIAN/control

sed 's/DISTRIBUTION/${DISTRIB_CODENAME}/g' < ./changelog > deb/DEBIAN/changelog
echo "-- Antoine Martin <antoine@nagafix.co.uk>  `date -R`" >> deb/DEBIAN/changelog
echo "" >> deb/DEBIAN/changelog

dpkg -b deb ${PKG}
mkdir -p ${TARGET}
mv ${PKG} ${TARGET}/
