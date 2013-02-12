#!/bin/sh

echo "Building and installing"
pushd ../src
./setup.py clean
./setup.py install
popd
./setup.py py2app

PYTHON_PREFIX=`python-config --prefix`
PYTHON_PACKAGES=`ls -d ${PYTHON_PREFIX}/lib/python*/site-packages`

IMAGE_DIR="./image/Xpra.app"
MACOS_DIR="${IMAGE_DIR}/Contents/MacOS"
RSCDIR="${IMAGE_DIR}/Contents/Resources"
HELPERS_DIR="${IMAGE_DIR}/Contents/Helpers"
LIBDIR="${RSCDIR}/lib"
UNAME_ARCH=`uname -p`
ARCH="x86"
if [ "${UNAME_ARCH}" == "powerpc" ]; then
	ARCH="ppc"
fi
export ARCH

echo "Fixing permissions on file we will need to relocate"
if [ ! -z "${JHBUILD_PREFIX}" ]; then
	chmod 755 "${JHBUILD_PREFIX}/lib/"libpython*.dylib
fi

echo "clearing image dir"
rm -fr image
echo "calling 'gtk-mac-bundler Xpra.bundle' in `pwd`"
gtk-mac-bundler Xpra.bundle

echo "unzip site-packages and make python softlink without version number"
pushd ${LIBDIR} || exit 1
ln -sf python* python
cd python
unzip -nq site-packages.zip
rm site-packages.zip
popd


echo "moving pixbuf loaders to a place that will *always* work"
mv ${RSCDIR}/lib/gdk-pixbuf-2.0/*/loaders/* ${RSCDIR}/lib/
echo "remove now empty loaders dir"
rmdir ${RSCDIR}/lib/gdk-pixbuf-2.0/2.10.0/loaders
rmdir ${RSCDIR}/lib/gdk-pixbuf-2.0/2.10.0
rmdir ${RSCDIR}/lib/gdk-pixbuf-2.0
echo "fix gdk-pixbuf.loaders"
LOADERS="${RSCDIR}/etc/gtk-2.0/gdk-pixbuf.loaders"
sed -i -e 's+@executable_path/../Resources/lib/gdk-pixbuf-2.0/.*/loaders/++g' "${LOADERS}"

echo "Add xpra/server/python scripts"
cp ./Python "${HELPERS_DIR}/"
cp ./xpra "${HELPERS_DIR}/"
cp ./SSH_ASKPASS "${HELPERS_DIR}/"
# copy "python" as "xpra" and "Xpra_Launcher" so we can have a process that is not called "python"...
cp "${RSCDIR}/bin/python" "${RSCDIR}/bin/Xpra"
cp "${RSCDIR}/bin/python" "${RSCDIR}/bin/Xpra_Launcher"
#we dont need the wrapper installed by distutils:
rm "${MACOS_DIR}/Xpra_Launcher-bin"

# launcher needs to be in main ("MacOS" dir) since it is launched from the custom Info.plist:
cp Xpra_Launcher ${MACOS_DIR}
# Add the icon:
cp ./*.icns ${RSCDIR}/

# Add Xpra share (for icons)
rsync -rplog $XDG_DATA_DIRS/xpra/* ${RSCDIR}/share/xpra/

echo "Hacks"
#HACKS
#no idea why I have to do this by hand
#add gtk .so
rsync -rpl $PYTHON_PACKAGES/gtk-2.0/* $LIBDIR/
#add pygtk .py
PYGTK_LIBDIR="$LIBDIR/pygtk/2.0/"
rsync -rpl $PYTHON_PACKAGES/pygtk* $PYGTK_LIBDIR
rsync -rpl $PYTHON_PACKAGES/cairo $PYGTK_LIBDIR

echo "Clean unnecessary files"
pwd
ls image
#better do this last ("rsync -C" may omit some files we actually need)
find ./image -name ".svn" | xargs rm -fr
#not sure why these get bundled at all in the first place!
find ./image -name "*.la" -exec rm -f {} \;

echo "copying application image to Desktop"
rsync -rplogt "${IMAGE_DIR}" ~/Desktop/
