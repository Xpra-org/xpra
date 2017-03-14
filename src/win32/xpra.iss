[Setup]
AppName=Xpra
AppVerName=Xpra 1.0.5
AppPublisher=xpra.org
AppPublisherURL=http://xpra.org/
DefaultDirName={pf}\Xpra
DefaultGroupName=Xpra
DisableProgramGroupPage=true
OutputBaseFilename=Xpra_Setup
//Compression=none
//Compression=lzma2/fast
Compression=lzma2/max
SolidCompression=yes
AllowUNCPath=false
VersionInfoVersion=1.0.5
VersionInfoCompany=xpra.org
VersionInfoDescription=multi-platform screen and application forwarding system
WizardImageFile=win32\xpra-logo.bmp
WizardSmallImageFile=win32\xpra.bmp
LicenseFile=COPYING
UninstallDisplayIcon={app}\Xpra-Launcher.exe

[Dirs]
Name: {app}; Flags: uninsalwaysuninstall;

[Files]
Source: dist\*; DestDir: {app}; Flags: ignoreversion recursesubdirs createallsubdirs;
Source: dist\etc\xpra\*; DestDir: "{commonappdata}\Xpra"; Flags: recursesubdirs createallsubdirs onlyifdoesntexist uninsneveruninstall; AfterInstall: PostInstall()

[Icons]
Name: "{group}\Xpra"; Filename: {app}\Xpra-Launcher.exe; WorkingDir: {app}
Name: "{group}\Xpra Homepage"; Filename: "{app}\website.url"
Name: "{group}\Xpra Command Manual"; Filename: "{app}\manual.html"
Name: "{group}\Xpra Shadow Server"; Filename: {app}\Xpra.exe; WorkingDir: {app}; Parameters: "shadow --bind-tcp=0.0.0.0:14500 --tcp-auth=sys --ssl-cert=""{commonappdata}\Xpra\ssl-cert.pem"""; IconFilename: {app}\icons\server-connected.ico


[Run]
Filename: {app}\Xpra-Launcher.exe; Description: {cm:LaunchProgram,xpra}; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCR; Subkey: ".xpra"; ValueType: string; ValueName: ""; ValueData: "Xpra.Session"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "Xpra.Session"; ValueType: string; ValueName: ""; ValueData: "Xpra Session File"; Flags: uninsdeletekey
Root: HKCR; Subkey: "Xpra.Session\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\Xpra-Launcher.exe,0"; Flags: uninsdeletekey
Root: HKCR; Subkey: "Xpra.Session\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Xpra-Launcher.exe"" ""%1"""; Flags: uninsdeletekey

Root: HKCR; Subkey: "xpra"; ValueType: "string"; ValueData: "URL:Custom Protocol"; Flags: uninsdeletekey
Root: HKCR; Subkey: "xpra"; ValueType: "string"; ValueName: "URL Protocol"; ValueData: ""
Root: HKCR; Subkey: "xpra\DefaultIcon"; ValueType: "string"; ValueData: "{app}\Xpra.exe,0"
Root: HKCR; Subkey: "xpra\shell\open\command"; ValueType: "string"; ValueData: """{app}\Xpra.exe"" ""attach"" ""%1"""

Root: HKCR; Subkey: "xpras"; ValueType: "string"; ValueData: "URL:Custom Protocol"; Flags: uninsdeletekey
Root: HKCR; Subkey: "xpras"; ValueType: "string"; ValueName: "URL Protocol"; ValueData: ""
Root: HKCR; Subkey: "xpras\DefaultIcon"; ValueType: "string"; ValueData: "{app}\Xpra.exe,0"
Root: HKCR; Subkey: "xpras\shell\open\command"; ValueType: "string"; ValueData: """{app}\Xpra.exe"" ""attach"" ""%1"""

[Code]
function IsAppRunning(const FileName : string): Boolean;
var
    FSWbemLocator: Variant;
    FWMIService   : Variant;
    FWbemObjectSet: Variant;
begin
    Result := false;
    try
	    FSWbemLocator := CreateOleObject('WBEMScripting.SWBEMLocator');
	    FWMIService := FSWbemLocator.ConnectServer('', 'root\CIMV2', '', '');
	    FWbemObjectSet := FWMIService.ExecQuery(Format('SELECT Name FROM Win32_Process Where Name="%s"',[FileName]));
	    Result := (FWbemObjectSet.Count > 0);
	    FWbemObjectSet := Unassigned;
	    FWMIService := Unassigned;
	    FSWbemLocator := Unassigned;
	except
		//MsgBox('Warning: failed to check for existing process', mbError, MB_OK);
	end;
end;


function InitializeSetup(): Boolean;
var
  nMsgBoxResult: Integer;
begin
  Result := True;
  while (IsAppRunning('Xpra_cmd.exe') or IsAppRunning('Xpra.exe') or IsAppRunning('Xpra-Launcher.exe')) and (nMsgBoxResult <> IDCANCEL) do
  begin
      nMsgBoxResult := MsgBox('Xpra is already running, you must stop it to proceed.', mbInformation, MB_RETRYCANCEL);
  end;
  // if Cancel is pressed
  if nMsgBoxResult = IDCANCEL then
  begin
    Result := False;
  end;
end;

function InitializeUninstall(): Boolean;
var
  nMsgBoxResult: Integer;
begin
  Result := True;
  while (IsAppRunning('Xpra_cmd.exe') or IsAppRunning('Xpra.exe') or IsAppRunning('Xpra-Launcher.exe')) and (nMsgBoxResult <> IDCANCEL) do
  begin
      nMsgBoxResult := MsgBox('Xpra is still running, you must stop it to be able to uninstall everything.', mbInformation, MB_RETRYCANCEL);
  end;
  // if Cancel is pressed
  if nMsgBoxResult = IDCANCEL then
  begin
    Result := False;
  end;
end;

procedure PostInstall();
var
  cert, config, saved_config, args, cmd: string;
  ResultCode: integer;
begin
  cert := ExpandConstant('{commonappdata}\Xpra\ssl-cert.pem');
  if (NOT FileExists(cert)) then
  begin
    config := ExpandConstant('{app}\openssl.cfg');
    args := 'req -new -newkey rsa:4096 -days 365 -nodes -x509 -config "'+config+'" -subj "/C=US/ST=Denial/L=Springfield/O=Dis/CN=localhost" -out "'+cert+'" -keyout "'+cert+'"';
    cmd := ExpandConstant('{app}\OpenSSL.exe');
	Exec(cmd, args, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
  // move old config file:
  config := ExpandConstant('{app}\xpra.conf');
  saved_config := ExpandConstant('{app}\etc\xpra.conf.bak');
  if (FileExists(config)) then
  begin
	RenameFile(config, saved_config);
  end;
end;


function GetUninstallString(): String;
var
  sUnInstPath: String;
  sUnInstallString: String;
begin
  sUnInstPath := ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\Xpra_is1');
  sUnInstallString := '';
  if not RegQueryStringValue(HKLM, sUnInstPath, 'UninstallString', sUnInstallString) then
    RegQueryStringValue(HKCU, sUnInstPath, 'UninstallString', sUnInstallString);
  Result := sUnInstallString;
end;


function IsUpgrade(): Boolean;
begin
  Result := (GetUninstallString() <> '');
end;


function UnInstallOldVersion(): Integer;
var
  sUnInstallString: String;
  iResultCode: Integer;
begin
// Return Values:
// 1 - uninstall string is empty
// 2 - error executing the UnInstallString
// 3 - successfully executed the UnInstallString

  // default return value
  Result := 0;

  // get the uninstall string of the old app
  sUnInstallString := GetUninstallString();
  if sUnInstallString <> '' then begin
    sUnInstallString := RemoveQuotes(sUnInstallString);
    if Exec(sUnInstallString, '/SILENT /NORESTART /SUPPRESSMSGBOXES','', SW_HIDE, ewWaitUntilTerminated, iResultCode) then
      Result := 3
    else
      Result := 2;
  end else
    Result := 1;
end;

procedure CurStepChanged(CurrentStep: TSetupStep);
var
  Version: TWindowsVersion;
begin
  if (CurrentStep=ssInstall) then
  begin
    if (IsUpgrade()) then
    begin
      UnInstallOldVersion();
    end;
  end;
  GetWindowsVersionEx(Version);
  if Version.NTPlatform and (Version.Major = 5) then
  begin
	if (CurrentStep = ssPostInstall) then
    begin
	  SuppressibleMsgBox('Warning: using an older version of Plink for SSH support on Windows XP,' + #13#10 +
	   					 'use at your own risk.',
	  	mbInformation, MB_OK, IDOK);
      FileCopy(ExpandConstant('{app}\TortoisePlink-XP\msvcp110.dll'), ExpandConstant('{app}\msvcp110.dll'), False);
      FileCopy(ExpandConstant('{app}\TortoisePlink-XP\msvcr110.dll'), ExpandConstant('{app}\msvcr110.dll'), False);
      FileCopy(ExpandConstant('{app}\TortoisePlink-XP\Plink.exe'), ExpandConstant('{app}\Plink.exe'), False);
	end;
  end;
end;