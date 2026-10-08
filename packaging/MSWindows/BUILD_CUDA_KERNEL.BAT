@ECHO OFF
SETLOCAL

REM accepts either a kernel name ("BGRX_to_NV12") or a path to its source file:
SET KERNEL=%~n1
SET CUDA_SRC=fs\share\xpra\cuda\%KERNEL%.cu
SET CUDA_BIN=fs\share\xpra\cuda\%KERNEL%.fatbin

REM CUDA can be installed in the source tree, or in its default location:
SET NVCC=cuda\bin\nvcc.exe
IF NOT EXIST "%NVCC%" SET NVCC=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\current\bin\nvcc.exe

REM locate the latest Visual Studio installation with the C++ compiler:
REM (`vcvars64.bat` also needs to find `vswhere.exe` in the PATH)
SET PATH=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer;%PATH%
SET VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe
SET VSINSTALL=
FOR /F "usebackq tokens=*" %%i IN (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) DO SET VSINSTALL=%%i
IF "%VSINSTALL%"=="" (
	ECHO Visual Studio C++ build tools not found, run SETUP_EXTRAS.sh
	EXIT /B 1
)
CALL "%VSINSTALL%\VC\Auxiliary\Build\vcvars64.bat" > NUL

"%NVCC%" -fatbin -c %CUDA_SRC% -o %CUDA_BIN% ^
	--use-local-env --machine 64 -arch=all -Wno-deprecated-gpu-targets -Xnvlink -ignore-host-info

ENDLOCAL
SET ERRORLEVEL=0
