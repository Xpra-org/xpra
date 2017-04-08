%global py2_incdir %{_includedir}/python%{python_version}
%global py3_incdir %{_includedir}/python%{python3_version}

%global name3 python3-pillow

%global lcms lcms
%global libjpeg libjpeg
%global tkinter tkinter
%global PyQt4 PyQt4
# none of these RHEL versions have python 3
%if 0%{?el7}
	%global with_python3 0
	%global with_filter 1
	%global with_webp 1
	%global lcms lcms2
%endif
%if 0%{?fedora}
	%global with_python3 1
	%global lcms lcms2
	%global with_filter 1
	%global with_webp 1
%endif
%if 0%{?suse_version}
	%global with_python3 0
	%global with_filter 0
	%global with_webp 1
	%global lcms liblcms
	%global libjpeg libjpeg8
	%global tkinter python-tk
	%global PyQt4 python-qt4
%endif


Name:           python2-pillow
Version:        4.1.0
Release:        1%{?snap}%{?dist}
Summary:        Python image processing library

# License: see http://www.pythonware.com/products/pil/license.htm
License:        MIT
URL:            http://python-imaging.github.com/Pillow/
Source:         https://pypi.python.org/packages/source/P/Pillow/Pillow-%{version}.tar.gz
Provides:       python-pillow
Obsoletes:      python-pillow
Conflicts:      python-pillow

%if 0%{?suse_version}
BuildRequires:  python-devel
%else
BuildRequires:  python2-devel
%endif

BuildRequires:  python-setuptools
BuildRequires:  %{tkinter}
BuildRequires:  tk-devel
#BuildRequires:  python-sphinx
BuildRequires:  %{libjpeg}-devel
BuildRequires:  zlib-devel
BuildRequires:  freetype-devel
%if "%{?lcms}"!="%{nil}"
BuildRequires:  %{lcms}-devel
%endif
%if 0%{with_webp} > 0
BuildRequires:  libwebp-devel
%endif
BuildRequires:  %{PyQt4}
BuildRequires:  numpy

%if 0%{with_python3}
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  python3-tkinter
BuildRequires:  python3-PyQt4
BuildRequires:  python3-numpy
#BuildRequires:  python3-sphinx
%endif

Provides:       python-imaging = %{version}-%{release}
Obsoletes:      python-imaging <= 1.1.7-12
%if "%{?lcms}"!="%{nil}"
Requires:		%{lcms}
%endif

%if 0%{with_filter} > 0
%filter_provides_in %{python_sitearch}
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
Requires:       python-devel, libjpeg-devel, zlib-devel
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


%package tk
Summary:        Tk interface for %{name}
Group:          System Environment/Libraries
Requires:       %{name}%{?_isa} = %{version}-%{release}
Requires:       tkinter
Provides:       python-imaging-tk = %{version}-%{release}
Obsoletes:      python-imaging-tk <= 1.1.7-12

%description tk
Tk interface for %{name}.

%package qt
Summary:        PIL image wrapper for Qt
Group:          System Environment/Libraries
Requires:       %{name}%{?_isa} = %{version}-%{release}
Requires:       PyQt4
Provides:       python-imaging-qt = %{version}-%{release}

%description qt
PIL image wrapper for Qt.


%if 0%{with_python3}
%package -n %{name3}
Summary:        Python 3 image processing library
Provides:       python3-imaging = %{version}-%{release}

%description -n %{name3}
%{_description}


%package -n %{name3}-devel
Summary:        Development files for %{name3}
Group:          Development/Libraries
Requires:       %{name3}%{?_isa} = %{version}-%{release}
Requires:       python3-devel, libjpeg-devel, zlib-devel

%description -n %{name3}-devel
Development files for %{name3}.


%package -n %{name3}-doc
Summary:        Documentation for %{name3}
Group:          Documentation
Requires:       %{name3} = %{version}-%{release}
BuildArch:      noarch

%description -n %{name3}-doc
Documentation for %{name3}.


%package -n %{name3}-tk
Summary:        Tk interface for %{name3}
Group:          System Environment/Libraries
Requires:       %{name3}%{?_isa} = %{version}-%{release}
Requires:       tkinter

%description -n %{name3}-tk
Tk interface for %{name3}.

%package -n %{name3}-qt
Summary:        PIL image wrapper for Qt
Group:          System Environment/Libraries
Obsoletes:      %{name3} <= 2.0.0-5.git93a488e8
Requires:       %{name3}%{?_isa} = %{version}-%{release}
Requires:       python3-PyQt4

%description -n %{name3}-qt
PIL image wrapper for Qt.

%endif


%prep
%setup -q -n Pillow-%{version}
%if %{with_python3}
rm -rf %{py3dir}
cp -a . %{py3dir}
%endif


%build
# Build Python 2 modules
find -name '*.py' | xargs sed -i '1s|^#!.*python|#!%{__python}|'
CFLAGS="$RPM_OPT_FLAGS" %{__python} setup.py build

%if %{with_python3}
# Build Python 3 modules
pushd %{py3dir}
find -name '*.py' | xargs sed -i '1s|^#!.*python|#!%{__python3}|'
CFLAGS="$RPM_OPT_FLAGS" %{__python3} setup.py build

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
install -m 644 libImaging/*.h $RPM_BUILD_ROOT/%{py2_incdir}/Imaging
%{__python} setup.py install --skip-build --root $RPM_BUILD_ROOT

%if %{with_python3}
pushd %{py3dir}
install -d $RPM_BUILD_ROOT/%{py3_incdir}/Imaging
install -m 644 libImaging/*.h $RPM_BUILD_ROOT/%{py3_incdir}/Imaging
%{__python3} setup.py install --skip-build --root $RPM_BUILD_ROOT
popd
%endif

# The scripts are packaged in %%doc
rm -rf $RPM_BUILD_ROOT%{_bindir}


%files
%doc README.rst CHANGES.rst docs/COPYING
%{python_sitearch}/*
# These are in subpackages
%exclude %{python_sitearch}/PIL/_imagingtk*
%exclude %{python_sitearch}/PIL/ImageTk*
%exclude %{python_sitearch}/PIL/SpiderImagePlugin*
%exclude %{python_sitearch}/PIL/ImageQt*

%files devel
%{py2_incdir}/Imaging/

%files doc
%doc Scripts

%files tk
%{python_sitearch}/PIL/_imagingtk*
%{python_sitearch}/PIL/ImageTk*
%{python_sitearch}/PIL/SpiderImagePlugin*

%files qt
%{python_sitearch}/PIL/ImageQt*

%if %{with_python3}
%files -n %{name3}
%doc README.rst CHANGES.rst docs/COPYING
%{python3_sitearch}/*
# These are in subpackages
%exclude %{python3_sitearch}/PIL/_imagingtk*
%exclude %{python3_sitearch}/PIL/ImageTk*
%exclude %{python3_sitearch}/PIL/SpiderImagePlugin*
%exclude %{python3_sitearch}/PIL/ImageQt*

%files -n %{name3}-devel
%{py3_incdir}/Imaging/

%files -n %{name3}-doc
%doc Scripts

%files -n %{name3}-tk
%{python3_sitearch}/PIL/_imagingtk*
%{python3_sitearch}/PIL/ImageTk*
%{python3_sitearch}/PIL/SpiderImagePlugin*

%files -n %{name3}-qt
%{python3_sitearch}/PIL/ImageQt*

%endif

%changelog
* Sun Apr 09 2017 Antoine Martin <antoine@devloop.org.uk> - 4.1.0-1
- new upstream release

* Sun Jan 08 2017 Antoine Martin <antoine@devloop.org.uk> - 4.0.0-1
- new upstream release

* Sat Dec 24 2016 Antoine Martin <antoine@devloop.org.uk> - 3.4.2-2
- try harder to supersede the old package name

* Wed Oct 19 2016 Antoine Martin <antoine@devloop.org.uk> - 3.4.2-1
- new upstream release

* Sun Oct 09 2016 Antoine Martin <antoine@devloop.org.uk> - 3.4.1-1
- new upstream release

* Sat Aug 20 2016 Antoine Martin <antoine@devloop.org.uk> - 3.3.1-1
- new upstream release

* Tue Jul 19 2016 Antoine Martin <antoine@nagafix.co.uk> - 3.3.0-3
- fix lcms2 dependency for Fedora

* Sun Jul 17 2016 Antoine Martin <antoine@nagafix.co.uk> - 3.3.0-2
- rename and obsolete old python package name

* Mon Jul 04 2016 Antoine Martin <antoine@devloop.org.uk> - 3.3.0-1
- new upstream release

* Fri Apr 08 2016 Antoine Martin <antoine@devloop.org.uk> - 3.2.0-2
- tweak liblcms dependencies (not useful on centos)

* Sat Apr 02 2016 Antoine Martin <antoine@devloop.org.uk> - 3.2.0-1
- new upstream release

* Sat Feb 06 2016 Antoine Martin <antoine@devloop.org.uk> - 3.1.1-1
- new upstream release

* Mon Jan 04 2016 Antoine Martin <antoine@devloop.org.uk> - 3.1.0-1
- new upstream release

* Sun Oct 18 2015 Antoine Martin <antoine@devloop.org.uk> - 3.0.0-1
- new upstream release

* Tue Jul 07 2015 Antoine Martin <antoine@devloop.org.uk> - 2.9.0-1
- new upstream release

* Wed Jun 10 2015 Antoine Martin <antoine@devloop.org.uk> - 2.8.2-1
- new upstream release

* Sun Apr 05 2015 Antoine Martin <antoine@devloop.org.uk> - 2.8.1-1
- new upstream release

* Mon Jan 19 2015 Antoine Martin <antoine@devloop.org.uk> - 2.7.0-1
- new upstream release
- remove sane packages which are no longer part of the main source distribution

* Sun Jan 18 2015 Antoine Martin <antoine@devloop.org.uk> - 2.6.2-1
- new upstream release

* Sat Oct 25 2014 Antoine Martin <antoine@devloop.org.uk> - 2.6.1-1
- new upstream release

* Tue Oct 07 2014 Antoine Martin <antoine@devloop.org.uk> - 2.6.0-1
- new upstream release

* Thu Sep 04 2014 Antoine Martin <antoine@devloop.org.uk> - 2.5.3-1
- Initial packaging for xpra
