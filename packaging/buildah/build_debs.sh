#!/bin/bash

apt-get update
apt-get upgrade -y
apt-get dist-upgrade -y

#the image should already have everything needed,
#unless something was added to the control file
#after the image had already been generated:
mk-build-deps --install --tool='apt-get -o Debug::pkgProblemResolver=yes --no-install-recommends --yes' debian/control
#mk-build-deps --install --tool='apt-get -o Debug::pkgProblemResolver=yes --yes' debian/control

eval `dpkg-architecture -s`
REPO_ARCH_PATH="`pwd`/repo/main/binary-$DEB_BUILD_ARCH"
mkdir -p $REPO_ARCH_PATH
rm xpra-build-deps*

VERSION=4.2
tar -Jxf pkgs/xpra-$VERSION.tar.xz
pushd xpra-$VERSION
ln -sf packaging/debian .

#the control file has a few distribution specific entries
#ie:
# '#buster:         ,libturbojpeg0'
#we uncomment the lines for this specific distro (by adding a new line after "#$DISTRO:"):
#first figure out the distribution's codename:
CODENAME=`lsb_release -c | awk '{print $2}'`
#ie: CODENAME=bionic
perl -i.bak -pe "s/#${CODENAME}:/#${CODENAME}:\\n/g" debian/control

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

#now figure out if this packages is already in the repository:
CHANGELOG_VERSION=`head -n 1 ."./debian/changelog" | sed 's/.*(//g' | sed 's/).*//g'`
DEB_FILENAME="xpra-${CHANGELOG_VERSION}_$DEB_BUILD_ARCH.deb"
MATCH=`find $REPO_ARCH_PATH/ -name "${DEB_FILENAME}" | wc -l`
if [ "$MATCH" == "0" ]; then
	debuild -us -uc -b
	ls -la ../xpra*deb
	mv ../xpra*deb ../xpra*changes $REPO_ARCH_PATH
fi
popd
