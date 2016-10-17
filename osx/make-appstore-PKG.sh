#!/bin/bash

echo
echo "*******************************************************************************"
if [ ! -d "./image/Xpra.app" ]; then
	echo "./image/Xpra.app is missing - cannot continue"
	exit 1
fi
rm -fr ./appstore/ 2>&1 > /dev/null
mkdir appstore
cp -R ./image/Xpra.app ./appstore/
echo "WARNING: removing sound sub-app support"
rm -fr ./appstore/Xpra.app/Contents/Xpra_NoDock.app

#get the version and build info from the python build records:
export PYTHONPATH="appstore/Xpra.app/Contents/Resources/lib/python/"
VERSION=`python -c "from xpra import __version__;import sys;sys.stdout.write(__version__)"`
REVISION=`python -c "from xpra import src_info;import sys;sys.stdout.write(str(src_info.REVISION))"`
REV_MOD=`python -c "from xpra import src_info;import sys;sys.stdout.write(['','M'][src_info.LOCAL_MODIFICATIONS>0])"`
BUILD_CPU=`python -c "from xpra import build_info;import sys;sys.stdout.write(str(build_info.BUILD_CPU))"`
BUILD_INFO=""
if [ "$BUILD_CPU" != "i386" ]; then
	BUILD_INFO="-x86_64"
fi

PKG_FILENAME="./image/Xpra$BUILD_INFO-$VERSION-r$REVISION$REV_MOD-appstore.pkg"
rm -f $PKG_FILENAME >& /dev/null
echo "Making $PKG_FILENAME"

#move all the scripts to Resources/scripts:
mkdir appstore/Xpra.app/Contents/Resources/scripts
rm -f appstore/Xpra.app/Contents/MacOS/*
for x in Bug_Report GTK_info Network_info Python Xpra Launcher Config_info Keyboard_Tool OpenGL_check PythonExecWrapper Encoding_info Keymap_info Path_info Version_info Shadow Feature_info Manual PowerMonitor Webcam_Test GStreamer_info NativeGUI_info Print Websockify; do
	mv "appstore/Xpra.app/Contents/Helpers/$x" "appstore/Xpra.app/Contents/Resources/scripts/"
	if [ "$x" != "PythonExecWrapper" ]; then
		if [ "$x" == "Launcher" ]; then
			gcc -arch i386 -o "appstore/Xpra.app/Contents/MacOS/$x" "./Shell-wrapper.c"
		else
			cat appstore/Xpra.app/Contents/Info.plist | sed "s+Launcher+$x+g" | sed "s+org.xpra.Xpra+org.xpra.$x+g" | sed "s+Xpra+$x+g" > ./appstore/temp.plist
			gcc -arch i386 -o "appstore/Xpra.app/Contents/MacOS/$x" "./Shell-wrapper.c" -sectcreate __TEXT __info_plist ./appstore/temp.plist
			rm appstore/temp.plist
		fi
	fi
done
echo "MacOS:"
ls -la@ appstore/Xpra.app/Contents/MacOS
echo
echo "Helpers:"
ls -la@ appstore/Xpra.app/Contents/Helpers
#remove gstreamer bits:
rm appstore/Xpra.app/Contents/Helpers/gst*


CODESIGN_ARGS="--force --verbose --sign \"3rd Party Mac Developer Application\" --entitlements ./Xpra.entitlements"
eval codesign $CODESIGN_ARGS appstore/Xpra.app/Contents/Helpers/*
EXES=`find appstore/Xpra.app/Contents/MacOS -type f | grep -v "Launcher" | xargs`
eval codesign $CODESIGN_ARGS $EXES

CODESIGN_ARGS="--force --verbose --sign \"3rd Party Mac Developer Application\" --entitlements ./Inherit.entitlements"
LIBS=`find appstore/Xpra.app/Contents/Resources -name "*so" -or -name "*dylib" | xargs`
eval codesign $CODESIGN_ARGS $LIBS
eval "find appstore/Xpra.app/Contents/Resources/bin/ -type f -exec codesign $CODESIGN_ARGS {} \;"

CODESIGN_ARGS="--force --verbose --sign \"3rd Party Mac Developer Application\" --entitlements ./Xpra.entitlements"
eval codesign $CODESIGN_ARGS appstore/Xpra.app
productbuild --component ./appstore/Xpra.app /Applications $PKG_FILENAME --sign "3rd Party Mac Developer Installer: $CODESIGN_KEYNAME"

#show resulting file and copy it to the desktop
du -sm $PKG_FILENAME
cp $PKG_FILENAME ~/Desktop/

echo "Done PKG"
echo "*******************************************************************************"
echo
