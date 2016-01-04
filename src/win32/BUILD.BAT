ECHO OFF
SET ARGS=%*
set DIR=%CD%

SETLOCAL EnableExtensions EnableDelayedExpansion

IF EXIST "E:\Xpra-Build-Libs\" (
	SET XPRA_WIN32_BUILD_LIB_PREFIX=E:\Xpra-Build-Libs\
)
IF EXIST "E:\Xpra-Build-Libs-v0.17.x\" (
	SET XPRA_WIN32_BUILD_LIB_PREFIX=E:\Xpra-Build-Libs-v0.17.x\
)
REM support double-click on BAT file, so run from parent directory:
IF EXIST "MAKE-INSTALLER.BAT" CD ..

REM "*********THESE MUSE BE SET BEFORE RUNNING**************"
if "%PYTHON%"=="" (
	ECHO build error, missing %%PYTHON%%
	GOTO ERROR
)
if "%DO_BUILD%"=="" (
	SET DO_BUILD=1
)
if "%DO_INSTALLER%"=="" (
	SET DO_INSTALLER=1
)
if "%DO_ZIP%"=="" (
	SET DO_ZIP=1
)
if "%DIST%"=="" (
	SET DIST="dist"
)
ECHO PYTHON=%PYTHON%
ECHO VC=%VC%
ECHO DO_BUILD=%DO_BUILD%
ECHO DO_INSTALLER=%DO_INSTALLER%
ECHO DO_ZIP=%DO_ZIP%

SET PYTHON_EXE=%PYTHON%\python.exe
SET PYTHONPATH=.;%PYTHONPATH%
SET INNOSETUP="%ProgramFiles%\Inno Setup 5\ISCC.exe"
IF EXIST "%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe" (
	SET INNOSETUP="%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe"
)
SET TORTOISESVN="%ProgramFiles%\TortoiseSVN"
IF EXIST "%ProgramFiles(x86)%\TortoiseSVN" (
	SET TORTOISESVN="%ProgramFiles(x86)%\TortoiseSVN"
)
SET ZIP7="%ProgramFiles%\7-Zip\7z.exe"
IF EXIST "%ProgramFiles(x86)%\7-Zip\7z.exe" (
	SET ZIP7="%ProgramFiles(x86)%\7-Zip\7z.exe"
)
SET SVNVERSION_EXE=svnversion
SET EXTRA_VERSION=
SET BUILD_DIR=build

FOR /F "delims=" %%i IN ('%PYTHON_EXE% -c "import sys;print(sys.version_info.major)"') DO set PYTHON_MAJOR_VERSION=%%i
FOR /F "delims=" %%i IN ('%PYTHON_EXE% -c "import sys;print(sys.version_info.minor)"') DO set PYTHON_MINOR_VERSION=%%i
ECHO Found Python version %PYTHON_MAJOR_VERSION%.%PYTHON_MINOR_VERSION%

REM "FLAGS TO DISABLE / ENABLE FEATURES"
SET SHOW_DEPENDENCIES=0
REM "IE:"
REM SET BUILD_ARGS=%BUILD_ARGS% --with-debug

if "%DO_BUILD%"=="1" (
	REM CLEAN
	%PYTHON_EXE% ./setup.py clean
	
	REM Record Version Info
	%PYTHON_EXE% -c "from add_build_info import record_src_info;record_src_info()"
)

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


if "%DO_BUILD%"=="0" (
	ECHO "Skipping build step"
	GOTO MAKEINSTALLER
)
ECHO ***************************************************************
ECHO ****** Clearing build directory
RMDIR /S /Q %BUILD_DIR% %DIST% Output Temp 2> NUL
DEL /Q Xpra_Setup*.exe 2> NUL
DEL /Q win32\cx_freeze-xpra.log win32\build-xpra.log win32\py2exe-xpra.log win32\innosetup.log 2> NUL

if NOT "%VC%"=="" (
	if "%VSINSTALLDIR%"=="" (
		ECHO ***************************************************************
		ECHO ****** load Visual Studio env
		CALL "%VC%\bin\vcvars32.bat"
	)
)

ECHO ***************************************************************
ECHO ****** build cython pyd files inplace
ECHO %PYTHON_EXE% -OO setup.py build_ext %BUILD_ARGS% --inplace %COMPILER_ARGS% ^> win32\build-xpra.log
%PYTHON_EXE% -OO setup.py build_ext %BUILD_ARGS% --inplace %COMPILER_ARGS% > win32\build-xpra.log
if %errorlevel% NEQ 0 (
	ECHO "build error, see win32\build-xpra.log"
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
IF %SHOW_DEPENDENCIES% NEQ 0 SET PY2EXE_ARGS=%BUILD_ARGS% -x
ECHO %PYTHON_EXE% -OO setup.py py2exe %PY2EXE_ARGS% ^> win32\py2exe-xpra.log
%PYTHON_EXE% -OO setup.py py2exe %PY2EXE_ARGS% > win32\py2exe-xpra.log
if %errorlevel% NEQ 0 (
	ECHO "py2exe error, see win32\py2exe-xpra.log"
	GOTO ERROR
)

REM Delete all GStreamer DLLs and only add those we actually want
DEL %DIST%\gst*dll
ECHO ****** Adding GStreamer Main DLLs
SET GST_PLUGIN_DIR=%DIST%\gstreamer-0.10
MKDIR %GST_PLUGIN_DIR%
SET GST_BIN_DIR=%DIST%\
REM To install the gstreamer libraries into a subdirectory instead:
REM MKDIR %DIST%\gstreamer-0.10\bin
REM SET GST_BIN_DIR=%DIST%\gstreamer-0.10\bin
FOR %%a in (audio base controller dataprotocol fft interfaces net reamer app riff tag) DO (
	COPY /B /Y /V "%GSTREAMER%\bin\libgst%%a*.dll" %GST_BIN_DIR%
)
FOR %%a in (FLAC id3tag mad mp3lame ogg orc speex vorbis wav) DO (
	COPY /B /Y /V "%GSTREAMER%\bin\lib%%a*.dll" %GST_BIN_DIR%
)
COPY /B /Y /V "%GSTREAMER%\bin\z*.dll" %GST_BIN_DIR%
ECHO ****** Adding GStreamer Plugin DLLs
FOR %%a in (audiofx audioparsersbad audiorate audioresample audiotestsrc app coreelements flac lame mad ogg gdp mpegaudioparse speex volume vorbis wavpack waveenc wavparse) DO (
	COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgst%%a.dll" %DIST%\gstreamer-0.10\
)
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstaudio*.dll" %GST_PLUGIN_DIR%
COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgstdirectsound*.dll" %GST_PLUGIN_DIR%
COPY /B /Y /V "%PYGSTDLL%\libgstpython-v2.7.dll" %GST_BIN_DIR%
COPY /B /Y /V "%GSTREAMER%\bin\gst-launch.exe" %GST_BIN_DIR%
COPY /B /Y /V "%GSTREAMER%\bin\gst-inspect.exe" %GST_BIN_DIR%
REM DEL %GST_BIN_DIR%\av*dll
REM DEL %GST_BIN_DIR%\libdvd*dll

REM "Overwrite the old version shipped with gstreamer - not sure why the PYTHONPATH order is not honoured.."
ECHO ****** Fix GTK DLLs
XCOPY /I /Y /S /Q "%GTK%\bin\*.dll" %DIST%\

GOTO MAKEINSTALLER


:PYTHON3
SET EXTRA_VERSION=-GTK3-py%PYTHON_MAJOR_VERSION%%PYTHON_MINOR_VERSION%
ECHO %PYTHON_EXE% -OO setup.py install_exe -d %DIST% ^> win32\cx_freeze-xpra.log
%PYTHON_EXE% -OO setup.py install_exe -d %DIST% > win32\cx_freeze-xpra.log
if %errorlevel% NEQ 0 (
	ECHO "cx_freeze error, see win32\cx_freeze-install.log"
	GOTO ERROR
)


:MAKEINSTALLER

REM Use a custom script to move the PyOpenGL bits back into the library.zip
REM (ugly, but hacking py2exe is worse?)
ECHO ****** Moving OpenGL into library.zip
ECHO %PYTHON_EXE% win32\move_to_zip.py %DIST%\library.zip %DIST% OpenGL
%PYTHON_EXE% win32\move_to_zip.py %DIST%\library.zip %DIST% OpenGL

ECHO ****** Generating HTML Manual Page
REM "Add mingw to the path unconditionally so we can find groff"
SET PATH=C:\MinGW\bin;C:\MinGW\msys\1.0\bin;%PATH%
groff.exe -mandoc -Thtml < man\xpra.1 > %DIST%\manual.html

ECHO ****** Adding TortoisePlink
REM "These are the versions currently used by TortoisePlink.exe: VC 2012 redist.."
COPY /B /Y /V "C:\WINDOWS\system32\msvcr110.dll" %DIST%\ > NUL
COPY /B /Y /V "C:\WINDOWS\system32\msvcp110.dll" %DIST%\ > NUL
COPY /B /Y /V %TORTOISESVN%\bin\TortoisePlink.exe %DIST%\Plink.exe > NUL
COPY /B /Y /V %TORTOISESVN%\Putty-LICENSE.txt %DIST%\ > NUL


if "%DO_ZIP%"=="1" (
	ECHO ***************************************************************
	ECHO ****** Creating ZIP file
	SET ZIP_DIR=Xpra%EXTRA_VERSION%%BUILD_TYPE%_%FULL_VERSION%
	SET ZIP_FILENAME=!ZIP_DIR!.zip
	ECHO RD /S /Q !ZIP_DIR! ^> NUL
	RD /S /Q !ZIP_DIR! > NUL
	ECHO DEL !ZIP_FILENAME! ^> NUL
	DEL !ZIP_FILENAME! > NUL
	ECHO XCOPY /S /I /X /Q %DIST% !ZIP_DIR!
	XCOPY /S /I /X /Q %DIST% !ZIP_DIR!
	ECHO %ZIP7% a -r !ZIP_FILENAME! !ZIP_DIR! ^> NUL
	%ZIP7% a -r !ZIP_FILENAME! !ZIP_DIR! > NUL
	dir !ZIP_FILENAME!
)

if "%DO_INSTALLER%"=="1" (
	ECHO ***************************************************************
	ECHO ****** Creating the installer using InnoSetup:
	COPY /Y win32\xpra.iss xpra.iss > NUL
	ECHO %INNOSETUP% xpra.iss ^> win32\innosetup.log
	%INNOSETUP% xpra.iss > win32\innosetup.log
	if %errorlevel% NEQ 0 (
		ECHO "InnoSetup error"
		GOTO ERROR
	)

	ECHO ***************************************************************
	ECHO ****** Finished - running the new installer
	SET INSTALLER_FILENAME=Xpra%EXTRA_VERSION%%BUILD_TYPE%_Setup_%FULL_VERSION%.exe
	MOVE /Y Output\Xpra_Setup.exe !INSTALLER_FILENAME!
	RMDIR Output
	dir !INSTALLER_FILENAME!
	if "%DO_NOTRUN%"=="1" (
		ECHO ****** Not Running Installer
	) else (
		!INSTALLER_FILENAME! %ARGS%
	)
)
GOTO END

:ERROR
pause
:END

ENDLOCAL
