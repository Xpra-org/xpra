#!/bin/bash

#apt-get update
#apt-get upgrade -y
#apt-get dist-upgrade -y

eval `dpkg-architecture -s`
REPO_ARCH_PATH="`pwd`/repo/main/binary-$DEB_BUILD_ARCH"
export REPO_ARCH_PATH
mkdir -p $REPO_ARCH_PATH

ls -la
ls -la debian
ls -la pkgs

BASH="bash -x"
if [ "${DEBUG:-0}" == "1" ]; then
	BASH="bash -x"
fi

pushd debian
$BASH ./libcuda1.sh
$BASH ./libnvidia-fbc1.sh
$BASH ./xpra-html5.sh
$BASH ./xpra.sh
popd
