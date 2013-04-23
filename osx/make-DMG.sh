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
REVISION=`python -c "from xpra import build_info;import sys;sys.stdout.write(build_info.REVISION)"`
DMG_NAME="Xpra-$VERSION-$REVISION.dmg"
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
echo "Copying to the desktop"
cp image/$DMG_NAME ~/Desktop/

echo "Done"
echo "*******************************************************************************"
echo