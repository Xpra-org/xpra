#!/bin/bash

MACOS_SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd "${MACOS_SCRIPT_DIR}" || exit 1

LIGHT="${LIGHT:=0}"
if [ "${LIGHT}" == "1" ]; then
  APP_NAME="Xpra-Light"
else
  APP_NAME="Xpra"
fi
APP_DIR="./image/${APP_NAME}.app"

echo
echo "*******************************************************************************"
if [ ! -d "${APP_DIR}" ]; then
	echo "${APP_DIR} is missing - cannot continue"
	exit 1
fi

#get the version and build info from the python build records:
export PYTHONPATH="${APP_DIR}/Contents/Frameworks/python/"
PYTHON="${PYTHON:=python}"
VERSION=$(${PYTHON} -c "from xpra import __version__;import sys;sys.stdout.write(__version__)")
REVISION=$(${PYTHON} -c "from xpra import src_info;import sys;sys.stdout.write(str(src_info.REVISION))")
REV_MOD=$(${PYTHON} -c "from xpra import src_info;import sys;sys.stdout.write(['','M'][src_info.LOCAL_MODIFICATIONS>0])")
BUILD_INFO="${BUILD_INFO}-$(uname -m)"

PKG_FILENAME="$APP_NAME$BUILD_INFO-$VERSION-r$REVISION$REV_MOD.pkg"
rm -f "./image/${PKG_FILENAME}" >& /dev/null
echo "Making ${PKG_FILENAME}"

#create directory structure:
rm -fr "./image/flat" "./image/root" "./image/scripts"
mkdir -p "./image/flat/Resources/en.lproj"
mkdir -p "./image/root/Applications"
ditto "${APP_DIR}" "./image/root/Applications/${APP_NAME}.app"

#add launchd agent:
mkdir -p "./image/root/Library/LaunchAgents/"
cp "./org.xpra.Agent.plist" "./image/root/Library/LaunchAgents/"

#add the postinstall fix script (cups backend and shortcuts)
mkdir ./image/scripts
cp postinstall ./image/scripts/
chmod +x ./image/scripts/postinstall

# always install into /Applications,
# never "upgrade" another copy of the app found elsewhere (ie: on the Desktop):
pkgbuild --analyze --root "./image/root" "./image/flat/components.plist"
i=0
while plutil -extract "${i}" raw "./image/flat/components.plist" > /dev/null 2>&1; do
	plutil -replace "${i}.BundleIsRelocatable" -bool NO "./image/flat/components.plist"
	i=$((i+1))
done

# use pkgbuild rather than cpio for the payload,
# so the extended attributes holding the signatures of scripts are preserved:
pkgbuild --root "./image/root" --component-plist "./image/flat/components.plist" \
	--scripts "./image/scripts" \
	--identifier "org.xpra.pkg" --version "$VERSION" \
	--install-location "/" --ownership recommended \
	"./image/flat/base.pkg" || exit 1

cat > ./image/flat/Distribution << EOF
<?xml version="1.0" encoding="utf-8"?>
<installer-script minSpecVersion="2">
	<title>${APP_NAME} $VERSION</title>
	<allowed-os-versions>
		<os-version min="10.12" />
	</allowed-os-versions>
	<options customize="never" require-scripts="false" allow-external-scripts="no"/>
	<domains enable_anywhere="true"/>
	<background file="background.png" alignment="bottomleft" scaling="none"/>
	<license file="GPL.rtf"/>
	<choices-outline>
		<line choice="choice1"/>
	</choices-outline>
	<choice id="choice1" title="base">
		<pkg-ref id="org.xpra.pkg"/>
	</choice>
	<pkg-ref id="org.xpra.pkg" version="$VERSION" auth="Root">base.pkg</pkg-ref>
</installer-script>
EOF

#add license and background files to image:
cp "background.png" "GPL.rtf" "./image/flat/Resources/en.lproj/"

productbuild --distribution "./image/flat/Distribution" \
	--resources "./image/flat/Resources" --package-path "./image/flat" \
	"./image/${PKG_FILENAME}" || exit 1

#clean temporary build directories
rm -fr "./image/flat" "./image/root" "./image/scripts"

#show resulting file and copy it to the desktop
du -sm "./image/$PKG_FILENAME"
ditto "./image/$PKG_FILENAME" "${HOME}/Desktop/"

echo "Done PKG"
echo "*******************************************************************************"
echo
