ECHO OFF

REM "*********CHANGE THESE BEFORE RUNNING**************"
SET PYTHON=C:\Python27
SET PYTHON_EXE=%PYTHON%\python.exe
SET INNOSETUP="C:\Program Files\Inno Setup 5\ISCC.exe"
SET BUILD_DIR=build

REM "SET THESE TO 0 TO DISABLE VPX/X264/RENCODE/CLIPBOARD:"
SET X264=1
SET VPX=1
SET WEBP=1
SET RENCODE=1
SET CLIPBOARD=1
REM "*********CHANGE THESE BEFORE RUNNING**************"

REM support double-click on BAT file, so run from parent directory:
set WORKING_DIRECTORY=%cd%
IF EXIST "MAKE-INSTALLER.BAT" CD ..

ECHO ****** Clearing build directory
RMDIR /S /Q %BUILD_DIR% dist Output
DEL /Q Xpra_Setup.exe
DEL /Q xpra\x264\win32\codec.pyd
DEL /Q xpra\x264\codec.pyd
DEL /Q xpra\vpx\win32\codec.pyd
DEL /Q xpra\vpx\codec.pyd
DEL /Q xpra\rencode\rencode.pyd
DEL /Q wimpiggy\gdk\gdk_atoms.pyd

ECHO ***************************************************************
ECHO ****** Hack for x264/vpx/rencode:
ECHO ****** build pyd file and place it where py2exe can find it
SET BUILD_ARGS=
IF %X264% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-x264
IF %VPX% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-vpx
IF %WEBP% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-webp
IF %RENCODE% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-rencode
IF %CLIPBOARD% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-clipboard

ECHO %PYTHON_EXE% -OO setup.py build %BUILD_ARGS%
%PYTHON_EXE% -OO setup.py build %BUILD_ARGS% > build-xpra.log
if %errorlevel% NEQ 0 (
	ECHO "build error, see build-xpra.log"
	GOTO:ERROR
)

IF %X264% NEQ 1 GOTO:NO_X264
SET X264_CODEC_PYD=build\lib.win32-2.7\xpra\x264\codec.pyd
COPY %X264_CODEC_PYD% xpra\x264\
if %errorlevel% NEQ 0 (
	ECHO "build error: cannot find compiled x264 codec.pyd"
	GOTO:ERROR
)
:NO_X264
IF %VPX% NEQ 1 GOTO:NO_VPX
SET VPX_CODEC_PYD=build\lib.win32-2.7\xpra\vpx\codec.pyd
COPY %VPX_CODEC_PYD% xpra\vpx\
if %errorlevel% NEQ 0 (
	ECHO "build error: cannot find compiled vpx codec.pyd"
	GOTO:ERROR
)
:NO_VPX
IF %RENCODE% NEQ 1 GOTO:NO_RENCODE
SET RENCODE_PYD=build\lib.win32-2.7\xpra\rencode\_rencode.pyd
COPY %RENCODE_PYD% xpra\rencode\
if %errorlevel% NEQ 0 (
	ECHO "build error: cannot find compiled _rencode.pyd"
	GOTO:ERROR
)
:NO_RENCODE
IF %CLIPBOARD% NEQ 1 GOTO:NO_CLIPBOARD
SET CLIPBOARD_PYD=build\lib.win32-2.7\wimpiggy\gdk\gdk_atoms.pyd
COPY %CLIPBOARD_PYD% wimpiggy\gdk\
if %errorlevel% NEQ 0 (
	ECHO "build error: cannot find compiled gdk_atoms.pyd"
	GOTO:ERROR
)
:NO_CLIPBOARD

ECHO ***************************************************************
ECHO ****** py2exe
%PYTHON_EXE% -OO setup.py py2exe %BUILD_ARGS% > py2exe-xpra.log
if %errorlevel% NEQ 0 (
	ECHO "py2exe error, see py2exe-xpra.log"
	GOTO:ERROR
)

ECHO ***************************************************************
ECHO ****** InnoSetup
COPY win32\xpra.iss xpra.iss
%INNOSETUP% xpra.iss > innosetup.log
ECHO returncode: %errorlevel%
if %errorlevel% NEQ 0 (
	ECHO "InnoSetup error"
	GOTO:ERROR
)
dir Output
MOVE /Y Output\Xpra_Setup.exe Xpra_Setup.exe
RMDIR Output

Xpra_Setup.exe
GOTO:END

:ERROR
pause
:END
