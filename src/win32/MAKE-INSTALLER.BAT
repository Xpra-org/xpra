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
SET BUILD_DIR=build

FOR /F "delims=" %%i IN ('%PYTHON_EXE% -c "import sys;print(sys.version[0])"') DO set PYTHON_MAJOR_VERSION=%%i
FOR /F "delims=" %%i IN ('%PYTHON_EXE% -c "import sys;print(sys.version[0])"') DO set PYTHON_MINOR_VERSION=%%i
ECHO Found Python version %PYTHON_MAJOR_VERSION%.%PYTHON_MINOR_VERSION%

REM "FLAGS TO DISABLE / ENABLE FEATURES"
SET SHOW_DEPENDENCIES=0
SET DEBUG=0
SET SOUND=1
SET BUILD_ARGS=
IF %SOUND% NEQ 1 SET BUILD_ARGS=%BUILD_ARGS% --without-sound
REM "IE:"
REM SET BUILD_ARGS=%BUILD_ARGS% --with-debug

REM CLEAN
%PYTHON_EXE% ./setup.py clean

REM Record Version Info
%PYTHON_EXE% -c "from add_build_info import record_src_info;record_src_info()"

SET VERSION=ERROR
FOR /F "delims=" %%i IN ('%PYTHON_EXE% -c "from xpra import __version__;print(__version__)"') DO set VERSION=%%i
ECHO Building Xpra Version %VERSION%
SET SVNVERSION=ERROR
FOR /F "delims=" %%i IN ('%SVNVERSION_EXE% -n') DO set SVNVERSION=%%i
ECHO Found svnversion=%SVNVERSION%
SET REVISION=
FOR /F "tokens=2 delims=:" %%G IN ("%SVNVERSION%") DO set REVISION=%%G
IF [%REVISION%]==[] set REVISION=%SVNVERSION%
SET FULL_VERSION=%VERSION%-r%REVISION%
ECHO Full version=%FULL_VERSION%


ECHO ****** Clearing build directory (you can ignore any errors here)
RMDIR /S /Q %BUILD_DIR% dist Output Temp
DEL /Q Xpra_Setup*.exe
DEL /Q cx_freeze-xpra.log build-xpra.log py2exe-xpra.log innosetup.log

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
SET PYTHONPATH=%PYGTK%;%GTK%\lib;%GTK%\bin;%PYTHON%\Lib\site-packages\;%DIR%;%PYTHONPATH%;%PYGST%;%PYGSTDLL%;
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
GOTO MAKEINSTALLER


:PYTHON3
REM cx_freeze and lib2to3 build_py overrides don't get on..
REM so we have to run the build in a temporary directory
REM where we can run 2to3 before cx_freeze:
set SOURCE_DIRECTORY=%cd%
MKDIR Temp
ECHO ****** Copying source into Temp
FOR %%a in (etc html5 icons scripts tests win32 xpra) DO (
	ECHO  * %%a :
	XCOPY /I /Y /S /Q %%a Temp\%%a\
)
FOR %%a in (setup.py add_build_info.py MANIFEST.in README NEWS COPYING) DO (
	COPY %%a Temp\
)
cd Temp
%PYTHON%\Tools\Scripts\2to3.py --no-diffs -x all -f except -w -n .
ECHO %PYTHON_EXE% -OO setup.py build_exe ^> cx_freeze-xpra.log
%PYTHON_EXE% -OO setup.py build_exe > cx_freeze-xpra.log
cd %SOURCE_DIRECTORY%
if %errorlevel% NEQ 0 (
	ECHO "cx_freeze error, see cx_freeze-xpra.log"
	GOTO ERROR
)
REM Copy build output to src/dist/
REM XCOPY /I /Y /S /Q Temp\build\exe.win32-%PYTHON_MAJOR_VERSION%.%PYTHON_MINOR_VERSION%\*.* dist\


:MAKEINSTALLER
ECHO ****** Adding TortoisePlink
ECHO "%TORTOISESVN%\bin\TortoisePlink.exe"
ECHO "%TORTOISESVN%\Putty-License.txt"
REM "These are the versions currently used by TortoisePlink.exe: VC 2012 redist.."
COPY /B /Y /V "C:\WINDOWS\system32\msvcr110.dll" dist\
COPY /B /Y /V "C:\WINDOWS\system32\msvcp110.dll" dist\
COPY /B /Y /V "%TORTOISESVN%\bin\TortoisePlink.exe" dist\Plink.exe
COPY /B /Y /V "%TORTOISESVN%\Putty-LICENSE.txt" dist\


ECHO ***************************************************************
ECHO ****** InnoSetup
COPY win32\xpra.iss xpra.iss
"%INNOSETUP%" xpra.iss ^> innosetup.log
"%INNOSETUP%" xpra.iss > innosetup.log
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
SET PATH=%OLDPATH%
