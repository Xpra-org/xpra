#!/bin/bash

if [ ! -e "../pkgs/ffmpeg-4.4.tar.xz" ]; then
	echo "ffmpeg source not found"
	exit 1
fi
tar -Jxf ../pkgs/ffmpeg-4.4.tar.xz
mkdir ffmpeg-4.4/debian
cp -apr ffmpeg-xpra/* ffmpeg-4.4/debian
pushd ffmpeg-4.4
apt-get install -y debhelper libvpx-dev libx264-dev yasm
debuild -us -uc -b
apt-get install -y ../ffmpeg-xpra*deb
mv ../ffmpeg-xpra*deb ../ffmpeg-xpra*changes "$REPO_ARCH_PATH"
popd
