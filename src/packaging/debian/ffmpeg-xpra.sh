#!/bin/bash

if [ ! -e "../pkgs/ffmpeg-6.1.tar.xz" ]; then
	echo "ffmpeg source not found"
	exit 1
fi
tar -Jxf ../pkgs/ffmpeg-6.1.tar.xz
mkdir ffmpeg-6.1/debian
cp -apr ffmpeg-xpra/* ffmpeg-6.1/debian
pushd ffmpeg-6.1
apt-get install -y debhelper libvpx-dev libx264-dev yasm
debuild -us -uc -b
apt-get install -y ../ffmpeg-xpra*deb
mv ../ffmpeg-xpra*deb ../ffmpeg-xpra*changes "$REPO_ARCH_PATH"
popd
