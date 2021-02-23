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
debuild -us -uc -b
popd
mv ./xpra*deb ./xpra*changes repo/
 