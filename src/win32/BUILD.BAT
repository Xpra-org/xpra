set DIR=%CD%

SETLOCAL EnableExtensions EnableDelayedExpansion

IF EXIST "E:\Xpra-Build-Libs\" (
	SET XPRA_WIN32_BUILD_LIB_PREFIX=E:\Xpra-Build-Libs\
)
IF EXIST "E:\Xpra-Build-Libs-v2.0.x\" (
	SET XPRA_WIN32_BUILD_LIB_PREFIX=E:\Xpra-Build-Libs-v2.0.x\
)
REM support double-click on BAT file, so run from parent directory:
IF EXIST "BUILD.BAT" CD ..

REM "*********THESE MUSE BE SET BEFORE RUNNING**************"
if "%PYTHON%"=="" (
	ECHO build error, missing %%PYTHON%%
	GOTO ERROR
)
if "%DIST%"=="" (
	SET DIST="dist"
)

SET PYTHON_EXE=%PYTHON%\python.exe
SET PYTHONPATH=.;%PYTHONPATH%
SET SVNVERSION_EXE=svnversion
SET EXTRA_VERSION=

FOR /F "delims=" %%i IN ('%PYTHON_EXE% -c "import sys;print(sys.version_info.major)"') DO set PYTHON_MAJOR_VERSION=%%i
FOR /F "delims=" %%i IN ('%PYTHON_EXE% -c "import sys;print(sys.version_info.minor)"') DO set PYTHON_MINOR_VERSION=%%i
ECHO Found Python version   %PYTHON_MAJOR_VERSION%.%PYTHON_MINOR_VERSION%

REM "FLAGS TO DISABLE / ENABLE FEATURES"
SET SHOW_DEPENDENCIES=0
REM "IE:"
REM SET BUILD_ARGS=%BUILD_ARGS% --with-debug

%PYTHON_EXE% ./setup.py clean
%PYTHON_EXE% -c "from add_build_info import record_src_info;record_src_info()"

SET VERSION=ERROR
FOR /F "delims=" %%i IN ('%PYTHON_EXE% -c "from xpra import __version__;print(__version__)"') DO set VERSION=%%i
ECHO Building Xpra version  %VERSION%
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
RMDIR /S /Q build %DIST% Temp 2> NUL

if NOT "%VC%"=="" (
	if "%VSINSTALLDIR%"=="" (
		ECHO ***************************************************************
		ECHO ****** load Visual Studio env
		CALL "%VC%\bin\vcvars32.bat"
	)
)

ECHO ***************************************************************
ECHO ****** build cython pyd files inplace
SET BUILD_LOG=win32\Python%PYTHON_MAJOR_VERSION%.%PYTHON_MINOR_VERSION%-build.log
DEL /Q %BUILD_LOG% 2> NUL
ECHO %PYTHON_EXE% -OO setup.py build_ext %BUILD_ARGS% --inplace %COMPILER_ARGS% ^> %BUILD_LOG%
%PYTHON_EXE% -OO setup.py build_ext %BUILD_ARGS% --inplace %COMPILER_ARGS% > %BUILD_LOG%
if %ERRORLEVEL% NEQ 0 (
	ECHO build error, see %BUILD_LOG%
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
SET GSTREAMER="%ProgramFiles%\OSSBuild\GStreamer\v0.10.7"
IF EXIST "%ProgramFiles(x86)%\OSSBuild\GStreamer\v0.10.7" (
    SET GSTREAMER="%ProgramFiles(x86)%\OSSBuild\GStreamer\v0.10.7"
)
REM remove quotes:
SET GSTREAMER=%GSTREAMER:"=%
SET PYGST=%GSTREAMER%\sdk\bindings\python\v2.7\lib\site-packages\gst-0.10
SET PYGSTDLL=%GSTREAMER%\sdk\bindings\python\v2.7\lib\gstreamer-0.10
SET PYTHONPATH=%PYGTK%;%GTK%\lib;%GTK%\bin;%PYTHON%\Lib\site-packages\;%DIR%;%PYTHONPATH%;%PYGST%;%PYGSTDLL%;%GSTREAMER%\lib\site-packages
SET PATH=%PATH%;%GSTREAMER%\sdk\bin;%GSTREAMER%\bin
SET PY2EXE_ARGS=%BUILD_ARGS%
REM Adding OpenSSL to PATH so py2exe can find the DLLs:
SET PATH=%XPRA_WIN32_BUILD_LIB_PREFIX%\OpenSSL\bin;%PATH%
IF %SHOW_DEPENDENCIES% NEQ 0 SET PY2EXE_ARGS=%BUILD_ARGS% -x
SET PY2EXE_LOG=win32\py2exe-xpra.log
DEL /Q %PY2EXE_LOG% 2> NUL
ECHO %PYTHON_EXE% -OO setup.py py2exe %PY2EXE_ARGS% ^> %PY2EXE_LOG%
%PYTHON_EXE% -OO setup.py py2exe %PY2EXE_ARGS% > %PY2EXE_LOG%
if %ERRORLEVEL% NEQ 0 (
	ECHO py2exe error, see %PY2EXE_LOG%
	GOTO ERROR
)

REM Delete all GStreamer DLLs and only add those we actually want
DEL %DIST%\gst*dll 2> NUL
SET GSTREAMER0_LOG=gstreamer0.log
DEL /Q %GSTREAMER0_LOG% 2> NUL
ECHO ****** Adding GStreamer Main DLLs
SET GST_PLUGIN_DIR=%DIST%\gstreamer-0.10
MKDIR %GST_PLUGIN_DIR%
SET GST_BIN_DIR=%DIST%\
REM To install the gstreamer libraries into a subdirectory instead:
REM MKDIR %DIST%\gstreamer-0.10\bin
REM SET GST_BIN_DIR=%DIST%\gstreamer-0.10\bin
FOR %%a in (audio base controller dataprotocol fft interfaces net reamer app riff tag) DO (
	COPY /B /Y /V "%GSTREAMER%\bin\libgst%%a*.dll" %GST_BIN_DIR% > %GSTREAMER0_LOG%
)
FOR %%a in (FLAC id3tag mad mp3lame ogg orc speex vorbis wav) DO (
	COPY /B /Y /V "%GSTREAMER%\bin\lib%%a*.dll" %GST_BIN_DIR% > %GSTREAMER0_LOG%
)
COPY /B /Y /V "%GSTREAMER%\bin\z*.dll" %GST_BIN_DIR% > %GSTREAMER0_LOG%
ECHO ****** Adding GStreamer Plugin DLLs
FOR %%a in (audiofx audioparsersbad audiorate audioresample audiotestsrc app coreelements flac lame mad ogg gdp mpegaudioparse speex volume vorbis wavpack waveenc wavparse) DO (
	COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgst%%a.dll" %DIST%\gstreamer-0.10\ > %GSTREAMER0_LOG%
)
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstaudio*.dll" %GST_PLUGIN_DIR% > %GSTREAMER0_LOG%
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstdirectsound*.dll" %GST_PLUGIN_DIR% > %GSTREAMER0_LOG%
COPY /B /Y /V "%PYGSTDLL%\libgstpython-v2.7.dll" %GST_BIN_DIR% > %GSTREAMER0_LOG%
COPY /B /Y /V "%GSTREAMER%\bin\gst-launch.exe" %GST_BIN_DIR% > %GSTREAMER0_LOG%
COPY /B /Y /V "%GSTREAMER%\bin\gst-inspect.exe" %GST_BIN_DIR% > %GSTREAMER0_LOG%
REM DEL %GST_BIN_DIR%\av*dll
REM DEL %GST_BIN_DIR%\libdvd*dll

REM "Overwrite the old version shipped with gstreamer - not sure why the PYTHONPATH order is not honoured.."
ECHO ****** Fix GTK DLLs
XCOPY /I /Y /S /Q "%GTK%\bin\*.dll" %DIST%\ > %GSTREAMER0_LOG%

GOTO END


:PYTHON3
SET EXTRA_VERSION=-GTK3-py%PYTHON_MAJOR_VERSION%%PYTHON_MINOR_VERSION%
SET CX_FREEZE_ARGS=%BUILD_ARGS%
SET CX_FREEZE_LOG=win32\cx_freeze-install.log
DEL /Q %CX_FREEZE_LOG% 2> NUL
ECHO %PYTHON_EXE% -OO setup.py install_exe %CX_FREEZE_ARGS% -d %DIST% ^> %CX_FREEZE_LOG%
%PYTHON_EXE% -OO setup.py install_exe %CX_FREEZE_ARGS% -d %DIST% > %CX_FREEZE_LOG%
if %ERRORLEVEL% NEQ 0 (
	ECHO cx_freeze error, see %CX_FREEZE_LOG%
	GOTO ERROR
)
GOTO END

:ERROR
PAUSE
ENDLOCAL
EXIT /b 1

:END
ENDLOCAL
SET ERRORLEVEL=0
