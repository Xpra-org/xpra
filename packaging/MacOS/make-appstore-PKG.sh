#!/bin/bash

BUILDNO="${BUILDNO:="0"}"

echo
echo "*******************************************************************************"
if [ ! -d "./image/Xpra.app" ]; then
	echo "./image/Xpra.app is missing - cannot continue"
	exit 1
fi
rm -fr ./appstore/ 2>&1 > /dev/null
mkdir appstore
cp -R ./image/Xpra.app ./appstore/

#get the version and build info from the python build records:
export PYTHONPATH="appstore/Xpra.app/Contents/Resources/lib/python/"
VERSION=`python -c "from xpra import __version__;import sys;sys.stdout.write(__version__)"`
REVISION=`python -c "from xpra import src_info;import sys;sys.stdout.write(str(src_info.REVISION))"`
REV_EXTRA=""
if [ "$BUILDNO" != "0" ]; then
	REV_EXTRA=".$BUILDNO"
fi
REV_MOD=`python -c "from xpra import src_info;import sys;sys.stdout.write(['','M'][src_info.LOCAL_MODIFICATIONS>0])"`
BUILD_CPU=`python -c "from xpra import build_info;import sys;sys.stdout.write(str(build_info.BUILD_CPU))"`
BUILD_INFO=""
if [ "$BUILD_CPU" != "i386" ]; then
	BUILD_INFO="-x86_64"
fi
echo "VERSION=$VERSION"
echo "REVISION=$REVISION"
echo "BUILDNO=$BUILDNO"
echo "REV_MOD=$REV_MOD"
echo "BUILD_CPU=$BUILD_CPU"
echo "BUILD_INFO=$BUILD_INFO"
PKG_FILENAME="./image/Xpra$BUILD_INFO-$VERSION-r$REVISION$REV_MOD$REV_EXTRA-appstore.pkg"
rm -f $PKG_FILENAME >& /dev/null
echo "Making $PKG_FILENAME"

#for creating shell or C command wrappers that live in "Helpers":
function helper_wrapper() {
	filename=`basename $1`
	wrapper=$2
	cp ./Info-template.plist ./appstore/temp.plist
	#sed -i '' -e "s+%BUNDLEID%+org.xpra.$filename+g" ./appstore/temp.plist
	sed -i '' -e "s+%BUNDLEID%+org.xpra.Xpra+g" ./appstore/temp.plist
	sed -i '' -e "s+%EXECUTABLE%+$filename+g" ./appstore/temp.plist
	sed -i '' -e "s+%VERSION%+$VERSION+g" ./appstore/temp.plist
	sed -i '' -e "s+%REVISION%+$REVISION$REV_MOD+g" ./appstore/temp.plist
	sed -i '' -e "s+%BUILDNO%+$BUILDNO+g" ./appstore/temp.plist
	gcc -arch i386 -o "appstore/Xpra.app/Contents/Helpers/$filename" "./${wrapper}-wrapper.c" -sectcreate __TEXT __info_plist ./appstore/temp.plist
	rm appstore/temp.plist
}

#move all the scripts to Resources/scripts:
mkdir appstore/Xpra.app/Contents/Resources/scripts
for x in `ls appstore/Xpra.app/Contents/Helpers/`; do
	mv "appstore/Xpra.app/Contents/Helpers/$x" "appstore/Xpra.app/Contents/Resources/scripts/"
	helper_wrapper "$x" "Shell"
done
for x in `ls appstore/Xpra.app/Contents/Resources/bin/gst*`; do
	helper_wrapper "$x" "C"
done
helper_wrapper "sshpass" "C"
#the binaries in "/Contents/Resources/bin" look for "@executable_path/../Resources/lib/*dylib"
#make it work with a symlink (ugly hack):
ln -sf . appstore/Xpra.app/Contents/Resources/Resources

#keep only one binary in MacOS:
rm -f appstore/Xpra.app/Contents/MacOS/*
gcc -arch i386 -o "appstore/Xpra.app/Contents/MacOS/Launcher" "./Shell-wrapper.c"

echo "MacOS:"
ls -la@ appstore/Xpra.app/Contents/MacOS
echo
echo "Helpers:"
ls -la@ appstore/Xpra.app/Contents/Helpers

#sound sub-app has a different binary: "Xpra":
rm -fr ./appstore/Xpra.app/Contents/Xpra_NoDock.app/Contents/MacOS
mkdir ./appstore/Xpra.app/Contents/Xpra_NoDock.app/Contents/MacOS
gcc -arch i386 -o "appstore/Xpra.app/Contents/Xpra_NoDock.app/Contents/MacOS/Xpra" "./Shell-wrapper.c" -sectcreate __TEXT __info_plist appstore/Xpra.app/Contents/Xpra_NoDock.app/Contents/Info.plist

CODESIGN_ARGS="--force --verbose --sign \"3rd Party Mac Developer Application\" --entitlements ./Xpra.entitlements"
eval codesign $CODESIGN_ARGS appstore/Xpra.app/Contents/Helpers/*
EXES=`find appstore/Xpra.app/Contents/MacOS -type f | xargs`
eval codesign $CODESIGN_ARGS $EXES

CODESIGN_ARGS="--force --verbose --sign \"3rd Party Mac Developer Application\" --entitlements ./Inherit.entitlements"
LIBS=`find appstore/Xpra.app/Contents/Resources -name "*so" -or -name "*dylib" | xargs`
eval codesign $CODESIGN_ARGS $LIBS
eval "find appstore/Xpra.app/Contents/Resources/bin/ -type f -exec codesign $CODESIGN_ARGS {} \;"

CODESIGN_ARGS="--force --verbose --sign \"3rd Party Mac Developer Application\" --entitlements ./Xpra.entitlements"
eval codesign $CODESIGN_ARGS appstore/Xpra.app/Contents/Xpra_NoDock.app/Contents/MacOS/Xpra
eval codesign $CODESIGN_ARGS appstore/Xpra.app/Contents/Xpra_NoDock.app
eval codesign $CODESIGN_ARGS appstore/Xpra.app
productbuild --component ./appstore/Xpra.app /Applications $PKG_FILENAME --sign "3rd Party Mac Developer Installer: $CODESIGN_KEYNAME"

#show resulting file and copy it to the desktop
du -sm $PKG_FILENAME
cp $PKG_FILENAME ~/Desktop/

echo "Done PKG"
echo "*******************************************************************************"
echo
