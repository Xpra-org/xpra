SETLOCAL
ECHO OFF
SET ARGS=%*

set PYTHON=C:\Python34
set PATH=%PATH%;C:\MinGW\bin
set PKG_CONFIG_PATH=C:\MinGW\lib\pkgconfig;C:\MinGW\msys\1.0\local\lib\pkgconfig;C:\MinGW\msys\1.0\lib\pkgconfig
set COMPILER_ARGS=--compiler=mingw32
set BUILD_TYPE=-MinGW

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
