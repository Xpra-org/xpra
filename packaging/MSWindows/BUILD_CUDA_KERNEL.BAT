@ECHO OFF
SETLOCAL

SET KERNEL=%1
SET CUDA_SRC=fs\share\xpra\cuda\%KERNEL%.cu
SET CUDA_BIN=fs\share\xpra\cuda\%KERNEL%.fatbin

SET NVCC_DIR=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.4\bin\
SET NVCC=%NVCC_DIR%\nvcc.exe

CALL "C:\Program Files (x86)\Microsoft Visual Studio 14.0\VC\vcvarsall.bat" x86_amd64
CALL "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat"

"%NVCC%" -fatbin -c %CUDA_SRC% -o %CUDA_BIN% ^
	--use-local-env --machine 64 ^
	-gencode=arch=compute_50,code=sm_50 ^
	-gencode=arch=compute_52,code=sm_52 ^
	-gencode=arch=compute_53,code=sm_53 ^
	-gencode=arch=compute_60,code=sm_60 ^
	-gencode=arch=compute_61,code=sm_61 ^
	-gencode=arch=compute_62,code=sm_62 ^
	-gencode=arch=compute_70,code=sm_70 ^
	-gencode=arch=compute_75,code=sm_75

ENDLOCAL
SET ERRORLEVEL=0
