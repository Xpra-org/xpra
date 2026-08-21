#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -z "${REPO_ARCH_PATH}" ]; then
	REPO_ARCH_PATH="`pwd`/../repo"
fi

DUMMY_TAR_XZ=`ls ../pkgs/xf86-video-dummy-*.tar.xz`
dirname=`echo ${DUMMY_TAR_XZ} | sed 's+../pkgs/++g' | sed 's/.tar.xz//' | sort -V | tail -n 1`
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
${TAR} -Jxf ${DUMMY_TAR_XZ}
pushd "./${dirname}"
ln -sf ../xserver-xorg-video-dummy ./debian

# Use the local tar wrapper for dpkg and apt while building under old qemu.
if command -v bsdtar > /dev/null; then
	export PATH="${SCRIPT_DIR}:${PATH}"
fi

#install build dependencies:
#Avoid mk-build-deps: its temporary .deb invokes GNU tar, which fails with
#the older arm64 qemu emulation used by the builder.
BUILD_DEPS=$(dpkg-parsecontrol -sBuild-Depends debian/control)
if ! apt-get -o Debug::pkgProblemResolver=yes --yes satisfy "$BUILD_DEPS"; then
	echo "failed to install xserver-xorg-video-dummy build dependencies" >&2
	exit 1
fi

if [ `arch` == "aarch64" ]; then
  debuild -us -uc -b --no-lintian
else
  debuild -us -uc -b
fi
ls -la ../xserver-xorg-video-dummy*deb
mv ../xserver-xorg-video-dummy*deb ../xserver-xorg-video-dummy*changes "$REPO_ARCH_PATH"
popd
