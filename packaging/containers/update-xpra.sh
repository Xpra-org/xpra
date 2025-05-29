#!/bin/bash
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

set -e

# update `xpra` container:
DISTRO="${DISTRO:-fedora}"
RELEASE="${RELEASE:-42}"
IMAGE_NAME="xpra"
CONTAINER="$DISTRO-$RELEASE-$IMAGE_NAME"
IMAGE_NAME="xpra"
buildah run "$CONTAINER" dnf update --refresh -y
buildah commit "$CONTAINER" $IMAGE_NAME
