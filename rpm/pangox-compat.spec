%define _disable_source_fetch 0

Name:           pangox-compat
Version:        0.0.2
Release:        2%{?dist}
Summary:        Compatibility library for pangox

License:        LGPLv2+
URL:            http://ftp.gnome.org/pub/GNOME/sources/pangox-compat/0.0/
Source0:        http://ftp.gnome.org/pub/GNOME/sources/pangox-compat/0.0/%{name}-%{version}.tar.xz

BuildRequires:  pango-devel

%description
This is a compatibility library providing the obsolete pangox library
that is not shipped by Pango itself anymore.

%package devel
Summary: Development files for pangox-compat
Group: Development/Libraries
Requires: %{name} = %{version}-%{release}

%description devel
The %{name}-devel package contains libraries and header files for
developing applications that use %{name}.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "552092b3b6c23f47f4beee05495d0f9a153781f62a1c4b7ec53857a37dfce046" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
xz -dc ../SOURCES/%{name}-%{version}.tar.xz | /usr/bin/tar --no-same-owner -xf -

%build
cd %{name}-%{version}
%configure --disable-static
make %{?_smp_mflags}

%install
cd %{name}-%{version}
make install DESTDIR=$RPM_BUILD_ROOT INSTALL="install -p"
find $RPM_BUILD_ROOT -name '*.la' -exec rm -f {} ';'

%post -p /sbin/ldconfig

%postun -p /sbin/ldconfig


%files
%doc %{name}-%{version}/README %{name}-%{version}/COPYING %{name}-%{version}/NEWS %{name}-%{version}/AUTHORS
%{_libdir}/libpango*-*.so.*
%dir %{_sysconfdir}/pango
%config %{_sysconfdir}/pango/pangox.aliases

%files devel
%{_libdir}/libpango*.so
%{_includedir}/*
%{_libdir}/pkgconfig/*

%changelog
* Tue May 25 2021 Antoine Martin <antoine@xpra.org> - 0.0.2-2
- verify source checksum

* Fri Nov 20 2015 Antoine Martin <antoine@xpra.org> - 0.0.2-1
- Initial package for xpra based on the Fedora spec file
