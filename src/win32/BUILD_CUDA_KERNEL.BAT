@ECHO OFF
SETLOCAL

SET KERNEL=%1
SET CUDA_SRC=xpra\codecs\cuda_common\%KERNEL%.cu
SET CUDA_BIN=xpra\codecs\cuda_common\%KERNEL%.fatbin

SET NVCC_DIR=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.6\bin\
SET NVCC=%NVCC_DIR%\nvcc.exe
SET MSVC2019VCBAT=C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvarsall.bat
IF EXIST "%MSVC2019VCBAT%" (
	CALL "%MSVC2019VCBAT%" x86_amd64
) else (
	CALL "C:\Program Files (x86)\Microsoft Visual Studio 14.0\VC\vcvarsall.bat" x86_amd64
)

"%NVCC%" -fatbin -c %CUDA_SRC% -o %CUDA_BIN% ^
	--use-local-env --machine 64 -arch=all -Xnvlink -ignore-host-info

ENDLOCAL
SET ERRORLEVEL=0
