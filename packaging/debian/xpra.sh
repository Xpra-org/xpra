#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

eval `dpkg-architecture -s`

if [ -z "${REPO_ARCH_PATH}" ]; then
	REPO_ARCH_PATH="`pwd`/../repo"
fi

#find the latest version we can build:
XPRA_TAR_XZ=`ls ../pkgs/xpra-7.0.*tar.xz | grep -v html5 | sort -V | tail -n 1`
if [ -z "${XPRA_TAR_XZ}" ]; then
	echo "no xpra source found"
	exit 0
fi

dirname=`echo ${XPRA_TAR_XZ} | sed 's+../pkgs/++g' | sed 's/.tar.xz//'`
rm -fr "./${dirname}"
#GNU tar 1.35 and later use the `openat2` syscall for extraction, which some
#versions of qemu don't implement - extraction then fails with
#"Cannot open: Function not implemented", see:
#https://github.com/Xpra-org/repo-build-scripts/issues/15
#bsdtar doesn't use `openat2`, so prefer it when it is installed
#(unlike GNU tar, it restores xattrs, ACLs and file flags unless told not to):
TAR="tar"
if command -v bsdtar > /dev/null; then
	TAR="bsdtar --no-xattrs --no-acls --no-fflags"
fi
${TAR} -Jxf ${XPRA_TAR_XZ}
pushd "./${dirname}"
ln -sf packaging/debian/xpra ./debian

# Use the local tar wrapper for dpkg and apt while building under old qemu.
if command -v bsdtar > /dev/null; then
	export PATH="${SCRIPT_DIR}:${PATH}"
fi

#the control file has a few distribution specific entries
#ie:
# '#buster:         ,libturbojpeg0'
#we uncomment the lines for this specific distro (by adding a new line after "#$DISTRO:"):
#first figure out the distribution's codename:
CODENAME=`lsb_release -c | awk '{print $2}'`
#ie: CODENAME=bionic
perl -i.bak -pe "s/#${CODENAME}:/#${CODENAME}:\\n/g" debian/control

#install build dependencies:
#Do not use mk-build-deps here: it creates a temporary .deb via dpkg-deb,
#which needs GNU tar and cannot run under the older arm64 qemu emulation.
#The build image does not include dpkg-parsecontrol, so extract this field
#directly.  The distro-specific comments have already been expanded above.
BUILD_DEPS=$(awk '
  /^Build-Depends:[[:space:]]*/ { in_deps=1; sub(/^Build-Depends:[[:space:]]*/, ""); print; next }
  in_deps && /^[[:space:]]*#/ { next }
  in_deps && /^[[:space:]]/ { sub(/^[[:space:]]*/, ""); print; next }
  in_deps { exit }
' debian/control | tr '\n' ' ')
if ! apt-get -o Debug::pkgProblemResolver=yes --no-install-recommends --yes satisfy "$BUILD_DEPS"; then
	echo "failed to install Xpra build dependencies" >&2
	exit 1
fi

#install latest cython since the one Debian / Ubuntu tends to be out of date:
DEBIAN_FRONTEND=noninteractive apt-get -y install python3-pip
DEBIAN_FRONTEND=noninteractive apt-get -y remove cython3
PIP_BREAK_SYSTEM_PACKAGES=1 pip3 install cython

#add revision to version number to changelog
REVISION=`PYTHONPATH=. python3 -c 'from xpra.src_info import REVISION;print(REVISION)'`
if [ "${REVISION}" == "" ]; then
	echo "cannot build: xpra revision not found in src_info"
	exit 1
fi
head -n 1 "./debian/changelog" | sed "s/-/-r${REVISION}-/g" > "debian/changelog.new"
tail -n +2 "./debian/changelog" >> "./debian/changelog.new"
mv "./debian/changelog.new" "./debian/changelog"
head -n 10 "./debian/changelog"

#now figure out if this package is already in the repository:
CHANGELOG_VERSION=`head -n 1 "./debian/changelog" | sed 's/.*(//g' | sed 's/).*//g'`
DEB_FILENAME="xpra-${CHANGELOG_VERSION}_$DEB_BUILD_ARCH.deb"
MATCH=`find $REPO_ARCH_PATH/ -name "${DEB_FILENAME}" | wc -l`
if [ "$MATCH" != "0" ]; then
	echo "package already exists"
else
  BUILD_TYPE="DEB"
	if [ `arch` == "aarch64" ]; then
		debuild --no-lintian -us -uc -b
	else
		debuild -us -uc -b
	fi
	ls -la ../xpra*deb
	cp ../xpra*deb ../xpra*changes "$REPO_ARCH_PATH"
fi
popd
