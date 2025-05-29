#!/bin/bash
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

set -e

# update `apps` container:
DISTRO="${DISTRO:-ubuntu}"
RELEASE="${RELEASE:-plucky}"
IMAGE_NAME="apps"
CONTAINER="$DISTRO-$RELEASE-$IMAGE_NAME"
buildah run "$CONTAINER" apt-get update
buildah run "$CONTAINER" apt-get dist-upgrade -y
buildah commit $CONTAINER $IMAGE_NAME
