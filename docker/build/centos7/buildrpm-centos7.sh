#!/bin/bash -e

if [ ! -f "/.dockerenv" ]; then
    echo "not a docker container exiting"
    exit
fi

if [ -z "${CI_PIPELINE_ID}" ]; then
    export CI_PIPELINE_ID=0
fi

RPMDIR="${HOME}/rpmbuild"
SRCDIR="${HOME}/rpmbuild/SOURCES"
XPRASRC="${HOME}/mount"

echo "Working in ${RPMDIR}"
echo "Source in ${SRCDIR}"
echo "Xpra Source in ${XPRASRC}"

SFNAME="$( dirname "$0" )/specs.txt"
#copy patches
cp -v ${XPRASRC}/rpmbuild/*.patch ${SRCDIR}

#loop through specs.txt for building
while read P; do
    SPECFNAME="${P}.spec"
    echo "Building ${SPECFNAME}"
    pushd ${SRCDIR}

    #clean up a bit
    rm -f ${P}*.tar.bz2 \
    ${P}*.tar.gz \
    ${P}*.tar.xz

    #download source and install build deps then build it
    spectool -g ${XPRASRC}/rpmbuild/${SPECFNAME}
    sudo yum-builddep -y -q -e0 ${XPRASRC}/rpmbuild/${SPECFNAME}
    rpmbuild -ba ${XPRASRC}/rpmbuild/${SPECFNAME}

    #install rpms when we are done
    sudo yum install -y -q -e0 ${RPMDIR}/RPMS/*/${P}-*.rpm \
    ${RPMDIR}/RPMS/*/python*-${P}-*.rpm \
    ${RPMDIR}/RPMS/*/*${P}*devel*.rpm \
    ${RPMDIR}/RPMS/*/python*-$( echo "${P}" | cut -f2 -d- )-*.rpm

    popd
done < ${SFNAME}

#build xpra
sudo yum-builddep -y -q -e0 rpmbuild/xpra.spec

#Install depends for xpra for unittests
#sudo yum -y -q -e0 install python-pillow
sudo yum -y -q -e0 install xorg-x11-server-utils

echo "Building RPM in $(pwd)"

#Clean version info before building
pushd src
./setup.py clean
svnrevision=${XPRA_REVISION}
popd

#Make src snapshot then copy and build
./scripts/make-src-snapshot.sh
cp xpra*.tar.bz2 /home/builder/rpmbuild/SOURCES
cp src/patches/* /home/builder/rpmbuild/SOURCES

#build and turn cuda off for now
rpmbuild -bb \
--define "with_cuda 0" \
--define "revision_no ${svnrevision}" \
rpmbuild/xpra.spec

#copy rpms to mounted dir so we get them outside the container
pwd
OUTDIR="./docker/out/CentOS/7.6/x86_64"
mkdir -p ${OUTDIR}
cp -v /home/builder/rpmbuild/RPMS/x86_64/*.rpm ${OUTDIR}
