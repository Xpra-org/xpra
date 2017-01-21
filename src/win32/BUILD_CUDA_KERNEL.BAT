ECHO OFF
SETLOCAL

SET KERNEL=%1
SET NVCC_DIR=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v8.0\bin\
SET NVCC=%NVCC_DIR%\nvcc.exe
SET CL_VERSION=2015
CALL "C:\Program Files (x86)\Microsoft Visual Studio 14.0\VC\vcvarsall.bat" x86_amd64
SET CUDA_SRC=xpra\codecs\cuda_common\%KERNEL%.cu
SET CUDA_BIN=xpra\codecs\cuda_common\%KERNEL%.fatbin

REM nvcc -fatbin -c %CUDA_SRC% -o %CUDA_BIN% --use-local-env --cl-version %CL_VERSION% -gencode=arch=compute_62,code=sm_62 --machine 64 -v
ECHO nvcc -fatbin -c %CUDA_SRC% -o %CUDA_BIN% --use-local-env --cl-version %CL_VERSION% -gencode=arch=compute_62,code=sm_62 --machine 64
nvcc -fatbin -c %CUDA_SRC% -o %CUDA_BIN% --use-local-env --cl-version %CL_VERSION% -gencode=arch=compute_62,code=sm_62 --machine 64
REM done

ENDLOCAL
SET ERRORLEVEL=0
