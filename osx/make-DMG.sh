#!/bin/sh

echo
echo "*******************************************************************************"
if [ ! -d "image/Xpra.app" ]; then
	echo "image/Xpra.app is missing!"
	echo "run make-app.sh first"
	exit 1
fi

export PYTHONPATH="image/Xpra.app/Contents/Resources/lib/python/"
VERSION=`python -c "from xpra import __version__;import sys;sys.stdout.write(__version__)"`
#prefer revision directly from svn:
REVISION=`svnversion -n .. | awk -F: '{print $2}'`
if [ -z "${REVISION}" ]; then
	#fallback to using revision recorded in build info
	REVISION=`python -c "from xpra import src_info;import sys;sys.stdout.write(str(src_info.REVISION))"`
fi
#check for 64-bit builds
BUILD_INFO=""
AMD64=`python -c "import sys;print(sys.maxsize > 2**32)"`
if [ "$AMD64" == "True" ]; then
	BUILD_INFO="-x86_64"
fi
DMG_NAME="Xpra$BUILD_INFO-$VERSION-r$REVISION.dmg"
echo "Creating $DMG_NAME"

rm -fr image/Blank.*
rm -fr image/*dmg

echo "Mounting blank DMG"
mkdir -p image/Blank
cp Blank.dmg.bz2 image/
bunzip2 image/Blank.dmg.bz2
hdiutil mount image/Blank.dmg -mountpoint ./image/Blank

echo "Copying Xpra.app into the DMG"
rsync -rpltgo image/Xpra.app ./image/Blank/
chmod -Rf go-w image/Blank/Xpra.app
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
