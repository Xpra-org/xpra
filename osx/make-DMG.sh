#!/bin/sh

CLIENT_ONLY="${CLIENT_ONLY:=0}"
APP_DIR="./image/Xpra.app"
if [ "${CLIENT_ONLY}" == "1" ]; then
	APP_DIR="./image/Xpra-Client.app"
fi

echo
echo
echo "*******************************************************************************"
if [ ! -d "${APP_DIR}" ]; then
	echo "${APP_DIR} is missing!"
	echo "run make-app.sh first"
	exit 1
fi

#get the version and build info from the python build records:
PYTHON="${PYTHON:=python}"
PYTHON_MAJOR_VERSION=`${PYTHON} -c 'import sys;sys.stdout.write("%s" % sys.version_info[0])'`
export PYTHONPATH="${APP_DIR}/Contents/Resources/lib/python/"
VERSION=`${PYTHON} -c "from xpra import __version__;import sys;sys.stdout.write(__version__)"`
REVISION=`${PYTHON} -c "from xpra import src_info;import sys;sys.stdout.write(str(src_info.REVISION))"`
REV_MOD=`${PYTHON} -c "from xpra import src_info;import sys;sys.stdout.write(['','M'][src_info.LOCAL_MODIFICATIONS>0])"`
BUILD_BIT=`${PYTHON} -c "from xpra import build_info;import sys;sys.stdout.write(str(build_info.BUILD_BIT))"`
BUILD_INFO=""
if [ "${PYTHON_MAJOR_VERSION}" == "3" ]; then
	BUILD_INFO="${BUILD_INFO}-Python3"
fi
if [ "$BUILD_BIT" != "32bit" ]; then
	BUILD_INFO="${BUILD_INFO}-x86_64"
fi

DMG_NAME="Xpra$BUILD_INFO-$VERSION-r$REVISION$REV_MOD.dmg"
if [ "${CLIENT_ONLY}" == "1" ]; then
	DMG_NAME="Xpra-Client$BUILD_INFO-$VERSION-r$REVISION$REV_MOD.dmg"
fi
echo "Creating $DMG_NAME"

rm -fr image/Blank.*
rm -fr image/*dmg

echo "Mounting blank DMG"
mkdir -p image/Blank
cp Blank.dmg.bz2 image/
bunzip2 image/Blank.dmg.bz2
hdiutil mount image/Blank.dmg -mountpoint ./image/Blank

echo "Copying app into the DMG"
rsync -rpltgo ${APP_DIR} ./image/Blank/
chmod -Rf go-w image/Blank/*
hdiutil detach image/Blank

echo "Creating compressed DMG"
hdiutil convert image/Blank.dmg -format UDBZ -o image/$DMG_NAME

if [ ! -z "${CODESIGN_KEYNAME}" ]; then
		echo "Signing with key '${CODESIGN_KEYNAME}'"
        codesign --deep --force --verify --verbose --sign "Developer ID Application: ${CODESIGN_KEYNAME}" image/$DMG_NAME
else
		echo "DMG Signing skipped (no keyname)"
fi

echo "Copying $DMG_NAME to the desktop"
cp image/$DMG_NAME ~/Desktop/
echo "Size of disk image: `du -sh image/$DMG_NAME`"

echo "Done DMG"
echo "*******************************************************************************"
echo
