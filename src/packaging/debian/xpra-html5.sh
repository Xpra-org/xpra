#!/bin/bash

XPRA_HTML5_TAR_XZ=`ls ../pkgs/xpra-html5-* | sort -V | tail -n 1`
if [ -z "${XPRA_HTML5_TAR_XZ}" ]; then
	echo "no xpra-html5 source found"
	exit 0
fi

dirname=`echo ${XPRA_TAR_XZ} | sed 's+./pkgs/++g' | sed 's/.tar.xz//'`
rm -fr "./${dirname}"
tar -Jxf ${XPRA_HTML5_TAR_XZ}
pushd "./${dirname}"

mk-build-deps --install --tool='apt-get -o Debug::pkgProblemResolver=yes --no-install-recommends --yes' packaging/debian/control
rm -f xpra-html5-build-deps*

python3 ./setup.py deb
mv ./dist/xpra-html5-*.deb $REPO_ARCH_PATH
popd
