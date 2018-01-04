#!/bin/bash

PYTHON_VERSION="${PYTHON_VERSION:=python2}"

STRIP_DEFAULT="${STRIP_DEFAULT:=1}"
STRIP_GSTREAMER_PLUGINS="${STRIP_GSTREAMER_PLUGINS:=$STRIP_DEFAULT}"
STRIP_SOURCE="${STRIP_SOURCE:=0}"
STRIP_OPENGL="${STRIP_OPENGL:=$STRIP_DEFAULT}"
STRIP_NUMPY="${STRIP_NUMPY:=$STRIP_DEFAULT}"
CLIENT_ONLY="${CLIENT_ONLY:=0}"

DO_TESTS="${DO_TESTS:-1}"

BUILDNO="${BUILDNO:="0"}"
APP_DIR="./image/Xpra.app"
if [ "${CLIENT_ONLY}" == "1" ]; then
	APP_DIR="./image/Xpra-Client.app"
	BUILD_ARGS="${BUILD_ARGS} --without-server --without-shadow --without-proxy --without-html5"
	DO_TESTS="0"
fi
CONTENTS_DIR="${APP_DIR}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RSCDIR="${CONTENTS_DIR}/Resources"
HELPERS_DIR="${CONTENTS_DIR}/Helpers"
LIBDIR="${RSCDIR}/lib"


echo "*******************************************************************************"
echo "Deleting existing xpra modules and temporary directories"
PYTHON_PREFIX=`python-config --prefix`
PYTHON_PACKAGES=`ls -d ${PYTHON_PREFIX}/lib/${PYTHON_VERSION}*/site-packages | sort | tail -n 1`
rm -fr "${PYTHON_PACKAGES}/xpra"*
rm -fr image/* dist
ln -sf ../src/dist ./dist
rm -fr "$PYTHON_PACKAGES/xpra"

echo
echo "*******************************************************************************"
echo "Building and installing locally"
pushd ../src

svn upgrade ../.. >& /dev/null
python -c "from add_build_info import record_src_info;record_src_info()"
rm -fr build/* dist/*
python ./setup.py clean
INSTALL_LOG=`pwd`/install.log
echo "./setup.py install ${BUILD_ARGS}"
echo " (see ${INSTALL_LOG} for details - this may take a minute or two)"
python ./setup.py install ${BUILD_ARGS} >& ${INSTALL_LOG}
if [ "$?" != "0" ]; then
	popd
	echo "ERROR: install failed"
	echo
	tail -n 20 ${INSTALL_LOG}
	exit 1
fi
#get the version and build info from the python build records:
export PYTHONPATH="."
VERSION=`python -c "from xpra import __version__;import sys;sys.stdout.write(__version__)"`
REVISION=`python -c "from xpra import src_info;import sys;sys.stdout.write(str(src_info.REVISION))"`
REV_MOD=`python -c "from xpra import src_info;import sys;sys.stdout.write(['','M'][src_info.LOCAL_MODIFICATIONS>0])"`
echo "OK"

if [ "${DO_TESTS}" == "1" ]; then
	pushd ./unittests
	#make sure the unit tests can run "python2 xpra ...":
	rm -f ./xpra >& /dev/null
	ln -sf ../scripts/xpra .
	UNITTEST_LOG=`pwd`/unittest.log
	echo "running unit tests (see ${UNITTEST_LOG} - this may take a minute or two)"
	PYTHONPATH=. ./unit/run.py >& ${UNITTEST_LOG}
	if [ "$?" != "0" ]; then
		popd
		echo "ERROR: unit tests failed, see ${UNITTEST_LOG}:"
		tail -n 20 ${UNITTEST_LOG}
		exit 1
	else
		echo "OK"
	fi
	popd
fi

echo
echo "*******************************************************************************"
echo "py2app step:"
PY2APP_LOG=`pwd`/py2app.log
echo "./setup.py py2app ${BUILD_ARGS}"
echo " (see ${PY2APP_LOG} for details - this may take a minute or two)"
python ./setup.py py2app ${BUILD_ARGS} >& ${PY2APP_LOG}
if [ "$?" != "0" ]; then
	echo "ERROR: py2app failed"
	echo
	tail -n 20 ${PY2APP_LOG}
	exit 1
fi
echo "OK"
popd


echo
echo "*******************************************************************************"
echo "Fixing permissions on libpython dylib"
if [ ! -z "${JHBUILD_PREFIX}" ]; then
	chmod 755 "${JHBUILD_PREFIX}/lib/"libpython*.dylib
fi
#avoid error if there is no /etc/pango:
#(which seems to be the case with newer builds)
if [ ! -d "${JHBUILD_PREFIX}/etc/pango" ]; then
	mkdir "${JHBUILD_PREFIX}/etc/pango"
fi

echo
echo "*******************************************************************************"
echo "adding version \"$VERSION\" and revision \"$REVISION$REV_MOD\" to Info.plist files"
svn revert Info.plist
sed -i '' -e "s+%VERSION%+$VERSION+g" "./Info.plist"
sed -i '' -e "s+%REVISION%+$REVISION$REV_MOD+g" "./Info.plist"
sed -i '' -e "s+%BUILDNO%+$BUILDNO+g" "./Info.plist"
if [ "${CLIENT_ONLY}" == "1" ]; then
	sed -i '' -e "s+Xpra+Xpra-Client+g" "./Info.plist"
	sed -i '' -e "s+org.xpra.xpra+org.xpra.xpra-client+g" "./Info.plist"
fi

echo
echo "*******************************************************************************"
echo "calling 'gtk-mac-bundler Xpra.bundle' in `pwd`"
#we have to make sure we use python2 here (not ported yet):
python2 ~/.local/bin/gtk-mac-bundler Xpra.bundle
if [ "$?" != "0" ]; then
	echo "ERROR: gtk-mac-bundler failed"
	exit 1
fi

echo
echo "*******************************************************************************"
echo "unzip site-packages and make python softlink without version number"
pushd ${LIBDIR} || exit 1
ln -sf python* python
cd python
unzip -nq site-packages.zip
rm site-packages.zip
popd

echo
echo "*******************************************************************************"
echo "Add xpra/server/python scripts"
rsync -pltv ./Helpers/* "${HELPERS_DIR}/"
#we dont need the wrapper installed by distutils:
rm ${MACOS_DIR}/Launcher-bin

#ensure that every wrapper has a "python" executable to match:
#(see PythonExecWrapper for why we need this "exec -a" workaround)
python_executable="$RSCDIR/bin/python"
for x in `ls "$HELPERS_DIR" | egrep -v "Python|gst-plugin-scanner"`; do
	#replace underscore with space in actual binary filename:
	target="$RSCDIR/bin/`echo $x | sed 's+_+ +g'`"
	if [ ! -e "$target" ]; then
		#symlinks don't work for us here (osx uses the referent as program name)
		#and hardlinks could cause problems, so we duplicate the file:
		cp "$python_executable" "$target"
	fi
done
#fix for:
# dyld: Library not loaded: @executable_path/../Resources/lib/libgstreamer-1.0.0.dylib
pushd $RSCDIR
ln -sf . Resources
popd

# launcher needs to be in main ("MacOS" dir) since it is launched from the custom Info.plist:
cp ./Helpers/Launcher ${MACOS_DIR}
if [ "${CLIENT_ONLY}" == "1" ]; then
	rm -f "${HELPERS_DIR}/Shadow"
	rm -f "${RSCDIR}/bin/Shadow"
fi
# Add the icon:
cp ./*.icns ${RSCDIR}/

echo
echo "*******************************************************************************"
echo "include all xpra modules found: "
find $PYTHON_PACKAGES/xpra/* -type d -maxdepth 0 -exec basename {} \;
rsync -rpl $PYTHON_PACKAGES/xpra/* $LIBDIR/python/xpra/
echo "removing files that should not be installed in the first place (..)"
for x in "*.c" "*.pyx" "*.pxd" "constants.pxi" "constants.txt"; do
	echo "removing $x:"
	find $LIBDIR/python/xpra/ -name "$x" -print -exec rm "{}" \; | sed "s+$LIBDIR/python/xpra/++g" | xargs -L 1 echo "* "
done
#should be redundant:
if [ "${CLIENT_ONLY}" == "1" ]; then
	for x in "server" "x11"; do
		rm -fr "$LIBDIR/python/xpra/$x"
	done
fi


echo
echo "*******************************************************************************"
echo "Ship default config files"
#the build / install step should have placed them here:
rsync -rplogtv ../src/build/etc/xpra ${RSCDIR}/etc/
if [ "${CLIENT_ONLY}" == "0" ]; then
	#add the launch agent file
	mkdir ${RSCDIR}/LaunchAgents
	cp ./org.xpra.Agent.plist ${RSCDIR}/LaunchAgents/
fi


echo
echo "*******************************************************************************"
echo "Xpra without a tray..."
for app in Xpra_NoDock.app; do
	SUB_APP="${APP_DIR}/Contents/${app}"
	rsync -rplvtog ${app} ${APP_DIR}/Contents/
	ln -sf ../../Resources ${SUB_APP}/Contents/Resources
	ln -sf ../../MacOS ${SUB_APP}/Contents/MacOS
	ln -sf ../../Helpers ${SUB_APP}/Contents/Helpers
done


echo
echo "*******************************************************************************"
echo "Hacks"
#HACKS
echo " * macos notifications API look for Info.plist in the wrong place"
cp ${CONTENTS_DIR}/Info.plist ${RSCDIR}/bin/
#no idea why I have to do this by hand
echo " * add gtk .so"
rsync -rpl $PYTHON_PACKAGES/gtk-2.0/* $LIBDIR/
#add pygtk .py
PYGTK_LIBDIR="$LIBDIR/pygtk/2.0/"
rsync -rpl $PYTHON_PACKAGES/pygtk* $PYGTK_LIBDIR
rsync -rpl $PYTHON_PACKAGES/cairo $PYGTK_LIBDIR
echo " * add all OpenGL"
rsync -rpl $PYTHON_PACKAGES/OpenGL* $LIBDIR/python/
if [ "$STRIP_OPENGL" == "1" ]; then
	#then remove what we know we don't need:
	pushd $LIBDIR/python/OpenGL
	for x in GLE Tk EGL GLES3 GLUT WGL GLX GLES1 GLES2; do
		rm -fr ./$x
		rm -fr ./raw/$x
	done
	popd
fi
echo " * add gobject-introspection (py2app refuses to do it)"
rsync -rpl $PYTHON_PACKAGES/gi $LIBDIR/python/
mkdir $LIBDIR/girepository-1.0
for t in Gst GObject GLib GModule; do
	rsync -rpl ${JHBUILD_PREFIX}/lib/girepository-1.0/$t*typelib $LIBDIR/girepository-1.0/
done
if [ "$STRIP_NUMPY" == "1" ]; then
	echo " * trim numpy"
	pushd $LIBDIR/python/numpy
	rm -fr ./f2py/docs
	for x in core distutils f2py lib linalg ma matrixlib oldnumeric polynomial random testing; do
		rm -fr ./$x/tests
	done
	popd
fi
#unused py2app scripts:
rm ${RSCDIR}/__boot__.py ${RSCDIR}/__error__.sh ${RSCDIR}/client_launcher.py


if [ "$STRIP_SOURCE" == "1" ]; then
	echo "removing py if we have the pyc:"
	#only remove ".py" source if we have a binary ".pyc" for it:
	for x in `find $LIBDIR -name "*.py" -type f`; do
		d="`dirname $x`"
		f="`basename $x`"
		if [ -r "$d/${f}c" ]; then
			#echo "* $x"
			rm "${x}"
		fi
	done
fi


#gst bits expect to find dylibs in Frameworks!?
pushd ${CONTENTS_DIR}
ln -sf Resources/lib Frameworks
pushd Resources/lib
if [ "$STRIP_GSTREAMER_PLUGINS" == "1" ]; then
	echo "removing extra gstreamer dylib deps:"
	for x in basevideo cdda check netbuffer photography rtsp sdp signalprocessor; do
		echo "* removing "$x
		rm libgst${x}*
	done
fi
#only needed with gstreamer 1.x by gstpbutils, get rid of the 0.10 one:
rm libgstvideo-0.10.*
echo "removing extra gstreamer plugins:"
echo " * GStreamer"
GST_PLUGIN_DIR="./gstreamer-1.0"
if [ "$STRIP_GSTREAMER_PLUGINS" == "1" ]; then
	KEEP="./gstreamer-1.0.keep"
	mkdir ${KEEP}
	PLUGINS="app audio coreelements faac faad flac oss osxaudio speex volume vorbis wav lame mad opus ogg gdp isomp4 matroska"
	for x in $PLUGINS; do
		echo "* keeping "$x
		mv ${GST_PLUGIN_DIR}/libgst${x}* ${KEEP}/
	done
	rm -fr ${GST_PLUGIN_DIR}
	mv ${KEEP} ${GST_PLUGIN_DIR}
fi
echo -n "GStreamer plugins shipped: "
ls ${GST_PLUGIN_DIR} | xargs
popd	#${CONTENTS_DIR}
popd	#"Resources/lib"

echo
echo "*******************************************************************************"
echo "Add the manual in HTML format (since we cannot install the man page properly..)"
groff -mandoc -Thtml < ../src/man/xpra.1 > ${RSCDIR}/share/manual.html
groff -mandoc -Thtml < ../src/man/xpra_launcher.1 > ${RSCDIR}/share/launcher-manual.html

echo
echo "*******************************************************************************"
echo "adding version \"$VERSION\" and revision \"$REVISION$REV_MOD\" to Info.plist files"
sed -i '' -e "s+%VERSION%+$VERSION+g" "${CONTENTS_DIR}/Xpra_NoDock.app/Contents/Info.plist"
sed -i '' -e "s+%REVISION%+$REVISION$REV_MOD+g" "${CONTENTS_DIR}/Xpra_NoDock.app/Contents/Info.plist"
sed -i '' -e "s+%BUILDNO%+$BUILDNO+g" "${CONTENTS_DIR}/Xpra_NoDock.app/Contents/Info.plist"
if [ "${CLIENT_ONLY}" == "1" ]; then
	sed -i '' -e "s+Xpra+Xpra-Client+g" "${CONTENTS_DIR}/Xpra_NoDock.app/Contents/Info.plist"
	sed -i '' -e "s+org.xpra.xpra+org.xpra.xpra-client+g" "${CONTENTS_DIR}/Xpra_NoDock.app/Contents/Info.plist"
fi

echo
echo "*******************************************************************************"
echo "Clean unnecessary files"
pwd
ls image
#better do this last ("rsync -C" may omit some files we actually need)
find ./image -name ".svn" | xargs rm -fr
#not sure why these get bundled at all in the first place!
find ./image -name "*.la" -exec rm -f {} \;

echo
echo "*******************************************************************************"
echo "De-duplicate dylibs"
pushd $LIBDIR
for x in `ls *dylib | grep -v libgst | sed 's+[0-9\.]*\.dylib++g' | sed 's+-$++g' | sort -u`; do
	COUNT=`ls *dylib | grep $x | wc -l`
	if [ "${COUNT}" -gt "1" ]; then
		FIRST=`ls $x* | sort -n | head -n 1`
		for f in `ls $x* | grep -v $FIRST`; do
			cmp -s $f $FIRST
			if [ "$?" == "0" ]; then
				echo "(re)symlinking $f to $FIRST"
				rm $f
				ln -sf $FIRST $f
			fi
		done
	fi
done
popd


echo
echo "*******************************************************************************"
echo "copying application image to Desktop"
rsync --delete -rplogt "${APP_DIR}" ~/Desktop/
echo "Done"
echo "*******************************************************************************"
echo

svn revert Info.plist
