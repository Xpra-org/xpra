ECHO OFF
SET ARGS=%*
set DIR=%CD%

SETLOCAL

REM support double-click on BAT file, so run from parent directory:
IF EXIST "MAKE-INSTALLER.BAT" CD ..

REM "*********CHANGE THESE BEFORE RUNNING**************"
if "%PYTHON%"=="" (
	REM DEFAULT to Python 2.7:
	SET PYTHON=C:\Python34
	SET PYTHON=C:\Python27
	SET VC=C:\Program Files\Microsoft Visual Studio 9.0\VC
)
SET PYTHON_EXE=%PYTHON%\python.exe
SET PYTHONPATH=.;%PYTHONPATH%
SET INNOSETUP=C:\Program Files\Inno Setup 5\ISCC.exe
SET TORTOISESVN=C:\Program Files\TortoiseSVN
SET SVNVERSION_EXE=svnversion
SET EXTRA_VERSION=
SET BUILD_DIR=build

FOR /F "delims=" %%i IN ('%PYTHON_EXE% -c "import sys;print(sys.version_info.major)"') DO set PYTHON_MAJOR_VERSION=%%i
FOR /F "delims=" %%i IN ('%PYTHON_EXE% -c "import sys;print(sys.version_info.minor)"') DO set PYTHON_MINOR_VERSION=%%i
ECHO Found Python version %PYTHON_MAJOR_VERSION%.%PYTHON_MINOR_VERSION%

REM "FLAGS TO DISABLE / ENABLE FEATURES"
SET SHOW_DEPENDENCIES=0
SET BUILD_ARGS=
REM "IE:"
REM SET BUILD_ARGS=%BUILD_ARGS% --with-debug

REM CLEAN
%PYTHON_EXE% ./setup.py clean

REM Record Version Info
%PYTHON_EXE% -c "from add_build_info import record_src_info;record_src_info()"

SET VERSION=ERROR
FOR /F "delims=" %%i IN ('%PYTHON_EXE% -c "from xpra import __version__;print(__version__)"') DO set VERSION=%%i
ECHO Building Xpra Version  %VERSION%
SET SVNVERSION=ERROR
FOR /F "delims=" %%i IN ('%SVNVERSION_EXE% -n ..') DO set SVNVERSION=%%i
ECHO Found svnversion       %SVNVERSION%
SET REVISION=
FOR /F "tokens=2 delims=:" %%G IN ("%SVNVERSION%") DO set REVISION=%%G
IF [%REVISION%]==[] set REVISION=%SVNVERSION%
SET FULL_VERSION=%VERSION%-r%REVISION%
ECHO Full version           %FULL_VERSION%


ECHO ***************************************************************
ECHO ****** Clearing build directory
RMDIR /S /Q %BUILD_DIR% dist Output Temp 2> NUL
DEL /Q Xpra_Setup*.exe 2> NUL
DEL /Q cx_freeze-xpra.log build-xpra.log py2exe-xpra.log innosetup.log 2> NUL

if NOT "%VC%"=="" (
	if "%VSINSTALLDIR%"=="" (
		ECHO ***************************************************************
		ECHO ****** load Visual Studio env
		CALL "%VC%\bin\vcvars32.bat"
	)
)

ECHO ***************************************************************
ECHO ****** build cython pyd files inplace
ECHO %PYTHON_EXE% -OO setup.py build_ext --inplace %COMPILER_ARGS% ^> build-xpra.log
%PYTHON_EXE% -OO setup.py build_ext --inplace %COMPILER_ARGS% > build-xpra.log
if %errorlevel% NEQ 0 (
	ECHO "build error, see build-xpra.log"
	GOTO ERROR
)

if "%PYTHON_MAJOR_VERSION%"=="3" (
	GOTO PYTHON3
)

ECHO ***************************************************************
ECHO ****** PYTHON2: py2exe + gtk2
ECHO ****** setting pygtk and pygst environment variables
SET PYGTK=%PYTHON%\Lib\site-packages\gtk-2.0
SET GTK=%PYGTK%\runtime
SET GSTREAMER=C:\Program Files\OSSBuild\GStreamer\v0.10.7
SET PYGST=%GSTREAMER%\sdk\bindings\python\v2.7\lib\site-packages\gst-0.10
SET PYGSTDLL=%GSTREAMER%\sdk\bindings\python\v2.7\lib\gstreamer-0.10
SET PYTHONPATH=%PYGTK%;%GTK%\lib;%GTK%\bin;%PYTHON%\Lib\site-packages\;%DIR%;%PYTHONPATH%;%PYGST%;%PYGSTDLL%;%GSTREAMER%\lib\site-packages
SET PATH=%PATH%;%GSTREAMER%\sdk\bin;%GSTREAMER%\bin
SET PY2EXE_ARGS=%BUILD_ARGS%
IF %SHOW_DEPENDENCIES% NEQ 0 SET PY2EXE_ARGS=%BUILD_ARGS% -x
ECHO %PYTHON_EXE% -OO setup.py py2exe %COMPILER_ARGS% %PY2EXE_ARGS% ^> py2exe-xpra.log
%PYTHON_EXE% -OO setup.py py2exe %COMPILER_ARGS% %PY2EXE_ARGS% > py2exe-xpra.log
if %errorlevel% NEQ 0 (
	ECHO "py2exe error, see py2exe-xpra.log"
	GOTO ERROR
)

REM Delete all GStreamer DLLs and only add those we actually want
DEL dist\gst*dll
ECHO ****** Adding GStreamer Main DLLs
FOR %%a in (audio base controller dataprotocol fft interfaces net reamer app riff tag) DO (
	COPY /B /Y /V "%GSTREAMER%\bin\libgst%%a*.dll" dist\
)
FOR %%a in (a52 faa FLAC id3tag mad mp3lame ogg orc speex vorbis wav) DO (
	COPY /B /Y /V "%GSTREAMER%\bin\lib%%a*.dll" dist\
)
COPY /B /Y /V "%GSTREAMER%\bin\z*.dll" dist\
ECHO ****** Adding GStreamer Plugin DLLs
MKDIR dist\gstreamer-0.10
FOR %%a in (a52dec audiofx audioparsersbad audiorate audioresample audiotestsrc app coreelements flac lame mad ogg, mpegaudioparse speex volume vorbis wavpack waveenc wavparse) DO (
	COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgst%%a.dll" dist\gstreamer-0.10\
)
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstaudio*.dll" dist\gstreamer-0.10\
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstdirectsound*.dll" dist\gstreamer-0.10\
COPY /B /Y /V "%PYGSTDLL%\libgstpython-v2.7.dll" dist\
COPY /B /Y /V "%GSTREAMER%\bin\gst-launch.exe" dist\
COPY /B /Y /V "%GSTREAMER%\bin\gst-inspect.exe" dist\
REM DEL dist\av*dll
REM DEL dist\libdvd*dll

REM "Overwrite the old version shipped with gstreamer - not sure why the PYTHONPATH order is not honoured.."
ECHO ****** Fix GTK DLLs
XCOPY /I /Y /S /Q "%GTK%\bin\*.dll" dist\

ECHO ****** Using MS-Windows theme
MKDIR dist\etc
MKDIR dist\etc\gtk-2.0
XCOPY /I /Y win32\gtkrc dist\etc\gtk-2.0\
MKDIR dist\lib
MKDIR dist\lib\gtk-2.0
MKDIR dist\lib\gtk-2.0\2.10.0
MKDIR dist\lib\gtk-2.0\2.10.0\engines
XCOPY /I /Y /S /Q "%GTK%\lib\gtk-2.0\2.10.0\engines\*.dll" dist\lib\gtk-2.0\2.10.0\engines


GOTO MAKEINSTALLER


:PYTHON3
SET EXTRA_VERSION=-GTK3-py%PYTHON_MAJOR_VERSION%%PYTHON_MINOR_VERSION%
ECHO %PYTHON_EXE% -OO setup.py install_exe ^> cx_freeze-install.log
%PYTHON_EXE% -OO setup.py install_exe -d dist > cx_freeze-install.log
if %errorlevel% NEQ 0 (
	ECHO "cx_freeze error, see cx_freeze-install.log"
	GOTO ERROR
)


:MAKEINSTALLER

ECHO ****** Generating HTML Manual Page
REM "Add mingw to the path unconditionally so we can find groff"
SET PATH=C:\MinGW\bin;C:\MinGW\msys\1.0\bin;%PATH%
groff.exe -mandoc -Thtml < man\xpra.1 > dist\manual.html

ECHO ****** Adding TortoisePlink
REM "These are the versions currently used by TortoisePlink.exe: VC 2012 redist.."
COPY /B /Y /V "C:\WINDOWS\system32\msvcr110.dll" dist\ > NUL
COPY /B /Y /V "C:\WINDOWS\system32\msvcp110.dll" dist\ > NUL
COPY /B /Y /V "%TORTOISESVN%\bin\TortoisePlink.exe" dist\Plink.exe > NUL
COPY /B /Y /V "%TORTOISESVN%\Putty-LICENSE.txt" dist\ > NUL


ECHO ***************************************************************
ECHO ****** Creating the installer using InnoSetup:
COPY /Y win32\xpra.iss xpra.iss > NUL
ECHO "%INNOSETUP%" xpra.iss ^> innosetup.log
"%INNOSETUP%" xpra.iss > innosetup.log
if %errorlevel% NEQ 0 (
	ECHO "InnoSetup error"
	GOTO ERROR
)

ECHO ***************************************************************
ECHO ****** Finished - running the new installer
SET INSTALLER_FILENAME=Xpra%EXTRA_VERSION%_Setup_%FULL_VERSION%.exe
MOVE /Y Output\Xpra_Setup.exe %INSTALLER_FILENAME%
RMDIR Output
dir %INSTALLER_FILENAME%

%INSTALLER_FILENAME% %ARGS%
GOTO END

:ERROR
pause
:END

ENDLOCAL
