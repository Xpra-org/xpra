SETLOCAL
ECHO OFF
SET ARGS=%*

REM support double-click on BAT file, so run from parent directory:
IF EXIST "MAKE-INSTALLER.BAT" CD ..

SET VC=%ProgramFiles%\Microsoft Visual Studio 9.0\VC
SET CL_VERSION=2008
SET PYTHON=C:\Python27
SET BUILD_ARGS=
SET COMPILER_ARGS=--compiler=msvc
SET DIST=dist
SET BUNDLE_GSTREAMER1=1

RMDIR /S /Q %DIST%
MKDIR %DIST%

CALL win32\BUILD.BAT
if %ERRORLEVEL% NEQ 0 (
	ECHO "build error, see output above"
	PAUSE
	ENDLOCAL
	EXIT /b 1
)

if "%BUNDLE_GSTREAMER1%"=="1" (
	ECHO.
	ECHO ***************************************************************
	ECHO ***** Building Sound Python 3.4 sub-package:
	ECHO ***************************************************************
	IF EXIST "%ProgramFiles%\Microsoft Visual Studio 10.0\VC" (
		SET VC=%ProgramFiles%\Microsoft Visual Studio 10.0\VC
	)
	IF EXIST "%ProgramFiles(x86)%\Microsoft Visual Studio 10.0\VC" (
		SET VC=%ProgramFiles(x86)%\Microsoft Visual Studio 10.0\VC
	)
	SET CL_VERSION=2010
	SET PYTHON=C:\Python34
	SET DIST=dist\Audio
	SET BUILD_ARGS=--minimal --with-sound
	CALL win32\BUILD.BAT
	if %ERRORLEVEL% NEQ 0 (
		ECHO "build error, see output above"
		PAUSE
		ENDLOCAL
		EXIT /b 1
	)
	ECHO.
)

SET DIST=dist
SET BUILD_TYPE=
CALL win32\BUILD_INSTALLER_PACKAGE.BAT %ARGS%

ENDLOCAL
SET ERRORLEVEL=0
