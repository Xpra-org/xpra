@ECHO OFF
SETLOCAL

SET KERNEL=%1
SET CUDA_SRC=fs\share\xpra\cuda\%KERNEL%.cu
SET CUDA_BIN=fs\share\xpra\cuda\%KERNEL%.fatbin

SET NVCC_DIR=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.6\bin\
SET NVCC=%NVCC_DIR%\nvcc.exe

CALL "C:\Program Files (x86)\Microsoft Visual Studio 14.0\VC\vcvarsall.bat" x86_amd64
CALL "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat"

"%NVCC%" -fatbin -c %CUDA_SRC% -o %CUDA_BIN% ^
	--use-local-env --machine 64 -arch=all -Xnvlink -ignore-host-info

ENDLOCAL
SET ERRORLEVEL=0
