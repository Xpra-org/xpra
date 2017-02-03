@ECHO OFF
SETLOCAL

SET KERNEL=%1
SET CUDA_SRC=xpra\codecs\cuda_common\%KERNEL%.cu
SET CUDA_BIN=xpra\codecs\cuda_common\%KERNEL%.fatbin

SET NVCC_DIR=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v8.0\bin\
SET NVCC=%NVCC_DIR%\nvcc.exe
SET CL_VERSION=2015
CALL "C:\Program Files (x86)\Microsoft Visual Studio 14.0\VC\vcvarsall.bat" x86_amd64

"%NVCC%" -fatbin -c %CUDA_SRC% -o %CUDA_BIN% ^
	--use-local-env --cl-version %CL_VERSION% --machine 64 ^
	-gencode=arch=compute_50,code=sm_50 ^
	-gencode=arch=compute_52,code=sm_52 ^
	-gencode=arch=compute_53,code=sm_53 ^
	-gencode=arch=compute_60,code=sm_60 ^
	-gencode=arch=compute_61,code=sm_61 ^
	-gencode=arch=compute_62,code=sm_62

ENDLOCAL
SET ERRORLEVEL=0
