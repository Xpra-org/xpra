#!/bin/bash

if [ ! -d "./image/Xpra.app" ]; then
	echo "./image/Xpra.app is missing - cannot continue"
	exit 1
fi

#figure out the version / revision
export PYTHONPATH="image/Xpra.app/Contents/Resources/lib/python/"
VERSION=`python -c "from xpra import __version__;import sys;sys.stdout.write(__version__)"`
#prefer revision directly from svn:
REVISION=`svnversion -n .. | awk -F: '{print $2}'`
if [ -z "${REVISION}" ]; then
	#fallback to using revision recorded in build info
	REVISION=`python -c "from xpra import src_info;import sys;sys.stdout.write(str(src_info.REVISION))"`
fi
PKG_FILENAME="Xpra-$VERSION-r$REVISION.pkg"
rm -f ./image/$PKG_FILENAME >& /dev/null
echo "Making $PKG_FILENAME"

#create directory structure:
rm -fr ./image/flat ./image/root
mkdir -p ./image/flat/base.pkg ./image/flat/Resources/en.lproj
mkdir -p ./image/root/Applications

mv ./image/Xpra.app ./image/root/Applications/
#man page:
mkdir -p ./image/root/usr/share/man/man1
for x in xpra xpra_launcher; do
	gzip -c ../src/man/$x.1 > ./image/root/usr/share/man/man1/$x.1.gz
done
#add cups backend:
mkdir -p ./image/root/usr/libexec/cups/backend/
cp ../src/cups/xpraforwarder ./image/root/usr/libexec/cups/backend/
chmod 700 ./image/root/usr/libexec/cups/backend

pushd ./image/root >& /dev/null
find . | cpio -o --format odc --owner 0:80 | gzip -c > ../flat/base.pkg/Payload
popd >& /dev/null

FILECOUNT=`find ./image/root | wc -l`
DISKUSAGE=`du -sk ./image/root`

#add the postinstall fix script (cups backend and shortcuts)
mkdir ./image/scripts
cp postinstall ./image/scripts/
chmod +x ./image/scripts/postinstall
pushd ./image/scripts >& /dev/null
find . | cpio -o --format odc --owner 0:80 | gzip -c > ../flat/base.pkg/Scripts
popd >& /dev/null

mkbom -u 0 -g 80 ./image/root ./image/flat/base.pkg/Bom

cat > ./image/flat/base.pkg/PackageInfo << EOF
<pkg-info format-version="2" identifier="org.xpra.pkg" version="$VERSION" install-location="/" auth="root">
  <payload installKBytes="$DISKUSAGE" numberOfFiles="$FILECOUNT"/>
  <scripts>
    <postinstall file="./postinstall"/>
  </scripts>
  <bundle-version>
    <bundle id="org.xpra.Xpra" CFBundleIdentifier="Xpra" path="./Applications/Xpra.app" CFBundleVersion="1.3.0"/>
  </bundle-version>
</pkg-info>
EOF

cat > ./image/flat/Distribution << EOF
<?xml version="1.0" encoding="utf-8"?>
<installer-script minSpecVersion="1.000000" authoringTool="com.apple.PackageMaker" authoringToolVersion="3.0.3" authoringToolBuild="174">
    <title>Xpra $VERSION</title>
    <options customize="never" allow-external-scripts="no"/>
    <domains enable_anywhere="true"/>
    <installation-check script="pm_install_check();"/>
    <script>function pm_install_check() {
  if(!(system.compareVersions(system.version.ProductVersion,'10.5') >= 0)) {
    my.result.title = 'Failure';
    my.result.message = 'You need at least Mac OS X 10.5 to install Xpra.';
    my.result.type = 'Fatal';
    return false;
  }
  return true;
}
    </script>
    <background file="background.png" alignment="bottomleft" scaling="none"/>
    <license file="GPL.rtf"/>
    <choices-outline>
        <line choice="choice1"/>
    </choices-outline>
    <choice id="choice1" title="base">
        <pkg-ref id="org.xpra.pkg"/>
    </choice>
    <pkg-ref id="org.xpra.pkg" installKBytes="$DISKUSAGE" version="$VERSION" auth="Root">#base.pkg</pkg-ref>
</installer-script>
EOF

#add license and background files to image:
cp background.png GPL.rtf ./image/flat/Resources/en.lproj/

pushd ./image/flat >& /dev/null
xar --compression none -cf "../$PKG_FILENAME" *
popd >& /dev/null

#clean temporary build directories
rm -fr ./image/flat ./image/root ./image/scripts

#show resulting file and copy it to the desktop
du -sm ./image/$PKG_FILENAME
cp ./image/$PKG_FILENAME ~/Desktop/
