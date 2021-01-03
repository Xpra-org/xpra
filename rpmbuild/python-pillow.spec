%{!?__python2: %global __python2 /usr/bin/python2}
%{!?python2_sitearch:%global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))" 2>/dev/null)}
%global py2_incdir %{_includedir}/python%{python2_version}
%global py3_incdir %{_includedir}/python%{python3_version}

%global lcms lcms
%global libjpeg libjpeg
%global tkinter tkinter
%global PyQt4 PyQt4
# none of these RHEL versions have python 3
%global with_qt4 1
%global with_tk 1
%if 0%{?el7}
	%global with_python3 0
	%global with_filter 1
	%global with_webp 0
	%global lcms lcms2
	%global libjpeg libjpeg-turbo
%endif
%if 0%{?fedora}%{?el8}
	%global with_python3 1
	%global lcms lcms2
	%global with_filter 1
	%global with_webp 1
        %global tkinter python2-tkinter
%endif
%if 0%{?el8}
	#don't override the system python3 package:
	%global with_python3 0
	%global with_qt4 0
	%global with_tk 0
	%global with_filter 0
%endif


Version:        6.2.2
Release:        2%{?snap}%{?dist}
Summary:        Python image processing library

# License: see http://www.pythonware.com/products/pil/license.htm
License:        MIT
URL:            http://python-imaging.github.com/Pillow/
Source:         https://files.pythonhosted.org/packages/b3/d0/a20d8440b71adfbf133452d4f6e0fe80de2df7c2578c9b498fb812083383/Pillow-%{version}.tar.gz

%if 0%{?el7}
Name:           python-pillow
Provides:       python2-pillow = %{version}-%{release}
Conflicts:      python2-pillow < %{version}-%{release}
Provides:       python-imaging = %{version}-%{release}
Obsoletes:      python-imaging <= 1.1.7-12
Provides:       python2-imaging = %{version}-%{release}
Obsoletes:      python2-imaging <= 1.1.7-12
%else
Name:           python2-pillow
%endif

%if "%{?lcms}"!="%{nil}"
Requires:	%{lcms}
%endif

BuildRequires:  python2-devel
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

%if 0%{with_python3}
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
%if %{with_tk}
BuildRequires:  python3-tkinter
%endif
%if 0%{with_qt4}
BuildRequires:  python3-PyQt4
%endif
BuildRequires:  python3-numpy
#BuildRequires:  python3-sphinx
%endif


%if 0%{with_filter} > 0
%filter_provides_in %{python2_sitearch}
%filter_provides_in %{python3_sitearch}
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


%if 0%{with_python3}
%package -n python3-pillow
Summary:        Python 3 image processing library
Provides:       python3-imaging = %{version}-%{release}

%description -n python3-pillow
%{_description}


%package -n python3-pillow-devel
Summary:        Development files for python3-pillow
Group:          Development/Libraries
Requires:       python3-pillow%{?_isa} = %{version}-%{release}
Requires:       python3-devel, libjpeg-devel, zlib-devel

%description -n python3-pillow-devel
Development files for python3-pillow.


%package -n python3-pillow-doc
Summary:        Documentation for python3-pillow
Group:          Documentation
Requires:       python3-pillow = %{version}-%{release}
BuildArch:      noarch

%description -n python3-pillow-doc
Documentation for python3-pillow.


%if %{with_tk}
%package -n python3-pillow-tk
Summary:        Tk interface for python3-pillow
Group:          System Environment/Libraries
Requires:       python3-pillow%{?_isa} = %{version}-%{release}
Requires:       tkinter

%description -n python3-pillow-tk
Tk interface for python3-pillow.
%endif

%if 0%{with_qt4}
%package -n python3-pillow-qt
Summary:        PIL image wrapper for Qt
Group:          System Environment/Libraries
Obsoletes:      python3-pillow <= 2.0.0-5.git93a488e8
Requires:       python3-pillow%{?_isa} = %{version}-%{release}
Requires:       python3-PyQt4

%description -n python3-pillow-qt
PIL image wrapper for Qt.
%endif
%endif


%global debug_package %{nil}


%prep
%setup -q -n Pillow-%{version}
%if %{with_python3}
rm -rf %{py3dir}
cp -a . %{py3dir}
%endif


%build
# Build Python 2 modules
find -name '*.py' | xargs sed -i '1s|^#!.*python|#!%{__python2}|'
CFLAGS="$RPM_OPT_FLAGS" %{__python2} setup.py build
%if %{with_webp} == 0
#couldn't find a better way to disable webp:
#(--disable-webp is ignored)
find -name '*webp*' | xargs rm
%endif

%if %{with_python3}
# Build Python 3 modules
pushd %{py3dir}
find -name '*.py' | xargs sed -i '1s|^#!.*python|#!%{__python3}|'
CFLAGS="$RPM_OPT_FLAGS" %{__python3} setup.py build
%if %{with_webp} == 0
#couldn't find a better way to disable webp:
#(--disable-webp is ignored)
find -name '*webp*' | xargs rm
%endif

#building the html docs require a very specific version of sphinx, PITA
#pushd docs
#PYTHONPATH=$PWD/../build/%py3_libbuilddir make html SPHINXBUILD=sphinx-build-%python3_version
#rm -f _build/html/.buildinfo
#popd
popd
%endif


%install
rm -rf $RPM_BUILD_ROOT
install -d $RPM_BUILD_ROOT/%{py2_incdir}/Imaging
%{__python2} setup.py install --skip-build --root $RPM_BUILD_ROOT

%if %{with_python3}
pushd %{py3dir}
install -d $RPM_BUILD_ROOT/%{py3_incdir}/Imaging
%{__python3} setup.py install --skip-build --root $RPM_BUILD_ROOT
popd
%endif

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

%if %{with_python3}
%files -n python3-pillow
%doc README.rst CHANGES.rst docs/COPYING
%{python3_sitearch}/*
# These are in subpackages
%if %{with_tk}
%exclude %{python3_sitearch}/PIL/_imagingtk*
%exclude %{python3_sitearch}/PIL/ImageTk*
%exclude %{python3_sitearch}/PIL/SpiderImagePlugin*
%endif
%if 0%{with_qt4}
%exclude %{python3_sitearch}/PIL/ImageQt*
%endif

%files -n python3-pillow-devel
%{py3_incdir}/Imaging/

%if %{with_tk}
%files -n python3-pillow-tk
%{python3_sitearch}/PIL/_imagingtk*
%{python3_sitearch}/PIL/ImageTk*
%{python3_sitearch}/PIL/SpiderImagePlugin*
%endif

%if 0%{with_qt4}
%files -n python3-pillow-qt
%{python3_sitearch}/PIL/ImageQt*
%endif

%endif

%changelog
* Sun Jan 03 2020 Antoine Martin <antoine@xpra.org> - 6.2.2-2
- don't conflict with the newer python3 Fedora or CentOS 8 builds

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
