%{!?__python2: %global __python2 /usr/bin/python2}
%{!?python2_sitearch:%global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))" 2>/dev/null)}
%global py2_incdir %{_includedir}/python%{python2_version}
%define _disable_source_fetch 0
%global debug_package %{nil}

%global lcms lcms
%global libjpeg libjpeg
%global tkinter tkinter
%global PyQt4 PyQt4
# none of these RHEL versions have python 3
%global with_qt4 1
%global with_tk 1
%if 0%{?el7}
	%global with_filter 1
	%global with_webp 0
	%global lcms lcms2
	%global libjpeg libjpeg-turbo
%endif
%if 0%{?fedora}%{?el8}
	%global lcms lcms2
	%global with_filter 1
	%global with_webp 1
    %global tkinter python2-tkinter
%endif
%if 0%{?el8}
	#don't override the system python3 package:
	%global with_qt4 0
	%global with_tk 0
	%global with_filter 0
%endif


Version:        6.2.2
Release:        1%{?snap}%{?dist}
Summary:        Python image processing library

# License: see http://www.pythonware.com/products/pil/license.htm
License:        MIT
URL:            http://python-imaging.github.com/Pillow/
Source:         https://files.pythonhosted.org/packages/b3/d0/a20d8440b71adfbf133452d4f6e0fe80de2df7c2578c9b498fb812083383/Pillow-%{version}.tar.gz
Provides:       python-imaging = %{version}-%{release}
Obsoletes:      python-imaging <= 1.1.7-12
Provides:       python2-imaging = %{version}-%{release}
Obsoletes:      python2-imaging <= 1.1.7-12
%if "%{?lcms}"!="%{nil}"
Requires:		%{lcms}
%endif

%if 0%{?el7}
Name:           python-pillow
Provides:       python2-pillow = %{version}-%{release}
Conflicts:      python2-pillow < %{version}-%{release}
%else
Name:           python2-pillow
Provides:       python-pillow = %{version}-%{release}
Obsoletes:      python-pillow < %{version}-%{release}
Conflicts:      python-pillow < %{version}-%{release}
%endif

BuildRequires:  python2-devel
BuildRequires:  gcc

BuildRequires:  python2-setuptools
%if %{with_tk}
BuildRequires:  %{tkinter}
BuildRequires:  tk-devel
%endif
BuildRequires:  %{libjpeg}-devel
BuildRequires:  zlib-devel
BuildRequires:  freetype-devel
%if "%{?lcms}"!="%{nil}"
BuildRequires:  %{lcms}-devel
%endif
%if 0%{with_webp} > 0
BuildRequires:  libwebp-devel
%endif
%if 0%{with_qt4}
BuildRequires:  %{PyQt4}
%endif
%if 0%{?el7}
BuildRequires:  numpy
%else
BuildRequires:  python2-numpy
%endif

%if 0%{with_filter} > 0
%filter_provides_in %{python2_sitearch}
%filter_setup
%endif

%description
Python image processing library, fork of the Python Imaging Library (PIL)

This library provides extensive file format support, an efficient
internal representation, and powerful image processing capabilities.

There are four subpackages: tk (tk interface), qt (PIL image wrapper for Qt),
devel (development) and doc (documentation).


%package devel
Summary:        Development files for %{name}
Group:          Development/Libraries
Requires:       %{name}%{?_isa} = %{version}-%{release}
Requires:       python2-devel, libjpeg-devel, zlib-devel
Provides:       python-imaging-devel = %{version}-%{release}
Obsoletes:      python-imaging-devel <= 1.1.7-12

%description devel
Development files for %{name}.

%package doc
Summary:        Documentation for %{name}
Group:          Documentation
Requires:       %{name} = %{version}-%{release}
BuildArch:      noarch

%description doc
Documentation for %{name}.


%if %{with_tk}
%package tk
Summary:        Tk interface for %{name}
Group:          System Environment/Libraries
Requires:       %{name}%{?_isa} = %{version}-%{release}
Requires:       tkinter
Provides:       python-imaging-tk = %{version}-%{release}
Obsoletes:      python-imaging-tk <= 1.1.7-12

%description tk
Tk interface for %{name}.
%endif

%if 0%{with_qt4}
%package qt
Summary:        PIL image wrapper for Qt
Group:          System Environment/Libraries
Requires:       %{name}%{?_isa} = %{version}-%{release}
Requires:       PyQt4
Provides:       python-imaging-qt = %{version}-%{release}

%description qt
PIL image wrapper for Qt.
%endif


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "db9ff0c251ed066d367f53b64827cc9e18ccea001b986d08c265e53625dab950" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n Pillow-%{version}

%build
# Build Python 2 modules
find -name '*.py' | xargs sed -i '1s|^#!.*python|#!%{__python2}|'
CFLAGS="$RPM_OPT_FLAGS" %{__python2} setup.py build
%if %{with_webp} == 0
#couldn't find a better way to disable webp:
#(--disable-webp is ignored)
find -name '*webp*' | xargs rm
%endif

%install
rm -rf $RPM_BUILD_ROOT
install -d $RPM_BUILD_ROOT/%{py2_incdir}/Imaging
%{__python2} setup.py install --skip-build --root $RPM_BUILD_ROOT
# The scripts are packaged in %%doc
rm -rf $RPM_BUILD_ROOT%{_bindir}


%files
%doc README.rst CHANGES.rst docs/COPYING
%{python2_sitearch}/*
# These are in subpackages
%if %{with_tk}
%exclude %{python2_sitearch}/PIL/_imagingtk*
%exclude %{python2_sitearch}/PIL/ImageTk*
%exclude %{python2_sitearch}/PIL/SpiderImagePlugin*
%endif
%if 0%{with_qt4}
%exclude %{python2_sitearch}/PIL/ImageQt*
%endif

%files devel
%{py2_incdir}/Imaging/

%if %{with_tk}
%files tk
%{python2_sitearch}/PIL/_imagingtk*
%{python2_sitearch}/PIL/ImageTk*
%{python2_sitearch}/PIL/SpiderImagePlugin*
%endif

%if 0%{with_qt4}
%files qt
%{python2_sitearch}/PIL/ImageQt*
%endif

%changelog
* Sat Jul 04 2020 Antoine Martin <antoine@xpra.org> - 6.2.2-1
- workaround python2 naming conflicts on RHEL / CentOS 7
- new upstream release

* Thu Oct 03 2019 Antoine Martin <antoine@xpra.org> - 6.2-2
- new upstream release

* Sat Sep 28 2019 Antoine Martin <antoine@xpra.org> - 6.1-2
- centos8 rebuild with tweaks (ie: no python3)

* Wed Sep 25 2019 Antoine Martin <antoine@xpra.org> - 6.1-1
- new upstream release

* Mon Apr 01 2019 Antoine Martin <antoine@xpra.org> - 6.0-1
- new upstream release

* Thu Jan 10 2019 Antoine Martin <antoine@xpra.org> - 5.4.1-1
- new upstream release

* Wed Oct 10 2018 Antoine Martin <antoine@xpra.org> - 5.3.0-1
- new upstream release

* Tue Jul 03 2018 Antoine Martin <antoine@xpra.org> - 5.2.0-3
- use python2 explicitly

* Tue Jul 03 2018 Antoine Martin <antoine@xpra.org> - 5.2.0-2
- try harder to prevent rpm db conflicts

* Mon Jul 02 2018 Antoine Martin <antoine@xpra.org> - 5.2.0-1
- new upstream release

* Tue Apr 10 2018 Antoine Martin <antoine@xpra.org> - 5.1.0-1
- new upstream release

* Tue Jan 02 2018 Antoine Martin <antoine@xpra.org> - 5.0.0-1
- new upstream release

* Thu Nov 23 2017 Antoine Martin <antoine@xpra.org> - 4.3.0-3
- don't link with webp on CentOS, so we can use our private library in xpra without conflicting

* Mon Oct 09 2017 Antoine Martin <antoine@xpra.org> - 4.3.0-1
- new upstream release

* Mon Jul 31 2017 Antoine Martin <antoine@xpra.org> - 4.2.1-2
- we should provide and obsolete "python2-imaging" as well as "python-imaging"

* Sat Jul 08 2017 Antoine Martin <antoine@xpra.org> - 4.2.1-1
- new upstream release

* Wed Jul 05 2017 Antoine Martin <antoine@xpra.org> - 4.2.0-1
- new upstream release

* Sun Apr 30 2017 Antoine Martin <antoine@xpra.org> - 4.1.1-1
- new upstream release

* Sun Apr 09 2017 Antoine Martin <antoine@xpra.org> - 4.1.0-1
- new upstream release

* Sun Jan 08 2017 Antoine Martin <antoine@xpra.org> - 4.0.0-1
- new upstream release

* Sat Dec 24 2016 Antoine Martin <antoine@xpra.org> - 3.4.2-2
- try harder to supersede the old package name

* Wed Oct 19 2016 Antoine Martin <antoine@xpra.org> - 3.4.2-1
- new upstream release

* Sun Oct 09 2016 Antoine Martin <antoine@xpra.org> - 3.4.1-1
- new upstream release

* Sat Aug 20 2016 Antoine Martin <antoine@xpra.org> - 3.3.1-1
- new upstream release

* Tue Jul 19 2016 Antoine Martin <antoine@xpra.org> - 3.3.0-3
- fix lcms2 dependency for Fedora

* Sun Jul 17 2016 Antoine Martin <antoine@xpra.org> - 3.3.0-2
- rename and obsolete old python package name

* Mon Jul 04 2016 Antoine Martin <antoine@xpra.org> - 3.3.0-1
- new upstream release

* Fri Apr 08 2016 Antoine Martin <antoine@xpra.org> - 3.2.0-2
- tweak liblcms dependencies (not useful on centos)

* Sat Apr 02 2016 Antoine Martin <antoine@xpra.org> - 3.2.0-1
- new upstream release

* Sat Feb 06 2016 Antoine Martin <antoine@xpra.org> - 3.1.1-1
- new upstream release

* Mon Jan 04 2016 Antoine Martin <antoine@xpra.org> - 3.1.0-1
- new upstream release

* Sun Oct 18 2015 Antoine Martin <antoine@xpra.org> - 3.0.0-1
- new upstream release

* Tue Jul 07 2015 Antoine Martin <antoine@xpra.org> - 2.9.0-1
- new upstream release

* Wed Jun 10 2015 Antoine Martin <antoine@xpra.org> - 2.8.2-1
- new upstream release

* Sun Apr 05 2015 Antoine Martin <antoine@xpra.org> - 2.8.1-1
- new upstream release

* Mon Jan 19 2015 Antoine Martin <antoine@xpra.org> - 2.7.0-1
- new upstream release
- remove sane packages which are no longer part of the main source distribution

* Sun Jan 18 2015 Antoine Martin <antoine@xpra.org> - 2.6.2-1
- new upstream release

* Sat Oct 25 2014 Antoine Martin <antoine@xpra.org> - 2.6.1-1
- new upstream release

* Tue Oct 07 2014 Antoine Martin <antoine@xpra.org> - 2.6.0-1
- new upstream release

* Thu Sep 04 2014 Antoine Martin <antoine@xpra.org> - 2.5.3-1
- Initial packaging for xpra
