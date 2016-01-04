SETLOCAL
SET ARGS=%*

REM locate VC 10:
IF EXIST "%ProgramFiles%\Microsoft Visual Studio 10.0\VC" (
	SET VC=%ProgramFiles%\Microsoft Visual Studio 10.0\VC
	SET CL_VERSION=2010
)
IF EXIST "%ProgramFiles(x86)%\Microsoft Visual Studio 10.0\VC" (
	SET VC=%ProgramFiles(x86)%\Microsoft Visual Studio 10.0\VC
	SET CL_VERSION=2010
)

set PYTHON=C:\Python34
set COMPILER_ARGS=--compiler=msvc
set BUILD_TYPE=-MSVC
set CL_VERSION=2010

win32\BUILD.BAT %ARGS%

ENDLOCAL
