ECHO OFF
SET ARGS=%*
set DIR=%CD%
SET OLDPYTHONPATH=%PYTHONPATH%
SET OLDPATH=%PATH%

REM support double-click on BAT file, so run from parent directory:
set WORKING_DIRECTORY=%cd%
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
SET DEBUG=0
SET SOUND=1
SET BUILD_ARGS=
SET CYTHON_ARGS=
IF %SOUND% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-sound
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
FOR /F "delims=" %%i IN ('%SVNVERSION_EXE% -n') DO set SVNVERSION=%%i
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
	ECHO ***************************************************************
	ECHO ****** load Visual Studio env
	if "%VSINSTALLDIR%"=="" (
		CALL "%VC%\bin\vcvars32.bat"
	)
)

ECHO ***************************************************************
ECHO ****** build cython pyd files inplace
ECHO %PYTHON_EXE% -OO setup.py build_ext %CYTHON_ARGS% --inplace ^> build-xpra.log
%PYTHON_EXE% -OO setup.py build_ext %CYTHON_ARGS% --inplace > build-xpra.log
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
ECHO %PYTHON_EXE% -OO setup.py py2exe %PY2EXE_ARGS% ^> py2exe-xpra.log
%PYTHON_EXE% -OO setup.py py2exe %PY2EXE_ARGS% > py2exe-xpra.log
if %errorlevel% NEQ 0 (
	ECHO "py2exe error, see py2exe-xpra.log"
	GOTO ERROR
)

REM Delete all GStreamer DLLs and only add those we actually want
DEL dist\gst*dll
if %SOUND% NEQ 1 GOTO NOGSTREAMER
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
:NOGSTREAMER
GOTO MAKEINSTALLER


:PYTHON3
SET EXTRA_VERSION=-GTK3-py%PYTHON_MAJOR_VERSION%%PYTHON_MINOR_VERSION%
REM cx_freeze and lib2to3 build_py overrides don't get on..
REM so we have to run the build in a temporary directory
REM where we can run 2to3 before cx_freeze:
set SOURCE_DIRECTORY=%cd%
MKDIR Temp
ECHO ***************************************************************
ECHO ****** PYTHON3: copying source into Temp
FOR %%a in (etc html5 icons scripts tests win32 xpra) DO (
	echo|set /p=* %%a : 
	XCOPY /I /Y /S /Q %%a Temp\%%a\
)
FOR %%a in (setup.py add_build_info.py MANIFEST.in README NEWS COPYING) DO (
	COPY /Y %%a Temp\ > NUL
)
cd Temp
ECHO using 2to3 to convert to py3k syntax:
ECHO %PYTHON%\Tools\Scripts\2to3.py --no-diffs -x all -f except -w -n . 2^> 2to3.log
%PYTHON%\Tools\Scripts\2to3.py --no-diffs -x all -f except -w -n . 2> 2to3.log

ECHO %PYTHON_EXE% -OO setup.py build_exe ^> cx_freeze-xpra.log
%PYTHON_EXE% -OO setup.py build_exe > cx_freeze-xpra.log
cd %SOURCE_DIRECTORY%
if %errorlevel% NEQ 0 (
	ECHO "cx_freeze error, see cx_freeze-xpra.log"
	GOTO ERROR
)
REM Copy build output to src/dist/
XCOPY /I /Y /S /Q Temp\build\exe.win32-%PYTHON_MAJOR_VERSION%.%PYTHON_MINOR_VERSION%\*.* dist\


:MAKEINSTALLER
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
SET PYTHONPATH=%OLDPYTHONPATH%
SET PATH=%OLDPATH%
