#!/bin/bash
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

set -e

DISTRO="${DISTRO:-fedora}"
RELEASE="${RELEASE:-latest}"
IMAGE_NAME="${IMAGE_NAME:-apps}"
CONTAINER="$DISTRO-$RELEASE-$IMAGE_NAME"
CLEAN="${CLEAN:-1}"
REPO="${REPO:-xpra-beta}"
TRIM="${TRIM:-1}"
XDISPLAY="${XDISPLAY:-:10}"
SEAMLESS="${SEAMLESS:-1}"
TOOLS="${TOOLS:-0}"
FILE_MANAGER="${FILE_MANAGER:-nemo}"
XPRA="${XPRA:-0}"
APPS="${APPS:-libreoffice lxterminal vlc gimp}"
FIREFOX="${FIREFOX:-1}"
TARGET_USER="${TARGET_USER:-desktop-user}"
TARGET_GROUP="${TARGET_GROUP:-desktop-user}"
TARGET_PASSWORD="${TARGET_PASSWORD:-thepassword}"
TARGET_USER_GROUPS="${TARGET_USER_GROUPS:-audio,pulse,video}"
TARGET_UID="${TARGET_UID:-1000}"
TARGET_GID="${TARGET_GID:-1000}"
# how long to wait for the pulseaudio server started by xpra, in seconds (0 to disable):
PULSEAUDIO_WAIT="${PULSEAUDIO_WAIT:-10}"
TIMEZONE="${TIMEZONE:-Europe/London}"
DESKTOP="${DESKTOP:-lxde}"
if [ "${DESKTOP}" == "xfce" ]; then
  DESKTOP="xfce4"
fi
# LANG="${LANG:-C}"

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
  run dnf update -y

  run ln -sf "/usr/share/zoneinfo/$TIMEZONE" /etc/localtime

  # add xpra repo:
  install wget
  run dnf config-manager setopt fedora-cisco-openh264.enabled=1
  # the distribution's major version number, ie: "latest" -> "44"
  VERSION_ID=$(run sh -c '. /etc/os-release;echo ${VERSION_ID%%.*}')
  install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-${VERSION_ID}.noarch.rpm https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-${VERSION_ID}.noarch.rpm
  run wget -O "/etc/yum.repos.d/${REPO}.repo" "https://raw.githubusercontent.com/Xpra-org/xpra/master/packaging/repos/Fedora/${REPO}.repo"

  if [ "${FIREFOX}" == "1" ]; then
    install firefox
  fi

  if [ "${XPRA}" == "1" ]; then
    install xpra-server xpra-client-gtk3 xorg-x11-drv-dummy xpra-codecs xpra-audio-server xpra-codecs-extras xpra-x11 xpra-html5
  fi

  if [ "${TOOLS}" == "1" ]; then
    # add some applications:
    install xterm strace net-tools iputils
    # toys useful for testing video encoders:
    install glx-utils VirtualGL
    # xrandr, xdpyinfo etc:
    install xprop xrandr xdpyinfo xdriinfo xwininfo vulkan-tools
  fi

  # Fedora defaults to 'dbus-broker', which needs systemd to start a session bus:
  install dbus-daemon dbus-tools
  # dbus falls back to '/etc/machine-id' when '/var/lib/dbus/machine-id' does not exist,
  # the base image ships an empty placeholder file, which 'dbus-uuidgen --ensure' rejects:
  run sh -c "test -s /etc/machine-id || rm -f /etc/machine-id"
  run dbus-uuidgen --ensure=/etc/machine-id

  install pulseaudio pavucontrol
  install "${FILE_MANAGER}"
  install $APPS

  # install desktop environment last,
  # so we can find the applications installed when creating the cache
  if [ "${DESKTOP}" == "xfce4" ] || [ "${DESKTOP}" == "all" ]; then
    install xfce4-session xfce4-panel xfwm4 xfdesktop xfce4-settings
  fi
  if [ "${DESKTOP}" == "lxde" ] || [ "${DESKTOP}" == "all" ]; then
    install lxsession lxpanel openbox lxappearance
  fi
  if [ "${DESKTOP}" == "lxqt" ] || [ "${DESKTOP}" == "all" ]; then
    install lxqt-session lxqt-panel openbox lxqt-config
  fi
  if [ "${DESKTOP}" == "mate" ] || [ "${DESKTOP}" == "all" ]; then
    install mate-session-manager mate-panel marco mate-control-center
  fi
  if [ "${DESKTOP}" == "budgie" ] || [ "${DESKTOP}" == "all" ]; then
    install budgie-desktop budgie-session budgie-control-center
  fi
  if [ "${DESKTOP}" == "cinnamon" ] || [ "${DESKTOP}" == "all" ]; then
    install cinnamon cinnamon-session xterm
  fi
  if [ "${DESKTOP}" == "enlightenment" ] || [ "${DESKTOP}" == "all" ]; then
    install enlightenment terminology xterm
  fi
  if [ "${DESKTOP}" == "xterm" ] || [ "${DESKTOP}" == "all" ]; then
    install xterm
  fi

  run userdel -r "${TARGET_USER}" || true
  run groupdel "${TARGET_GROUP}" || true
  run rm -fr "/home/${TARGET_USER}"
  run groupadd -r -g "${TARGET_GID}" "${TARGET_GROUP}"
  run useradd -m -u "${TARGET_UID}" -g "${TARGET_GID}" --shell /bin/bash "${TARGET_USER}"
  run usermod -aG "${TARGET_USER_GROUPS}" "${TARGET_USER}"
  run sh -c "echo \"${TARGET_USER}:${TARGET_PASSWORD}\" | chpasswd"
  run chown -R "${TARGET_UID}:${TARGET_GID}" "/home/${TARGET_USER}"
  run sh -c "cd /home/${TARGET_USER};setpriv --reuid ${TARGET_UID} --regid ${TARGET_GID} --init-groups --reset-env mkdir -p Documents Downloads Music Pictures Videos Network"
fi

# default DE commands:
# ie: "mate" -> "mate-"
# overriden for "lxde" -> "lx" for "lxsession" and "lxpanel"
# "all" installs every desktop environment and starts LXDE
DE_COMMAND_PREFIX="${DESKTOP}-"
if [ "${DESKTOP}" == "lxde" ] || [ "${DESKTOP}" == "all" ]; then
  DE_COMMAND_PREFIX="lx"
fi

if [ "${SEAMLESS}" == "1" ]; then
  DE_COMMAND="${DE_COMMAND_PREFIX}panel"
else
  DE_COMMAND="${DE_COMMAND_PREFIX}session"
fi

# known issues:
# * xfce4-panel keeps moving!

if [ "${DESKTOP}" == "xfce4" ]; then
  echo "${DESKTOP} known issue: panel keeps moving"
elif [ "${DESKTOP}" == "cinnamon" ] || [ "${DESKTOP}" == "enlightenment" ]; then
  if [ "${SEAMLESS}" == "1" ]; then
    echo "no seamless mode with ${DESKTOP}"
    DE_COMMAND="xterm"
  elif [ "${DESKTOP}" == "enlightenment" ]; then
    DE_COMMAND="enlightenment"
  fi
elif [ "${DESKTOP}" == "xterm" ]; then
  DE_COMMAND="xterm"
fi

# the display may be provided by another container which is still starting,
# so wait up to 30 seconds for its socket:
WAIT_FOR_DISPLAY="for i in \$(seq 300); do test -S /tmp/.X11-unix/X${XDISPLAY#:} && break; sleep 0.1; done;"
# the session bus runs in this container, so that dbus activation starts services here,
# and xpra connects to it using '--dbus=wait', its socket is in the shared '/run' volume.
# the environment is exported first so that services started by the bus also inherit it.
# there is no accessibility bus in the pod, 'NO_AT_BRIDGE' stops GTK applications from looking for one.
# when xpra starts the X server, it requires the authorization cookie, which xpra saves in the shared '/run' volume:
SESSION_BUS="unix:path=/run/user/${TARGET_UID}/bus"
SESSION_ENV="export XDG_RUNTIME_DIR=/run/user/${TARGET_UID} DISPLAY=${XDISPLAY} XAUTHORITY=/run/user/${TARGET_UID}/xpra/Xauthority-${XDISPLAY#:} DBUS_SESSION_BUS_ADDRESS=${SESSION_BUS} NO_AT_BRIDGE=1;"
START_SESSION_BUS="dbus-daemon --session --address=${SESSION_BUS} --fork;"
# xpra only starts pulseaudio once it has found the session bus,
# so the bus must be started before waiting for the pulseaudio socket:
WAIT_FOR_PULSEAUDIO="for i in \$(seq $((PULSEAUDIO_WAIT*10))); do test -S /run/user/${TARGET_UID}/pulse/native && break; sleep 0.1; done;"
# ugly syntax for arrays of strings with shell variables:
buildah config --entrypoint "[ \"/usr/bin/setpriv\", \"--no-new-privs\", \"--reuid\", \"${TARGET_UID}\", \"--regid\", \"${TARGET_GID}\", \"--init-groups\", \"--reset-env\", \"/bin/bash\", \"-c\", \"${SESSION_ENV} ${WAIT_FOR_DISPLAY} ${START_SESSION_BUS} ${WAIT_FOR_PULSEAUDIO} exec ${DE_COMMAND}\" ]" $CONTAINER
buildah commit $CONTAINER $IMAGE_NAME
