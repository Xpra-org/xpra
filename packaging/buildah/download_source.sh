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
	FILENAME=$2
	URL=$3
	VERSION=$(specver $SPECNAME)
	if [ -z "${VERSION}" ]; then
		echo "no ${version} found in $SPECNAME"
		exit 1
	fi
	REAL_FILENAME="${FILENAME/\%\{version\}/$VERSION}"
	if [ -e "${REAL_FILENAME}" ]; then
		echo "found ${REAL_FILENAME}"
	else
		curl -o "${REAL_FILENAME}" "${URL}/${REAL_FILENAME}"
	fi
}
pushd pkgs
fetch "ffmpeg-xpra" "ffmpeg-%{version}.tar.xz" "http://www.ffmpeg.org/releases"
fetch "gstreamer1-plugin-timestamp" "gst-plugin-timestamp-%{version}.tar.xz" "https://xpra.org/src"
fetch "libfakeXinerama" "libfakeXinerama-%{version}.tar.bz2" "https://xpra.org/src"
fetch "python3-cairo"    "pycairo-%{version}.tar.gz"             "https://github.com/pygobject/pycairo/releases/download/v%{version}"
fetch "python3-pycuda"   "pycuda-%{version}.tar.gz"              "https://files.pythonhosted.org/packages/46/61/47d3235a4c13eec5a5f03594ddb268f4858734e02980afbcd806e6242fa5"
fetch "python3-pynvml"   "nvidia-ml-py-%{version}.tar.gz"        "https://files.pythonhosted.org/packages/4c/e7/f6fef887708f601cda64c8fd48dcb80a0763cb6ee4eaf89939bdc165ce41"
fetch "python3-pyopengl" "PyOpenGL-%{version}.tar.gz"            "https://files.pythonhosted.org/packages/b8/73/31c8177f3d236e9a5424f7267659c70ccea604dab0585bfcd55828397746"
fetch "python3-pyopengl" "PyOpenGL-accelerate-%{version}.tar.gz" "https://files.pythonhosted.org/packages/a2/3c/f42a62b7784c04b20f8b88d6c8ad04f4f20b0767b721102418aad94d8389"
fetch "python3-pytools"  "pytools-%{version}.tar.gz"             "https://files.pythonhosted.org/packages/16/ed/f4b298876b9b624150cc01830075f7cb0b9e09c1abfc46daef14811f3eed"
#libyuv (from git)
if [ ! -e "./libyuv-0.tar.xz" ]; then
	git clone https://chromium.googlesource.com/libyuv/libyuv
	pushd "./libyuv"
	git archive --format=tar --prefix=libyuv-0/ 4bd08cb | xz  > "../libyuv-0.tar.xz"
	popd
	rm -fr "./libyuv"
fi
popd
