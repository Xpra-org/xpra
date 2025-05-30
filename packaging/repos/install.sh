#!/bin/bash

# other options: "xpra-lts" and "xpra-beta"
REPO="xpra"
GITHUB_REPOS="https://raw.githubusercontent.com/Xpra-org/xpra/master/packaging/repos"

# OSNAME=$(grep -e "^NAME=" /etc/os-release | awk -F= '{print $2}' | sed 's/"//g')
# examples:
# MSYS2, Fedora Linux, Debian GNU/Linux, AlmaLinux Kitten, Ubuntu
ID=$(grep -e "^ID=" /etc/os-release | awk -F= '{print $2}' | sed 's/"//g')
# examples:
# msys2, fedora, debian, almalinux, ubuntu
VERSION_ID=$(grep -e "^VERSION_ID=" /etc/os-release | awk -F= '{print $2}' | sed 's/"//g')
MAJOR_VERSION=${VERSION_ID%.*}

if [ "${ID}" == "msys2" ]; then
  pacman -S "${MINGW_PREFIX}-xpra"
  exit 1
fi

dnfinstall() {
  DISTRO=$1
  distro=${DISTRO,,}
  echo "adding rpmfusion"
  sudo dnf install -y "https://mirrors.rpmfusion.org/free/${distro}/rpmfusion-free-release-${MAJOR_VERSION}.noarch.rpm"
  # alternative:
  # sudo dnf install -y "https://download1.rpmfusion.org/free/${distro}/rpmfusion-free-release-${MAJOR_VERSION}.noarch.rpm"
  echo "downloading the repository file"
  sudo wget -O "/etc/yum.repos.d/${REPO}.repo" "${GITHUB_REPOS}/$DISTRO/${REPO}.repo"
  echo "installing 'xpra'"
  sudo dnf install -y xpra
}

if [ "${ID}" == "fedora" ]; then
  echo "installing 'config-manager' plugin"
  sudo dnf install -y dnf-plugins-core --disablerepo='*' --enablerepo='fedora'
  echo "enabling cisco's openh264"
  sudo dnf-3 config-manager --set-enabled fedora-cisco-openh264
  dnfinstall Fedora
  exit 0
fi
if [ "${ID}" == "rhel" ]; then
  sudo dnf config-manager --set-enabled crb
  sudo dnf config-manager --set-enabled powertools
  dnfinstall AlmaLinux
  exit 0
fi
if [ "${ID}" == "centos" ]; then
  sudo dnf config-manager --set-enabled epel-next-release
  sudo dnf config-manager --set-enabled powertools
  dnfinstall CentOS
  exit 0
fi
if [ "${ID}" == "almalinux" ]; then
  sudo dnf config-manager --set-enabled crb
  sudo dnf config-manager --set-enabled epel-release
  sudo dnf config-manager --set-enabled powertools
  dnfinstall AlmaLinux
  exit 0
fi
if [ "${ID}" == "rockylinux" ]; then
  sudo dnf config-manager --set-enabled crb
  sudo dnf config-manager --set-enabled epel-release
  sudo dnf config-manager --set-enabled powertools
  dnfinstall RockyLinux
  exit 0
fi
if [ "${ID}" == "oraclelinux" ]; then
  sudo dnf config-manager --set-enabled "ol${VERSION}_codeready_builder"
  sudo dnf config-manager --set-enabled epel-release
  sudo dnf config-manager --set-enabled powertools
  dnfinstall OracleLinux
  exit 0
fi

if [ "${ID}" == "debian" ] || [ "${ID}" == "ubuntu" ]; then
  echo "installing xpra.org gpg key"
  sudo wget -O "/usr/share/keyrings/xpra.asc" "https://xpra.org/xpra.asc"
  echo "installing xpra.org repository file"
  VERSION_CODENAME=$(grep -e "^VERSION_CODENAME=" /etc/os-release | awk -F= '{print $2}' | sed 's/"//g')
  sudo wget -O "/etc/apt/sources.list.d/${REPO}.sources" "${GITHUB_REPOS}/${VERSION_CODENAME}/${REPO}.sources"
  sudo apt-get update
  sudo apt-get install -y xpra
  exit 0
fi

echo "your distribution is not supported by this script:"
echo " ID=${ID}"
echo " VERSION_ID=${VERSION_ID}"
exit 1
