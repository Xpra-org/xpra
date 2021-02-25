#!/bin/bash

apt-get update
apt-get upgrade -y
apt-get dist-upgrade -y

#the image should already have everything needed,
#unless something was added to the control file
#after the image had already been generated:
apt-get install -y devscripts
mk-build-deps --install --tool='apt-get -o Debug::pkgProblemResolver=yes --no-install-recommends --yes' debian/control
#mk-build-deps --install --tool='apt-get -o Debug::pkgProblemResolver=yes --yes' debian/control

VERSION=4.1
tar -Jxf pkgs/xpra-$VERSION.tar.xz
pushd xpra-$VERSION
ln -sf packaging/debian .

#the control file has a few distribution specific entries
#ie:
# '#buster:         ,libturbojpeg0'
#we uncomment the lines for this specific distro (by adding a new line after "#$DISTRO:"):
#first figure out the distribution's codename:
DEBIAN_FRONTEND=noninteractive apt-get install lsb-release perl -y
CODENAME=`lsb_release -c | awk '{print $2}'`
#ie: CODENAME=bionic
perl -i.bak -pe "s/#${CODENAME}:/#${CODENAME}:\\n/g" debian/control

#add revision to version number to changelog
REVISION=`PYTHONPATH=. python -c 'from xpra.src_info import REVISION;print(REVISION)'`
if [ "${REVISION}" != "" ]; then
	perl -i.bak -pe "s/-/-r${REVISION}-/g" debian/changelog
fi

debuild -us -uc -b
popd
eval `dpkg-architecture -s`
REPO_ARCH_PATH="repo/main/binary-$DEB_BUILD_ARCH"
mkdir -p $REPO_ARCH_PATH
rm xpra-build-deps*
ls -la ./xpra*deb
mv ./xpra*deb ./xpra*changes $REPO_ARCH_PATH
