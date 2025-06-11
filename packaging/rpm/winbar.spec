%define _disable_source_fetch 0
%define commit d69731f7482e5604cc7592e1241e12c69367e2cb

Name:           winbar
Version:        0.2.3
Release:        1
Summary:        A familiar X11 panel/dock to ease new linux users transition
License:        GPL-3
URL:            https://github.com/jmanc3/winbar
Source0:        https://github.com/jmanc3/winbar/archive/%{commit}.zip

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
BuildRequires:  libXi-devel
BuildRequires:  alsa-lib-devel
BuildRequires:  glm-devel
BuildRequires:  glew-devel

%description
A familiar X11 panel/dock to ease new linux users transition


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "8c043cafa8cf7e28e9e96ed125f758d0d3a0f0fd6e4bcb8bd9280334a8bd6003" ]; then
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
* Wed Jun 11 2025 Antoine Martin <antoine@xpra.org> - 0.2.3-1
- new snapshot

* Tue Jun 10 2025 Antoine Martin <antoine@xpra.org> - 0.2.2-1
- switch back to upstream

* Mon Jun 09 2025 Antoine Martin <antoine@xpra.org> - 0.2.1-1
- use fork to get randr patch

* Thu May 29 2025 Antoine Martin <antoine@xpra.org> - 0.2-1
- new snapshot

* Sun May 18 2025 Antoine Martin <antoine@xpra.org> - 0.1-1
- initial packaging for xpra