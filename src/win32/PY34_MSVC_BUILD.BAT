SETLOCAL
ECHO OFF
SET ARGS=%*

REM locate VC 10:
IF EXIST "%ProgramFiles%\Microsoft Visual Studio 10.0\VC" (
	SET VC=%ProgramFiles%\Microsoft Visual Studio 10.0\VC
)
IF EXIST "%ProgramFiles(x86)%\Microsoft Visual Studio 10.0\VC" (
	SET VC=%ProgramFiles(x86)%\Microsoft Visual Studio 10.0\VC
)

set PYTHON=C:\Python34
set COMPILER_ARGS=--compiler=msvc
set BUILD_TYPE=-MSVC
set CL_VERSION=2010

CALL win32\BUILD.BAT
if %ERRORLEVEL% NEQ 0 (
	ECHO "build error, see output above"
	PAUSE
	ENDLOCAL
	EXIT /b 1
)
CALL win32\BUILD_INSTALLER_PACKAGE.BAT %ARGS%

ENDLOCAL
SET ERRORLEVEL=0
