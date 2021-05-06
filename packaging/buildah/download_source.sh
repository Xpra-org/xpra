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
	URL=`rpmspec -P ../rpm/$SPECNAME.spec | grep "Source.*:" | awk '{print $2}'`
	if [ -z "${URL}" ]; then
		echo "no Source URL found in $SPECNAME"
		exit 1
	fi
	FILENAME=`echo $URL | awk -F/ '{print $NF}'`
	REAL_URL="${URL/\%\{version\}/$VERSION}"
	if [ -e "${FILENAME}" ]; then
		echo "found ${FILENAME}"
	else
		echo "downloading $FILENAME from ${REAL_URL}"
		curl --output "${FILENAME}" -L "${REAL_URL}"
	fi
}
pushd pkgs
X264_COMMIT=`grep "%define commit" ../rpm/x264-xpra.spec  | awk '{print $3}'`
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
#libyuv (use github mirror to download an archive)
fetch "libyuv"
popd
