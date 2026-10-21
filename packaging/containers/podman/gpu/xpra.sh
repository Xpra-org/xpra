#!/bin/bash
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

set -e

# the 'xpra' image from the 'split' pod, with the codecs and drivers for hardware accelerated video encoding:
BASE_IMAGE="${BASE_IMAGE:-xpra}"
IMAGE_NAME="${IMAGE_NAME:-xpra-gpu}"
CONTAINER="${IMAGE_NAME}-build"
# the GPU codecs to install:
# * `nvidia`: NVENC, the driver libraries are injected by the NVIDIA Container Toolkit when the container starts
# * `intel`: VA-API and oneVPL drivers for Intel GPUs
# * `mesa`: VA-API drivers for AMD (and other) GPUs, with H.264 and HEVC support from RPM Fusion
# * `amd`: AMF, which requires AMD's proprietary encoder library (`libamdenc-amdgpu-pro`)
GPU_CODECS="${GPU_CODECS:-nvidia intel mesa}"

run () {
  buildah run $CONTAINER "$@"
}

install () {
  run dnf install -y --setopt=install_weak_deps=False "$@"
}

if ! buildah inspect -t image "${BASE_IMAGE}" &> /dev/null; then
  (cd "$(dirname "$0")/../split" && bash ./xpra.sh)
fi
buildah rm $CONTAINER &> /dev/null || true
buildah rmi -f "${IMAGE_NAME}" &> /dev/null || true
buildah from --name $CONTAINER "${BASE_IMAGE}"
# the GPU codecs must be the same version as the other codecs already installed,
# the repository may already have newer builds:
XPRA_EVR=$(run rpm -q --qf '%{epoch}:%{version}-%{release}' xpra-codecs)

for codec in ${GPU_CODECS}; do
  case "${codec}" in
    nvidia)
      # `python3-pycuda` builds older than 2026.1-2 are missing their dependencies:
      install "xpra-codecs-nvidia-${XPRA_EVR}" python3-numpy
      ;;
    intel)
      install libva-intel-media-driver intel-vpl-gpu-rt
      ;;
    mesa)
      # the Fedora package does not include the patent encumbered codecs:
      run sh -c "if rpm -q mesa-va-drivers > /dev/null; then dnf swap -y mesa-va-drivers mesa-va-drivers-freeworld; else dnf install -y --setopt=install_weak_deps=False mesa-va-drivers-freeworld; fi"
      ;;
    amd)
      install "xpra-codecs-amd-${XPRA_EVR}"
      ;;
    *)
      echo "unknown GPU codec '${codec}'" >&2
      exit 1
      ;;
  esac
done
run sh -c "rm -fr /var/cache/*dnf* /var/log/dnf*.log*"

buildah commit $CONTAINER "${IMAGE_NAME}"
buildah rm $CONTAINER
