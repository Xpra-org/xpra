#!/bin/bash

VERSION=$1
if [ -z "${VERSION}" ]; then
	VERSION=`PYTHONPATH="./src" python -c "from xpra.codecs.webm import __VERSION__; print(__VERSION__)"`
fi
DIR="python-webm-${VERSION}"
rm -fr "${DIR}"
mkdir -p "${DIR}/webm"

cp "./src/xpra/codecs/webm/"*.py "${DIR}/webm/"
cp "./src/xpra/codecs/webm/README" "${DIR}/"
cp "./src/xpra/codecs/webm/LICENSE" "${DIR}/"
cp -apr "./src/tests/webm" "${DIR}/webm/tests"

tar -jcf ${DIR}.tar.bz2 ${DIR}
tar -Jcf ${DIR}.tar.xz ${DIR}
for a in ${DIR}.tar.bz2 ${DIR}.tar.xz; do
	md5sum ${a} > ${a}.md5
	sha1sum ${a} > ${a}.sha
done
ls -al ${DIR}.tar.*
rm -fr "${DIR}"
