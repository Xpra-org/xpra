Name:	     x264-xpra	
Version:     20150713
Release:     1%{?dist}
Summary:     x264 library for xpra	

Group:       Applications/Multimedia
License:     GPL
URL:	     http://www.videolan.org/developers/x264.html
Source0:     http://download.videolan.org/pub/x264/snapshots/x264-snapshot-%{version}-2245-stable.tar.bz2
BuildRoot:   %(mktemp -ud %{_tmppath}/%{name}-%{version}-%{release}-XXXXXX)

BuildRequires:	yasm


%if 0%{?fedora} || 0%{?rhel} >= 7
BuildRequires: perl-Digest-MD5
%endif

%description
x264 library for xpra

%package devel
Summary: Development files for the x264 library
Group: Development/libraries
Requires: %{name} = %{version}
Requires: pkgconfig

%description devel
This package contains the development files for %{name}.


%prep
%setup -q -n x264-snapshot-%{version}-2245-stable


%build
./configure \
    --prefix="%{_prefix}" \
    --libdir="%{_libdir}/xpra" \
    --includedir="%{_includedir}/xpra" \
    --enable-shared \
    --enable-static

make %{?_smp_mflags}


%install
rm -rf %{buildroot}
make install DESTDIR=%{buildroot}

# remove executable
rm %{buildroot}/usr/bin/x264

%post -p /sbin/ldconfig
%postun -p /sbin/ldconfig

%clean
rm -rf %{buildroot}

%files
%defattr(644,root,root,0755)
%doc AUTHORS COPYING*
%{_libdir}/xpra/libx264.so.*

%files devel
%defattr(644,root,root,0755)
%{_includedir}/xpra/x264.h
%{_includedir}/xpra/x264_config.h
%{_libdir}/xpra/libx264.a
%{_libdir}/xpra/libx264.so
%{_libdir}/xpra/pkgconfig/x264.pc

%changelog
* Tue Jul 14 2015 Antoine Martin <antoine@devloop.org.uk> 20150713
- new upstream release

* Sun Jan 18 2015 Antoine Martin <antoine@devloop.org.uk> 20141218
- new upstream release

* Tue Dec 09 2014 Antoine Martin <antoine@devloop.org.uk> 20141208
- new upstream release

* Tue Oct 07 2014 Antoine Martin <antoine@devloop.org.uk> 20141006
- new upstream release

* Wed Sep 10 2014 Antoine Martin <antoine@devloop.org.uk> 20140909
- version bump

* Sun Jul 20 2014 Antoine Martin <antoine@devloop.org.uk> 20140719
- version bump

* Mon Jul 14 2014 Matthew Gyurgyik <pyther@pyther.net>
- initial package
