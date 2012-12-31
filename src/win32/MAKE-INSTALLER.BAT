ECHO OFF
SET ARGS=%*
ECHO "ARGS=%ARGS%"
set DIR=%CD%
SET OLDPYTHONPATH=%PYTHONPATH%

REM "*********CHANGE THESE BEFORE RUNNING**************"
SET PYTHON=C:\Python27
SET PYTHON_EXE=%PYTHON%\python.exe
SET INNOSETUP="C:\Program Files\Inno Setup 5\ISCC.exe"
SET TORTOISESVN=C:\Program Files\TortoiseSVN

SET PYGTK=%PYTHON%\Lib\site-packages\gtk-2.0
SET GTK=%PYGTK%\runtime
SET GSTREAMER=C:\Program Files\OSSBuild\GStreamer\v0.10.7
SET PYGST=%GSTREAMER%\sdk\bindings\python\v2.7\lib\site-packages\gst-0.10
SET PYGSTDLL=%GSTREAMER%\sdk\bindings\python\v2.7\lib\gstreamer-0.10
SET BUILD_DIR=build

SET PYTHONPATH=%PYGTK%;%GTK%\lib;%GTK%\bin;%PYTHON%\Lib\site-packages\;%DIR%;%PYTHONPATH%;%PYGST%;%PYGSTDLL%;

SET SHOW_DEPENDENCIES=1

REM "SET THESE TO 0 TO DISABLE VPX/X264/RENCODE/CLIPBOARD:"
SET X264=1
SET VPX=1
SET WEBP=1
SET RENCODE=1
SET CYXOR=1
SET CLIPBOARD=1
SET SOUND=1
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

SET BUILD_ARGS=
IF %X264% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-x264
IF %VPX% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-vpx
IF %WEBP% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-webp
IF %RENCODE% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-rencode
IF %CYXOR% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-cyxor
IF %CLIPBOARD% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-clipboard
IF %SOUND% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-sound

ECHO ***************************************************************
ECHO ****** Hack for x264/vpx/rencode/gdk-clipboard:
ECHO ****** build pyd file and place it where py2exe can find it
ECHO %PYTHON_EXE% -OO setup.py build %BUILD_ARGS%
%PYTHON_EXE% -OO setup.py build %BUILD_ARGS% > build-xpra.log
if %errorlevel% NEQ 0 (
	ECHO "build error, see build-xpra.log"
	GOTO ERROR
)

IF %X264% NEQ 1 GOTO NO_X264
SET X264_CODEC_PYD=build\lib.win32-2.7\xpra\x264\codec.pyd
COPY %X264_CODEC_PYD% xpra\x264\
if %errorlevel% NEQ 0 (
	ECHO "build error: cannot find compiled x264 codec.pyd"
	GOTO ERROR
)
:NO_X264
IF %VPX% NEQ 1 GOTO NO_VPX
SET VPX_CODEC_PYD=build\lib.win32-2.7\xpra\vpx\codec.pyd
COPY %VPX_CODEC_PYD% xpra\vpx\
if %errorlevel% NEQ 0 (
	ECHO "build error: cannot find compiled vpx codec.pyd"
	GOTO ERROR
)
:NO_VPX
IF %RENCODE% NEQ 1 GOTO NO_RENCODE
SET RENCODE_PYD=build\lib.win32-2.7\xpra\rencode\_rencode.pyd
COPY %RENCODE_PYD% xpra\rencode\
if %errorlevel% NEQ 0 (
	ECHO "build error: cannot find compiled _rencode.pyd"
	GOTO ERROR
)
:NO_RENCODE
IF %CYXOR% NEQ 1 GOTO NO_CYXOR
SET CYXOR_PYD=build\lib.win32-2.7\xpra\xor\cyxor.pyd
COPY %CYXOR_PYD% xpra\xor\
if %errorlevel% NEQ 0 (
	ECHO "build error: cannot find compiled cyxor.pyd"
	GOTO ERROR
)
:NO_CYXOR
IF %CLIPBOARD% NEQ 1 GOTO NO_CLIPBOARD
SET CLIPBOARD_PYD=build\lib.win32-2.7\wimpiggy\gdk\gdk_atoms.pyd
COPY %CLIPBOARD_PYD% wimpiggy\gdk\
if %errorlevel% NEQ 0 (
	ECHO "build error: cannot find compiled gdk_atoms.pyd"
	GOTO ERROR
)
:NO_CLIPBOARD

ECHO ***************************************************************
ECHO ****** py2exe
SET PY2EXE_ARGS=%BUILD_ARGS%
IF %SHOW_DEPENDENCIES% NEQ 0 SET PY2EXE_ARGS=%PY2EXE_ARGS% -x

%PYTHON_EXE% -OO setup.py py2exe %PY2EXE_ARGS% > py2exe-xpra.log
if %errorlevel% NEQ 0 (
	ECHO "py2exe error, see py2exe-xpra.log"
	GOTO ERROR
)

if %SOUND% NEQ 1 GOTO NOGSTREAMER
ECHO ****** Adding gstreamer DLLs
XCOPY /I /Y /S /Q "%GSTREAMER%\bin\*.dll" dist\
XCOPY /I /Y /S /Q "%GSTREAMER%\lib\gstreamer-0.10\*.dll" dist\
COPY /B /Y /V "%PYGSTDLL%\libgstpython-v2.7.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\gst-launch.exe" dist\
REM DEL dist\av*dll
REM DEL dist\libdvd*dll

REM "Overwrite the old version shipped with gstreamer - not sure why the PYTHONPATH order is not honoured.."
ECHO ****** Fix GTK DLLs
XCOPY /I /Y /S /Q "%GTK%\bin\*.dll" dist\
:NOGSTREAMER

ECHO ****** Adding TortoisePlink
ECHO "%TORTOISESVN%\bin\TortoisePlink.exe"
ECHO "%TORTOISESVN%\Putty-License.txt"
COPY /B /Y /V "%TORTOISESVN%\bin\TortoisePlink.exe" dist\Plink.exe
COPY /B /Y /V "%TORTOISESVN%\Putty-LICENSE.txt" dist\


ECHO ***************************************************************
ECHO ****** InnoSetup
COPY win32\xpra.iss xpra.iss
%INNOSETUP% xpra.iss > innosetup.log
ECHO returncode: %errorlevel%
if %errorlevel% NEQ 0 (
	ECHO "InnoSetup error"
	GOTO ERROR
)
dir Output
MOVE /Y Output\Xpra_Setup.exe Xpra_Setup.exe
RMDIR Output

Xpra_Setup.exe %ARGS%
GOTO END

:ERROR
pause
:END
SET PYTHONPATH=%OLDPYTHONPATH%
