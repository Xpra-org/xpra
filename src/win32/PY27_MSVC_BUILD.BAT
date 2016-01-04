SETLOCAL
SET ARGS=%*

REM support double-click on BAT file, so run from parent directory:
IF EXIST "MAKE-INSTALLER.BAT" CD ..

SET VC=%ProgramFiles%\Microsoft Visual Studio 9.0\VC
SET CL_VERSION=2008
SET PYTHON=C:\Python27
SET COMPILER_ARGS=--compiler=msvc
set BUILD_TYPE=
set CL_VERSION=2008

win32\BUILD.BAT %ARGS%

ENDLOCAL
