#!/bin/bash -e
docker build -f Dockerfile.centos7 -t xprabuild-centos7:latest .
docker run -it \
-e XPRA_REVISION=$( svnversion ) \
--mount type=bind,source="${PWD}/../../../",target=/home/builder/mount \
xprabuild-centos7:latest
