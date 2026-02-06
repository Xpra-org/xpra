# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#we don't want to depend on libcuda via RPM dependencies
#so that we can install NVidia drivers without using RPM packages:
%define __requires_exclude ^libcuda.*$

%define _disable_source_fetch 0
%if "%{getenv:PYTHON3}" == ""
%global python3 python3
%else
%global python3 %{getenv:PYTHON3}
%undefine __pythondist_requires
%undefine __python_requires
%endif
%define python3_sitearch %(%{python3} -Ic "from sysconfig import get_path; print(get_path('platlib').replace('/usr/local/', '/usr/'))" 2> /dev/null)

%global debug_package %{nil}

Name:           %{python3}-torch-cuda
Version:        2.10.0
Release:        1
URL:            https://github.com/pytorch/pytorch
Summary:        PyTorch provides tensor computation with strong GPU acceleration and deep neural networks built on a tape-based autograd system
License:        BSD-3
Group:          Development/Libraries/Python
Source0:        https://github.com/pytorch/pytorch/releases/download/v%{version}/pytorch-v%{version}.tar.gz

BuildRoot:      %{_tmppath}/%{name}-%{version}-build
Provides:       %{python3}-torch

BuildRequires:	coreutils
BuildRequires:  make
BuildRequires:  cmake
BuildRequires:  gcc-c++
BuildRequires:  %{python3}-devel
BuildRequires:  %{python3}-pip
BuildRequires:  %{python3}-setuptools
BuildRequires:  %{python3}-numpy
BuildRequires:  %{python3}-filelock
BuildRequires:  %{python3}-typing-extensions
BuildRequires:  %{python3}-sympy
BuildRequires:  %{python3}-networkx
BuildRequires:  %{python3}-jinja2
BuildRequires:  %{python3}-fsspec
BuildRequires:  %{python3}-mpmath
BuildRequires:  %{python3}-markupsafe
BuildRequires:  cuda

%description
PyTorch is a Python package that provides two high-level features:
* Tensor computation (like NumPy) with strong GPU acceleration
* Deep neural networks built on a tape-based autograd system


Requires:       %{python3}
Requires:       %{python3}-numpy
Requires:       cuda

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "fa8ccbe87f83f48735505371c1c313b4aa6db400b0ae4f8a02844d1e150c695f" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n pytorch-v%{version}
# Create missing NCCL pin file that's excluded from release tarball
mkdir -p .ci/docker/ci_commit_pins
echo "v2.21.5-1" > .ci/docker/ci_commit_pins/nccl-cu12.txt

%build
CUDA=/opt/cuda
PYTHON_BIN=/usr/bin/%{python3}
export NVCC_FLAGS="-fPIE"
export LDFLAGS="%{build_ldflags} -pie"
# Disable NCCL to avoid missing .ci files from release tarball
export USE_NCCL=0
PY_VERSION=$(%{python3} -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
cmake . -B build \
    -DPYTHON_EXECUTABLE:FILEPATH=${PYTHON_BIN} \
    -DPython_EXECUTABLE:FILEPATH=${PYTHON_BIN} \
    -DPython3_EXECUTABLE:FILEPATH=${PYTHON_BIN} \
    -DPython3_FIND_STRATEGY=LOCATION \
    -DPython3_FIND_UNVERSIONED_NAMES=FIRST \
    -DBUILD_PYTHON=ON \
    -DBUILD_SHARED_LIBS=ON \
    -DCMAKE_INSTALL_PREFIX=%{_prefix} \
    -DCMAKE_CUDA_FLAGS="-fPIE" \
    -DCMAKE_CUDA_ARCHITECTURES=all-major \
    -DCMAKE_CUDA_COMPILER=${CUDA}/bin/nvcc \
    -DUSE_NCCL=OFF -DUSE_NUMA=OFF -DUSE_XCCL=OFF -DUSE_MPI=OFF -DUSE_ROCM=off
cmake --build build %{?_smp_mflags} --target install

%install
CUDA=/opt/cuda
cd build
cmake --install . --prefix %{buildroot}%{_prefix}

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root)
%{python3_sitearch}/torch*

%changelog
* Fri Feb 06 2026 Antoine Martin <antoine@xpra.org> - 2.10.0-1
- initial packaging
