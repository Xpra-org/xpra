#!/bin/bash

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

#install build dependencies:
mk-build-deps --install --tool='apt-get -o Debug::pkgProblemResolver=yes --yes' debian/control
rm -f xserver-xorg-video-dummy-build-deps*

if [ `arch` == "aarch64" ]; then
  debuild -us -uc -b --no-lintian
else
  debuild -us -uc -b
fi
ls -la ../xserver-xorg-video-dummy*deb
mv ../xserver-xorg-video-dummy*deb ../xserver-xorg-video-dummy*changes "$REPO_ARCH_PATH"
popd
