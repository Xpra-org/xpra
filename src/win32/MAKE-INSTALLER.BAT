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

REM "*********CHANGE THESE BEFORE RUNNING**************"
if "%PYTHON%"=="" (
	REM DEFAULT to Python 2.7:
	SET PYTHON=C:\Python27
)
if "%VC%"=="" (
    SET VC="%ProgramFiles%\Microsoft Visual Studio 9.0\VC"
	IF EXIST "%ProgramFiles(x86)%\Microsoft Visual Studio 9.0\VC" (
		SET VC="%ProgramFiles(x86)%\Microsoft Visual Studio 9.0\VC"
		SET CL_VERSION=2008
	)
	IF EXIST "%ProgramFiles%\Microsoft Visual Studio 10.0\VC" (
		SET VC="%ProgramFiles%\Microsoft Visual Studio 10.0\VC"
		SET CL_VERSION=2010
	)
	IF EXIST "%ProgramFiles(x86)%\Microsoft Visual Studio 10.0\VC" (
		SET VC="%ProgramFiles(x86)%\Microsoft Visual Studio 10.0\VC"
		SET CL_VERSION=2010
	)
)
SET VC=%VC:"=%

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
SET DO_BUILD=1
SET DO_INSTALLER=1
SET DO_ZIP=1

FOR /F "delims=" %%i IN ('%PYTHON_EXE% -c "import sys;print(sys.version_info.major)"') DO set PYTHON_MAJOR_VERSION=%%i
FOR /F "delims=" %%i IN ('%PYTHON_EXE% -c "import sys;print(sys.version_info.minor)"') DO set PYTHON_MINOR_VERSION=%%i
ECHO Found Python version %PYTHON_MAJOR_VERSION%.%PYTHON_MINOR_VERSION%

REM "FLAGS TO DISABLE / ENABLE FEATURES"
SET SHOW_DEPENDENCIES=0
SET BUILD_ARGS=
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
SET ZIP_DIR=Xpra%EXTRA_VERSION%%BUILD_TYPE%_%FULL_VERSION%
SET ZIP_FILENAME=%ZIP_DIR%.zip
SET INSTALLER_FILENAME=Xpra%EXTRA_VERSION%%BUILD_TYPE%_Setup_%FULL_VERSION%.exe


if "%DO_BUILD%"=="0" (
	ECHO "Skipping build step"
	GOTO MAKEINSTALLER
)
ECHO ***************************************************************
ECHO ****** Clearing build directory
RMDIR /S /Q %BUILD_DIR% dist Output Temp 2> NUL
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
ECHO %PYTHON_EXE% -OO setup.py py2exe %COMPILER_ARGS% %PY2EXE_ARGS% ^> win32\py2exe-xpra.log
%PYTHON_EXE% -OO setup.py py2exe %COMPILER_ARGS% %PY2EXE_ARGS% > win32\py2exe-xpra.log
if %errorlevel% NEQ 0 (
	ECHO "py2exe error, see win32\py2exe-xpra.log"
	GOTO ERROR
)

REM Delete all GStreamer DLLs and only add those we actually want
DEL dist\gst*dll
ECHO ****** Adding GStreamer Main DLLs
SET GST_PLUGIN_DIR=dist\gstreamer-0.10
MKDIR %GST_PLUGIN_DIR%
SET GST_BIN_DIR=dist\
REM To install the gstreamer libraries into a subdirectory instead:
REM MKDIR dist\gstreamer-0.10\bin
REM SET GST_BIN_DIR=dist\gstreamer-0.10\bin
FOR %%a in (audio base controller dataprotocol fft interfaces net reamer app riff tag) DO (
	COPY /B /Y /V "%GSTREAMER%\bin\libgst%%a*.dll" %GST_BIN_DIR%
)
FOR %%a in (a52 faa FLAC id3tag mad mp3lame ogg orc speex vorbis wav) DO (
	COPY /B /Y /V "%GSTREAMER%\bin\lib%%a*.dll" %GST_BIN_DIR%
)
COPY /B /Y /V "%GSTREAMER%\bin\z*.dll" %GST_BIN_DIR%
ECHO ****** Adding GStreamer Plugin DLLs
FOR %%a in (a52dec audiofx audioparsersbad audiorate audioresample audiotestsrc app coreelements flac lame mad ogg gdp mpegaudioparse speex volume vorbis wavpack waveenc wavparse) DO (
	COPY /B /Y /V "%GSTREAMER%\lib\gstreamer-0.10\libgst%%a.dll" dist\gstreamer-0.10\
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
ECHO %PYTHON_EXE% -OO setup.py install_exe ^> win32\cx_freeze-xpra.log
%PYTHON_EXE% -OO setup.py install_exe -d dist > win32\cx_freeze-xpra.log
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
COPY /B /Y /V %TORTOISESVN%\bin\TortoisePlink.exe dist\Plink.exe > NUL
COPY /B /Y /V %TORTOISESVN%\Putty-LICENSE.txt dist\ > NUL


if "%DO_ZIP%"=="1" (
	ECHO ***************************************************************
	ECHO ****** Creating ZIP file
	ECHO RD /S /Q %ZIP_DIR%
	RD /S /Q %ZIP_DIR% > NUL
	DEL %ZIP_FILENAME% > NUL
	ECHO XCOPY /S /I /X /Q dist %ZIP_DIR%
	XCOPY /S /I /X /Q dist %ZIP_DIR%
	ECHO %ZIP7% a -r %ZIP_FILENAME% %ZIP_DIR% ^> NUL
	%ZIP7% a -r %ZIP_FILENAME% %ZIP_DIR% > NUL
	dir %ZIP_FILENAME%
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
	MOVE /Y Output\Xpra_Setup.exe %INSTALLER_FILENAME%
	RMDIR Output
	dir %INSTALLER_FILENAME%
	
	if "%DO_NOTRUN%"=="1" (
         ECHO ****** Not Running Installer
        ) else (
                %INSTALLER_FILENAME% %ARGS%
        )
)
GOTO END

:ERROR
pause
:END

ENDLOCAL
