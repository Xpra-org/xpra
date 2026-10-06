#!/bin/bash
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

set -e

DISTRO="${DISTRO:-fedora}"
RELEASE="${RELEASE:-latest}"
IMAGE_NAME="xpra"
CONTAINER="$DISTRO-$RELEASE-$IMAGE_NAME"
CLEAN="${CLEAN:-1}"
REPO="${REPO:-xpra-beta}"
XDISPLAY="${XDISPLAY:-:10}"
SEAMLESS="${SEAMLESS:-1}"
PORT="${PORT:-10000}"
AUDIO="${AUDIO:-1}"
CODECS="${CODECS:-1}"
TOOLS="${TOOLS:-0}"
TRIM="${TRIM:-0}"
TARGET_USER="${TARGET_USER:-xpra-user}"
TARGET_PASSWORD="${TARGET_PASSWORD:-thepassword}"
# the "pulse" group only exists when pulseaudio is installed:
if [ "${AUDIO}" == "1" ]; then
  TARGET_USER_GROUPS="${TARGET_USER_GROUPS:-audio,pulse,video,xpra}"
else
  TARGET_USER_GROUPS="${TARGET_USER_GROUPS:-audio,video,xpra}"
fi
TARGET_UID="${TARGET_UID:-1000}"
TARGET_GID="${TARGET_GID:-1000}"
DEBUG="${DEBUG:-none}"

run () {
  buildah run $CONTAINER "$@"
}

copy () {
  buildah copy $CONTAINER "$@"
}

install () {
  if [ "${TRIM}" == "1" ]; then
    run dnf install -y --setopt=install_weak_deps=False "$@"
  else
    run dnf install -y "$@"
  fi
}

if [ "$1" == "update" ]; then
  run dnf update --refresh -y
else
  if [ "${CLEAN}" == "1" ]; then
    buildah rm $CONTAINER || true
    buildah rmi -f $IMAGE_NAME || true
    buildah from --pull=newer --name $CONTAINER $DISTRO:$RELEASE
  fi
  # the distribution's major version number, ie: "latest" -> "44"
  VERSION_ID=$(run sh -c '. /etc/os-release;echo ${VERSION_ID%%.*}')
  if [ "${DISTRO}" == "fedora" ]; then
    RPMFUSION_DIR="fedora"
    REPO_DIR="Fedora"
    # python3-uvloop is no longer available as of Fedora 44:
    EXTRA_PACKAGES="python3-aioquic python3-zeroconf"
  else
    # almalinux, rockylinux: dependencies come from EPEL and CRB
    install -y epel-release dnf-plugins-core
    run dnf config-manager --set-enabled crb
    RPMFUSION_DIR="el"
    REPO_DIR="${DISTRO}"
    if [ "${VERSION_ID}" -ge 10 ]; then
      EXTRA_PACKAGES="python3-uvloop python3-aioquic"
    else
      EXTRA_PACKAGES=""
    fi
  fi
  install -y "https://download1.rpmfusion.org/free/${RPMFUSION_DIR}/rpmfusion-free-release-${VERSION_ID}.noarch.rpm"
  run dnf update -y
  install -y wget "--setopt=install_weak_deps=False"
  run wget -O "/etc/yum.repos.d/${REPO}.repo" "https://raw.githubusercontent.com/Xpra-org/xpra/master/packaging/repos/${REPO_DIR}/${REPO}.repo"
  # `xpra-client` provides `xpra run`, which can be used as exec wrapper to start the commands in another container:
  install -y xpra-filesystem xpra-server xpra-client xpra-x11 xpra-html5 python3-pyxdg ${EXTRA_PACKAGES} dbus-daemon dbus-x11 dbus-tools desktop-backgrounds-compat libjxl-utils python3-cups cups-filters cups-pdf --setopt=install_weak_deps=False
  if [ "${AUDIO}" == "1" ]; then
    install -y xpra-audio-server
  fi
  if [ "${CODECS}" == "1" ]; then
    install -y xpra-codecs
  fi

  if [ "${TOOLS}" == "1" ]; then
    install -y strace xterm xclip net-tools lsof xpra-client socat mesa-demos xdpyinfo VirtualGL pavucontrol --setopt=install_weak_deps=False
  fi
  # the package scripts only cache the SVG menu icons available when xpra is installed,
  # cache them again now that everything is installed, the home directory may not be writable at runtime:
  run xpra menu-cache

  run userdel -r "${TARGET_USER}" || true
  run groupadd -r -g "${TARGET_GID}" "${TARGET_USER}"
  run adduser -u "${TARGET_UID}" -g "${TARGET_GID}" --shell /bin/bash "${TARGET_USER}"
  run usermod -aG "${TARGET_USER_GROUPS}" "${TARGET_USER}"
  run sh -c "echo \"${TARGET_USER}:${TARGET_PASSWORD}\" | chpasswd"

  # dbus setup
  # dbus falls back to '/etc/machine-id' when '/var/lib/dbus/machine-id' does not exist,
  # the base image ships an empty placeholder file, which 'dbus-uuidgen --ensure' rejects:
  run sh -c "test -s /etc/machine-id || rm -f /etc/machine-id"
  run dbus-uuidgen --ensure=/etc/machine-id

  # in a pod, the shared '/run' volume is populated from this image,
  # so the user's runtime directory already exists when the other containers start,
  # even before xpra has created it: ie: for the session bus started by the 'apps' container
  run mkdir -p -m 0700 "/run/user/${TARGET_UID}"
  run chown "${TARGET_UID}:${TARGET_GID}" "/run/user/${TARGET_UID}"
  # when xpra starts the X server, the X11 socket directory may be shared with other containers using a volume,
  # which is populated from this image, so it must be writable by the X server running as the target user:
  run mkdir -m 1777 /tmp/.X11-unix
fi

# just use the system-wide ssl certificate:
run sh -c "chmod 644 /etc/xpra/ssl/*.pem"

# save space:
# (`buildah run` does not use a shell, so we need one to expand the globs)
run sh -c "rm -fr /var/cache/*dnf* /var/log/dnf*.log* /var/log/README /var/yp /var/preserve /var/opt /var/nis /var/log/journal /var/log/private /var/local /var/lib/systemd /var/lib/selinux/tmp /var/games /var/kerberos /var/db"

if [ "${SEAMLESS}" == "1" ]; then
  MODE="seamless"
else
  MODE="desktop"
fi
# only use socket directories in '/run', the home directory may not be writable (ie: `--read-only`).
# the entrypoint runs in a shell, so `USE_DISPLAY` can be overriden when starting the container,
# ie: `--env USE_DISPLAY=yes` to only use the display from the 'xvfb' container,
# with `--env XPRA_VFB_WAIT=30` to wait up to 30 seconds for it to become available.
# likewise, `--env DBUS=wait` connects to a session bus started by another container
# at '/run/user/${TARGET_UID}/bus', instead of running without dbus.
# `--env EXEC_WRAPPER=...` starts the commands using a wrapper,
# ie: `xpra run socket:///run/user/${TARGET_UID}/runner/socket --` to start them in the container running the 'xpra runner',
# the OpenGL probe also goes through the wrapper, `--env OPENGL=noprobe` skips it.
# the session bus may be owned by another container, so do not expose the xpra server's control interface on it (`--dbus-control=no`),
# which would let any process connected to the bus start commands or change the server settings:
buildah config --env USE_DISPLAY=auto $CONTAINER
buildah config --env DBUS=no $CONTAINER
buildah config --env EXEC_WRAPPER= $CONTAINER
buildah config --env OPENGL=probe $CONTAINER
buildah config --entrypoint "/usr/bin/xpra ${MODE} --uid ${TARGET_UID} --gid ${TARGET_GID} ${XDISPLAY} --bind-quic=0.0.0.0:${PORT} --bind-tcp=0.0.0.0:${PORT} --no-daemon --use-display=\${USE_DISPLAY} --socket-dirs=/run/user/${TARGET_UID}/xpra --socket-dirs=/run/xpra --dbus=\${DBUS} --dbus-control=no \"--exec-wrapper=\${EXEC_WRAPPER}\" --opengl=\${OPENGL} --system-tray=no --ssh-upgrade=no --env=XPRA_POWER_EVENTS=0 -d ${DEBUG}" $CONTAINER
buildah commit $CONTAINER $IMAGE_NAME
