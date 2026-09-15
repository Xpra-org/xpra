@ECHO OFF
SETLOCAL

SET KERNEL=%1
SET CUDA_SRC=fs\share\xpra\cuda\%KERNEL%.cu
SET CUDA_BIN=fs\share\xpra\cuda\%KERNEL%.fatbin

REM CUDA can be installed in the source tree, or in its default location:
SET NVCC=cuda\bin\nvcc.exe
IF NOT EXIST "%NVCC%" SET NVCC=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\current\bin\nvcc.exe

CALL "C:\Program Files (x86)\Microsoft Visual Studio 14.0\VC\vcvarsall.bat" x86_amd64
CALL "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
CALL "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"

"%NVCC%" -fatbin -c %CUDA_SRC% -o %CUDA_BIN% ^
	--use-local-env --machine 64 -arch=all -Wno-deprecated-gpu-targets -Xnvlink -ignore-host-info

ENDLOCAL
SET ERRORLEVEL=0
