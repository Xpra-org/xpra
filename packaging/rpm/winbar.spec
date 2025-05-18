%define _disable_source_fetch 0
%define commit 892e8d01701a8931ec7f3b5597e555c640fa34c5

Name:           winbar
Version:        0.1
Release:        1
Summary:        A familiar X11 panel/dock to ease new linux users transition
License:        GPL-3
URL:            https://github.com/jmanc3/winbar
Source0:        https://github.com/jmanc3/winbar/archive/892e8d01701a8931ec7f3b5597e555c640fa34c5.zip

BuildRequires:  git
BuildRequires:  cmake
BuildRequires:  g++
BuildRequires:  cairo-devel
BuildRequires:  pango-devel
BuildRequires:  librsvg2-devel
BuildRequires:  xcb-util-devel
BuildRequires:  pulseaudio-libs-devel
BuildRequires:  xcb-util-wm-devel
BuildRequires:  libxkbcommon-x11-devel
BuildRequires:  libconfig-devel
BuildRequires:  xcb-util-cursor-devel
BuildRequires:  dbus-devel
BuildRequires:  fontconfig-devel
BuildRequires:  xcb-util-keysyms-devel
BuildRequires:  alsa-lib-devel
BuildRequires:  glm-devel
BuildRequires:  glew-devel

%description
A familiar X11 panel/dock to ease new linux users transition


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "a716c92e5be5659340f781b3d429c64981113510b13e5a148f4bc8a935457baf" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n %{name}-%{commit}

%build
mkdir -p build
cd build
%cmake -DCMAKE_BUILD_TYPE=Release ../
pushd %{__cmake_builddir}
make
popd
# unzip assets
unzip ../winbar.zip

%install
mkdir -p %{buildroot}%{_sysconfdir} %{buildroot}%{_bindir} %{buildroot}%{_datadir}/winbar >& /dev/null
cd build
pushd %{__cmake_builddir}
cp ./winbar %{buildroot}%{_bindir}
popd
cp -R ./winbar/fonts ./winbar/resources ./winbar/plugins ./winbar/tofix.csv ./winbar/items_custom.ini %{buildroot}%{_datadir}/winbar
cp ./winbar/winbar.cfg %{buildroot}%{_sysconfdir}

%files
%license LICENSE.md
%doc README.md
%{_bindir}/winbar
%{_datadir}/winbar
%{_sysconfdir}/winbar.cfg

%changelog
* Sun May 18 2025 Antoine Martin <antoine@xpra.org> - 0.1-1
- initial packaging for xpra