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
%define _lto_cflags %{nil}
%global __requires_exclude ^lib(cudart|cublas|cublasLt|cufft|cufile|cupti|curand|cusolver|cusparse|nvrtc)\\.so\\..*

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
export CUDA_HOME=${CUDA}
export CUDACXX=${CUDA}/bin/nvcc
# export TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0"
export TORCH_CUDA_ARCH_LIST="8.0"
export USE_NCCL=0
export USE_ROCM=0
export BUILD_TEST=0
export USE_DISTRIBUTED=0
export PYTHON=/usr/bin/%{python3}
export CMAKE_CUDA_COMPILER=${CUDA}/bin/nvcc
export Python3_FIND_UNVERSIONED_NAMES=FIRST
export TORCH_NVCC_FLAGS="-Xcompiler -fPIC"
export NVCC_FLAGS="-fPIE"
export MAX_JOBS=1  # Very conservative, but should avoid OOM
export CMAKE_BUILD_PARALLEL_LEVEL=2  # For CMake builds
export USE_MKLDNN=0
export CMAKE_BUILD_TYPE=Release
export DEBUG=0
export CMAKE_INTERPROCEDURAL_OPTIMIZATION=OFF

unset CFLAGS
unset CXXFLAGS
unset CPPFLAGS
unset LDFLAGS
unset RPM_OPT_FLAGS
unset RPM_LD_FLAGS

# Strip out GCC-specific -specs flags that clang doesn't understand
export CFLAGS="$(echo "%{optflags}" | sed -e 's/-specs=[^ ]*//g' -e 's/-Wno-complain-wrong-lang//g')"
export CXXFLAGS="$(echo "%{optflags}" | sed -e 's/-specs=[^ ]*//g' -e 's/-Wno-complain-wrong-lang//g')"
export LDFLAGS=$(echo "%{build_ldflags}" | sed 's/-specs=[^ ]*//g')

# Set minimal safe flags
export CFLAGS="-O2"
export CXXFLAGS="-O2"
export LDFLAGS="-Wl,--strip-debug"

export MAX_JOBS=4
%{python3} setup.py build

%install
export USE_NCCL=0
export BUILD_TEST=0
export USE_DISTRIBUTED=0
export QA_RPATHS=$[ 0x0001|0x0002 ]
CUDA=/opt/cuda
# this should be the same as the py3_install macro:
%{python3} -m pip install \
    --no-deps \
    --no-build-isolation \
    --ignore-installed \
    --no-user \
    --root=%{buildroot} \
    --prefix=%{_prefix} \
    .

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root)
%{_bindir}/torchrun
%{python3_sitearch}/torch-%{version}*.dist-info
%{python3_sitearch}/torch
%{python3_sitearch}/torchgen
%{python3_sitearch}/functorch

%changelog
* Sun Feb 08 2026 Antoine Martin <antoine@xpra.org> - 2.10.0-1
- initial packaging for xpra with CUDA support builtin
