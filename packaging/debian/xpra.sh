#!/bin/bash

eval `dpkg-architecture -s`

if [ -z "${REPO_ARCH_PATH}" ]; then
	REPO_ARCH_PATH="`pwd`/../repo"
fi

#find the latest version we can build:
XPRA_TAR_XZ=`ls ../pkgs/xpra-6.3.2.*tar.xz | grep -v html5 | sort -V | tail -n 1`
if [ -z "${XPRA_TAR_XZ}" ]; then
	echo "no xpra source found"
	exit 0
fi

dirname=`echo ${XPRA_TAR_XZ} | sed 's+../pkgs/++g' | sed 's/.tar.xz//'`
rm -fr "./${dirname}"
tar -Jxf ${XPRA_TAR_XZ}
pushd "./${dirname}"
ln -sf packaging/debian/xpra ./debian

#the control file has a few distribution specific entries
#ie:
# '#buster:         ,libturbojpeg0'
#we uncomment the lines for this specific distro (by adding a new line after "#$DISTRO:"):
#first figure out the distribution's codename:
CODENAME=`lsb_release -c | awk '{print $2}'`
#ie: CODENAME=bionic
perl -i.bak -pe "s/#${CODENAME}:/#${CODENAME}:\\n/g" debian/control

#install build dependencies:
mk-build-deps --install --tool='apt-get -o Debug::pkgProblemResolver=yes --no-install-recommends --yes' debian/control
#mk-build-deps --install --tool='apt-get -o Debug::pkgProblemResolver=yes --yes' debian/control
rm -f xpra-build-deps*

#install latest cython since the one Debian / Ubuntu tends to be out of date:
DEBIAN_FRONTEND=noninteractive apt-get -y install python3-pip
DEBIAN_FRONTEND=noninteractive apt-get -y remove cython3
PIP_BREAK_SYSTEM_PACKAGES=1 pip3 install cython

#add revision to version number to changelog
REVISION=`PYTHONPATH=. python3 -c 'from xpra.src_info import REVISION;print(REVISION)'`
if [ "${REVISION}" == "" ]; then
	echo "cannot build: xpra revision not found in src_info"
	exit 1
fi
head -n 1 "./debian/changelog" | sed "s/-/-r${REVISION}-/g" > "debian/changelog.new"
tail -n +2 "./debian/changelog" >> "./debian/changelog.new"
mv "./debian/changelog.new" "./debian/changelog"
head -n 10 "./debian/changelog"

#now figure out if this package is already in the repository:
CHANGELOG_VERSION=`head -n 1 "./debian/changelog" | sed 's/.*(//g' | sed 's/).*//g'`
DEB_FILENAME="xpra-${CHANGELOG_VERSION}_$DEB_BUILD_ARCH.deb"
MATCH=`find $REPO_ARCH_PATH/ -name "${DEB_FILENAME}" | wc -l`
if [ "$MATCH" != "0" ]; then
	echo "package already exists"
else
  BUILD_TYPE="DEB"
	if [ `arch` == "aarch64" ]; then
		debuild --no-lintian -us -uc -b
	else
		debuild -us -uc -b
	fi
	ls -la ../xpra*deb
	cp ../xpra*deb ../xpra*changes "$REPO_ARCH_PATH"
fi
popd
