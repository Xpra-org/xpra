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
SET SVNVERSION_EXE=svnversion

SET PYGTK=%PYTHON%\Lib\site-packages\gtk-2.0
SET GTK=%PYGTK%\runtime
SET GSTREAMER=C:\Program Files\OSSBuild\GStreamer\v0.10.7
SET PYGST=%GSTREAMER%\sdk\bindings\python\v2.7\lib\site-packages\gst-0.10
SET PYGSTDLL=%GSTREAMER%\sdk\bindings\python\v2.7\lib\gstreamer-0.10
SET BUILD_DIR=build

SET SHOW_DEPENDENCIES=0

REM "SET THESE TO 0 TO DISABLE VPX/X264/RENCODE/CLIPBOARD:"
SET X264=1
SET VPX=1
SET WEBP=1
SET RENCODE=1
SET CYXOR=1
SET CYMATHS=1
SET CLIPBOARD=1
SET SOUND=1
SET OPENGL=1
SET SHADOW=1
SET DEBUG=0
REM "*********CHANGE THESE BEFORE RUNNING**************"

REM support double-click on BAT file, so run from parent directory:
set WORKING_DIRECTORY=%cd%
IF EXIST "MAKE-INSTALLER.BAT" CD ..

SET PYTHONPATH=.;%PYTHONPATH%
SET VERSION=ERROR
FOR /F "delims=" %%i IN ('%PYTHON_EXE% -c "from xpra import __version__;print __version__"') DO set VERSION=%%i
ECHO Building Xpra Version %VERSION%
SET SVNVERSION=ERROR
FOR /F "delims=" %%i IN ('%SVNVERSION_EXE% -n') DO set SVNVERSION=%%i
ECHO Found svnversion=%SVNVERSION%
SET REVISION=
FOR /F "tokens=2 delims=:" %%G IN ("%SVNVERSION%") DO set REVISION=%%G
IF [%REVISION%]==[] set REVISION=%SVNVERSION%
SET FULL_VERSION=%VERSION%-r%REVISION%
ECHO Full version=%FULL_VERSION%

SET PYTHONPATH=%PYGTK%;%GTK%\lib;%GTK%\bin;%PYTHON%\Lib\site-packages\;%DIR%;%PYTHONPATH%;%PYGST%;%PYGSTDLL%;


ECHO ****** Clearing build directory (you can ignore any errors here)
RMDIR /S /Q %BUILD_DIR% dist Output
DEL /Q Xpra_Setup*.exe
DEL /Q xpra\x264\codec.pyd
DEL /Q xpra\x264\codec.c
DEL /Q xpra\vpx\codec.pyd
DEL /Q xpra\vpx\codec.c
DEL /Q xpra\rencode\rencode.pyd
DEL /Q xpra\rencode\rencode.c
DEL /Q wimpiggy\gdk\gdk_atoms.pyd
DEL /Q wimpiggy\gdk\gdk_atoms.c
DEL /Q xpraz\xor\cyxor.pyd
DEL /Q xpra\xor\cyxor.c
DEL /Q xpra\stats\cymaths.pyd
DEL /Q xpra\stats\cymaths.c

ECHO ***************************************************************
SET BUILD_ARGS=

IF %X264% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-x264
IF %VPX% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-vpx
IF %WEBP% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-webp
IF %RENCODE% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-rencode
IF %CYXOR% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-cyxor
IF %CYMATHS% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-cymaths
IF %CLIPBOARD% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-clipboard
IF %SOUND% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-sound
IF %OPENGL% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-opengl
IF %SHADOW% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-shadow

IF %DEBUG% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-debug
IF %DEBUG% EQU 1 SET BUILD_ARGS=%BUILD_ARGS% --with-debug


ECHO ***************************************************************
ECHO ****** build cython pyd files inplace
SET CYTHON_ARGS=%BUILD_ARGS%
IF %DEBUG% EQU 1 SET CYTHON_ARGS=%BUILD_ARGS% --pyrex-gdb

ECHO %PYTHON_EXE% -OO setup.py build_ext %CYTHON_ARGS% --inplace
%PYTHON_EXE% -OO setup.py build_ext %CYTHON_ARGS% --inplace > build-xpra.log
if %errorlevel% NEQ 0 (
	ECHO "build error, see build-xpra.log"
	GOTO ERROR
)

ECHO ***************************************************************
ECHO ****** py2exe
SET PY2EXE_ARGS=%BUILD_ARGS%
IF %SHOW_DEPENDENCIES% NEQ 0 SET PY2EXE_ARGS=%BUILD_ARGS% -x

ECHO %PYTHON_EXE% -OO setup.py py2exe %PY2EXE_ARGS%
%PYTHON_EXE% -OO setup.py py2exe %PY2EXE_ARGS% > py2exe-xpra.log
if %errorlevel% NEQ 0 (
	ECHO "py2exe error, see py2exe-xpra.log"
	GOTO ERROR
)

REM Delete all GStreamer DLLs and only add those we actually want
DEL dist\gst*dll
if %SOUND% NEQ 1 GOTO NOGSTREAMER
ECHO ****** Adding GStreamer Main DLLs
COPY /B /Y /V "%GSTREAMER%\bin\libgstaudio*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libgstbase*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libgstcontroller*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libgstdataprotocol*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libgstfft*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libgstinterfaces*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libgstnet*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libgstreamer*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libgstapp*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libgstriff*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libgsttag*.dll" dist\

COPY /B /Y /V "%GSTREAMER%\bin\liba52*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libfaa*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libFLAC*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libid3tag*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libmad*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libmp3lame*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libogg*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\liborc*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libspeex*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libvorbis*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\libwav*.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\z*.dll" dist\
ECHO ****** Adding GStreamer Plugin DLLs
MKDIR dist\gstreamer-0.10
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgsta52dec.dll" dist\gstreamer-0.10\
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstapp.dll" dist\gstreamer-0.10\
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstaudio*.dll" dist\gstreamer-0.10\
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstcoreelements.dll" dist\gstreamer-0.10\
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstdirectsound*.dll" dist\gstreamer-0.10\
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstflac.dll" dist\gstreamer-0.10\
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstlame.dll" dist\gstreamer-0.10\
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstmad.dll" dist\gstreamer-0.10\
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstogg.dll" dist\gstreamer-0.10\
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstmpegaudioparse.dll" dist\gstreamer-0.10\
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstspeex.dll" dist\gstreamer-0.10\
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstvolume.dll" dist\gstreamer-0.10\
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstvorbis.dll" dist\gstreamer-0.10\
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstwavpack.dll" dist\gstreamer-0.10\
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstwaveenc.dll" dist\gstreamer-0.10\
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstwavparse.dll" dist\gstreamer-0.10\
COPY /B /Y /V "%PYGSTDLL%\libgstpython-v2.7.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\gst-launch.exe" dist\
COPY /B /Y /V "%GSTREAMER%\bin\gst-inspect.exe" dist\
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

ECHO ***************************************************************
ECHO ****** Finished - running the new installer
MOVE /Y Output\Xpra_Setup.exe Xpra_Setup_%FULL_VERSION%.exe
RMDIR Output
dir Xpra_Setup_%FULL_VERSION%.exe

Xpra_Setup_%FULL_VERSION%.exe %ARGS%
GOTO END

:ERROR
pause
:END
SET PYTHONPATH=%OLDPYTHONPATH%
