#!/bin/bash

VERSION=$1
if [ -z "${VERSION}" ]; then
	echo "usage: ./fakeXinerama-snapshot.sh VERSION"
	exit 1
fi
DIR="libfakeXinerama-${VERSION}"
rm -fr "${DIR}"
mkdir -p "${DIR}"

cp "./src/fakexinerama/fakeXinerama.c" "${DIR}/"
cp "./src/fakexinerama/README.TXT" "${DIR}/"
cp "./src/fakexinerama/LICENSE" "${DIR}/"

tar -jcf ${DIR}.tar.bz2 ${DIR}
tar -Jcf ${DIR}.tar.xz ${DIR}
for a in ${DIR}.tar.bz2 ${DIR}.tar.xz; do
	md5sum ${a} > ${a}.md5
	sha1sum ${a} > ${a}.sha
done
ls -al ${DIR}.tar.*
rm -fr "${DIR}"
