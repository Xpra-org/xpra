#!/bin/bash

BUILDAH_DIR=`dirname $(readlink -f $0)`
pushd ${BUILDAH_DIR}

function specver() {
	V=`rpmspec -q --qf "%{version}\n" "../../rpm/$1.spec" 2> /dev/null | sort -u`
	if [ "$?" != "0" ]; then
		exit 1
	fi
	if [ "$V" == "" ]; then
		exit 1
	fi
	echo $V
}
function fetch() {
	SPECNAME=$1
	VERSION=$(specver $SPECNAME)
	if [ -z "${VERSION}" ]; then
		echo "no ${version} found in $SPECNAME"
		exit 1
	fi
	URLS=`rpmspec -P ../rpm/$SPECNAME.spec | grep "Source.*:" | awk '{print $2}'`
	if [ -z "${URLS}" ]; then
		echo "no Source URLs found in $SPECNAME"
		exit 1
	fi
	for URL in $URLS; do
		FILENAME=`echo $URL | awk -F/ '{print $NF}'`
		if [ -e "${FILENAME}" ]; then
			echo "found ${FILENAME}"
		else
			echo "downloading $FILENAME from ${URL}"
			curl --output "${FILENAME}" -L "${URL}"
		fi
	done
}
pushd pkgs
fetch "x264-xpra"
fetch "ffmpeg-xpra"
fetch "gstreamer1-plugin-timestamp"
fetch "libfakeXinerama"
fetch "python3-cairo"
fetch "python3-pycuda"
fetch "python3-pynvml"
fetch "python3-pyopengl"
fetch "python3-pyopengl"
fetch "python3-pytools"
fetch "python3-pytools"
fetch "libyuv"
popd
