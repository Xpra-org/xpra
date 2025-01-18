[Setup]
AppName=Xpra
AppId=Xpra_is1
AppVersion=5.0.12
AppVerName=Xpra 5.0.12
UninstallDisplayName=Xpra 5.0.12
AppPublisher=xpra.org
AppPublisherURL=http:;xpra.org/
DefaultDirName={pf}\Xpra
DefaultGroupName=Xpra
DisableProgramGroupPage=true
OutputDir=dist
OutputBaseFilename=Xpra_Setup
;Compression=none
;Compression=lzma2/fast
Compression=lzma2/max
SolidCompression=yes
AllowUNCPath=false
VersionInfoVersion=5.0.12
VersionInfoCompany=xpra.org
VersionInfoDescription=multi-platform screen and application forwarding system
WizardImageFile=packaging\MSWindows\xpra-logo.bmp
WizardSmallImageFile=packaging\MSWindows\xpra.bmp
LicenseFile=COPYING
UninstallDisplayIcon={app}\Xpra-Launcher.exe
ArchitecturesInstallIn64BitMode=
ArchitecturesAllowed=

[Dirs]
Name: "{app}"; Flags: uninsalwaysuninstall;
Name: "{commonappdata}\Xpra"; Permissions: users-readexec admins-full;
Name: "{commonappdata}\SSH"; Permissions: users-readexec admins-full; Attribs: notcontentindexed;

[Files]
Source: dist\*; Excludes: "etc\xpra"; DestDir: {app}; Flags: ignoreversion recursesubdirs createallsubdirs;
Source: dist\etc\xpra\*; DestDir: "{commonappdata}\Xpra"; Flags: recursesubdirs createallsubdirs uninsneveruninstall;

[InstallDelete]
Type: filesandordirs; Name: "{app}\lib"

[Icons]
Name: "{group}\Xpra"; Filename: {app}\Xpra.exe; WorkingDir: {app}
Name: "{group}\Xpra Session Browser"; Filename: "{app}\Xpra.exe"; Parameters: "sessions"; WorkingDir: {app}
Name: "{group}\Xpra Homepage"; Filename: "{app}\website.url"
Name: "{group}\Xpra Command Manual"; Filename: "{app}\manual.html"
Name: "{group}\Xpra Shadow Server"; Filename: "{app}\Xpra.exe"; WorkingDir: {app}; Parameters: "shadow --bind-tcp=0.0.0.0:14500,auth=sys,ssl-cert=auto"; IconFilename: {app}\icons\server-connected.ico


[Run]
Filename: {app}\Xpra.exe; Description: {cm:LaunchProgram,xpra}; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCR; Subkey: ".xpra"; ValueType: string; ValueName: ""; ValueData: "Xpra.Session"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "Xpra.Session"; ValueType: string; ValueName: ""; ValueData: "Xpra Session File"; Flags: uninsdeletekey
Root: HKCR; Subkey: "Xpra.Session\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\Xpra-Launcher.exe,0"; Flags: uninsdeletekey
Root: HKCR; Subkey: "Xpra.Session\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Xpra-Launcher.exe"" ""%1"""; Flags: uninsdeletekey

Root: HKCR; Subkey: "xpra"; ValueType: "string"; ValueData: "Xpra TCP Protocol"; Flags: uninsdeletekey
Root: HKCR; Subkey: "xpra"; ValueType: "string"; ValueName: "URL Protocol"; ValueData: ""
Root: HKCR; Subkey: "xpra\DefaultIcon"; ValueType: "string"; ValueData: "{app}\Xpra.exe,0"
Root: HKCR; Subkey: "xpra\shell\open\command"; ValueType: "string"; ValueData: """{app}\Xpra.exe"" ""attach"" ""%1"""

Root: HKCR; Subkey: "xpras"; ValueType: "string"; ValueData: "Xpra SSL Protocol"; Flags: uninsdeletekey
Root: HKCR; Subkey: "xpras"; ValueType: "string"; ValueName: "URL Protocol"; ValueData: ""
Root: HKCR; Subkey: "xpras\DefaultIcon"; ValueType: "string"; ValueData: "{app}\Xpra.exe,0"
Root: HKCR; Subkey: "xpras\shell\open\command"; ValueType: "string"; ValueData: """{app}\Xpra.exe"" ""attach"" ""%1"""

Root: HKCR; Subkey: "xpra+tcp"; ValueType: "string"; ValueData: "Xpra TCP Protocol"; Flags: uninsdeletekey
Root: HKCR; Subkey: "xpra+tcp"; ValueType: "string"; ValueName: "URL Protocol"; ValueData: ""
Root: HKCR; Subkey: "xpra+tcp\DefaultIcon"; ValueType: "string"; ValueData: "{app}\Xpra.exe,0"
Root: HKCR; Subkey: "xpra+tcp\shell\open\command"; ValueType: "string"; ValueData: """{app}\Xpra.exe"" ""attach"" ""%1"""
Root: HKCR; Subkey: "xpratcp"; ValueType: "string"; ValueData: "Xpra TCP Protocol"; Flags: uninsdeletekey
Root: HKCR; Subkey: "xpratcp"; ValueType: "string"; ValueName: "URL Protocol"; ValueData: ""
Root: HKCR; Subkey: "xpratcp\DefaultIcon"; ValueType: "string"; ValueData: "{app}\Xpra.exe,0"
Root: HKCR; Subkey: "xpratcp\shell\open\command"; ValueType: "string"; ValueData: """{app}\Xpra.exe"" ""attach"" ""%1"""

Root: HKCR; Subkey: "xpra+ssl"; ValueType: "string"; ValueData: "Xpra SSL Protocol"; Flags: uninsdeletekey
Root: HKCR; Subkey: "xpra+ssl"; ValueType: "string"; ValueName: "URL Protocol"; ValueData: ""
Root: HKCR; Subkey: "xpra+ssl\DefaultIcon"; ValueType: "string"; ValueData: "{app}\Xpra.exe,0"
Root: HKCR; Subkey: "xpra+ssl\shell\open\command"; ValueType: "string"; ValueData: """{app}\Xpra.exe"" ""attach"" ""%1"""
Root: HKCR; Subkey: "xprassl"; ValueType: "string"; ValueData: "Xpra SSL Protocol"; Flags: uninsdeletekey
Root: HKCR; Subkey: "xprassl"; ValueType: "string"; ValueName: "URL Protocol"; ValueData: ""
Root: HKCR; Subkey: "xprassl\DefaultIcon"; ValueType: "string"; ValueData: "{app}\Xpra.exe,0"
Root: HKCR; Subkey: "xprassl\shell\open\command"; ValueType: "string"; ValueData: """{app}\Xpra.exe"" ""attach"" ""%1"""

Root: HKCR; Subkey: "xpra+tls"; ValueType: "string"; ValueData: "Xpra SSL Protocol"; Flags: uninsdeletekey
Root: HKCR; Subkey: "xpra+tls"; ValueType: "string"; ValueName: "URL Protocol"; ValueData: ""
Root: HKCR; Subkey: "xpra+tls\DefaultIcon"; ValueType: "string"; ValueData: "{app}\Xpra.exe,0"
Root: HKCR; Subkey: "xpra+tls\shell\open\command"; ValueType: "string"; ValueData: """{app}\Xpra.exe"" ""attach"" ""%1"""
Root: HKCR; Subkey: "xpratls"; ValueType: "string"; ValueData: "Xpra SSL Protocol"; Flags: uninsdeletekey
Root: HKCR; Subkey: "xpratls"; ValueType: "string"; ValueName: "URL Protocol"; ValueData: ""
Root: HKCR; Subkey: "xpratls\DefaultIcon"; ValueType: "string"; ValueData: "{app}\Xpra.exe,0"
Root: HKCR; Subkey: "xpratls\shell\open\command"; ValueType: "string"; ValueData: """{app}\Xpra.exe"" ""attach"" ""%1"""

Root: HKCR; Subkey: "xpra+ssh"; ValueType: "string"; ValueData: "Xpra SSH Protocol"; Flags: uninsdeletekey
Root: HKCR; Subkey: "xpra+ssh"; ValueType: "string"; ValueName: "URL Protocol"; ValueData: ""
Root: HKCR; Subkey: "xpra+ssh\DefaultIcon"; ValueType: "string"; ValueData: "{app}\Xpra.exe,0"
Root: HKCR; Subkey: "xpra+ssh\shell\open\command"; ValueType: "string"; ValueData: """{app}\Xpra.exe"" ""attach"" ""%1"""
Root: HKCR; Subkey: "xprassh"; ValueType: "string"; ValueData: "Xpra SSH Protocol"; Flags: uninsdeletekey
Root: HKCR; Subkey: "xprassh"; ValueType: "string"; ValueName: "URL Protocol"; ValueData: ""
Root: HKCR; Subkey: "xprassh\DefaultIcon"; ValueType: "string"; ValueData: "{app}\Xpra.exe,0"
Root: HKCR; Subkey: "xprassh\shell\open\command"; ValueType: "string"; ValueData: """{app}\Xpra.exe"" ""attach"" ""%1"""

Root: HKCR; Subkey: "xpra+ws"; ValueType: "string"; ValueData: "Xpra Websocket Protocol"; Flags: uninsdeletekey
Root: HKCR; Subkey: "xpra+ws"; ValueType: "string"; ValueName: "URL Protocol"; ValueData: ""
Root: HKCR; Subkey: "xpra+ws\DefaultIcon"; ValueType: "string"; ValueData: "{app}\Xpra.exe,0"
Root: HKCR; Subkey: "xpra+ws\shell\open\command"; ValueType: "string"; ValueData: """{app}\Xpra.exe"" ""attach"" ""%1"""
Root: HKCR; Subkey: "xpraws"; ValueType: "string"; ValueData: "Xpra Websocket Protocol"; Flags: uninsdeletekey
Root: HKCR; Subkey: "xpraws"; ValueType: "string"; ValueName: "URL Protocol"; ValueData: ""
Root: HKCR; Subkey: "xpraws\DefaultIcon"; ValueType: "string"; ValueData: "{app}\Xpra.exe,0"
Root: HKCR; Subkey: "xpraws\shell\open\command"; ValueType: "string"; ValueData: """{app}\Xpra.exe"" ""attach"" ""%1"""

Root: HKCR; Subkey: "xpra+wss"; ValueType: "string"; ValueData: "Xpra Secure Websocket Protocol"; Flags: uninsdeletekey
Root: HKCR; Subkey: "xpra+wss"; ValueType: "string"; ValueName: "URL Protocol"; ValueData: ""
Root: HKCR; Subkey: "xpra+wss\DefaultIcon"; ValueType: "string"; ValueData: "{app}\Xpra.exe,0"
Root: HKCR; Subkey: "xpra+wss\shell\open\command"; ValueType: "string"; ValueData: """{app}\Xpra.exe"" ""attach"" ""%1"""
Root: HKCR; Subkey: "xprawss"; ValueType: "string"; ValueData: "Xpra Secure Websocket Protocol"; Flags: uninsdeletekey
Root: HKCR; Subkey: "xprawss"; ValueType: "string"; ValueName: "URL Protocol"; ValueData: ""
Root: HKCR; Subkey: "xprawss\DefaultIcon"; ValueType: "string"; ValueData: "{app}\Xpra.exe,0"
Root: HKCR; Subkey: "xprawss\shell\open\command"; ValueType: "string"; ValueData: """{app}\Xpra.exe"" ""attach"" ""%1"""


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
  //if Cancel is pressed
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
  //if Cancel is pressed
  if nMsgBoxResult = IDCANCEL then
  begin
    Result := False;
  end;
end;

procedure PostInstall();
var
  cert, config, saved_config, args, openssl, ssh_keygen, rsa_key: string;
  ResultCode: integer;
begin
  Log('PostInstall()');
  cert := ExpandConstant('{commonappdata}\Xpra\ssl-cert.pem');
  if (NOT FileExists(cert)) then
  begin
    config := ExpandConstant('{app}\etc\ssl\openssl.cnf');
    args := 'req -new -newkey rsa:4096 -days 365 -nodes -x509 -config "'+config+'" -subj "/C=US/ST=Denial/L=Springfield/O=Dis/CN=localhost" -out "'+cert+'" -keyout "'+cert+'"';
    openssl := ExpandConstant('{app}\OpenSSL.exe');
    if (FileExists(openssl)) then
    begin
      Log('PostInstall() generating ssl-cert.pem');
      Exec(openssl, args, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end;
  end;
  //move old config file:
  config := ExpandConstant('{app}\xpra.conf');
  saved_config := ExpandConstant('{app}\etc\xpra.conf.bak');
  if (FileExists(config)) then
  begin
	RenameFile(config, saved_config);
  end;
  //ssh host key:
  ssh_keygen := ExpandConstant('{app}\ssh-keygen.exe');
  if (FileExists(ssh_keygen)) then
  begin
    Log('found ssh_keygen');
    rsa_key := ExpandConstant('{commonappdata}\SSH\ssh_host_rsa_key');
    if (NOT FileExists(rsa_key)) then
    begin
      Log('generating rsa key');
      args := '-P "" -t rsa -b 4096 -f "'+rsa_key+'"';
      Exec(ssh_keygen, args, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end;
  end else begin
    Log('ssh-keygen.exe not found');
  end;
  //store installation path:
  RegWriteStringValue(HKEY_LOCAL_MACHINE, 'Software\Xpra',
    'InstallPath', ExpandConstant('{app}'));
  Log('PostInstall() done');
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

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep=ssInstall) then
  begin
    if (IsUpgrade()) then
    begin
      UnInstallOldVersion();
    end;
  end;
  if (CurStep=ssPostInstall) then
  begin
    PostInstall();
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep=usPostUninstall) then
  begin
    //RegDeleteKeyIncludingSubkeys(HKEY_LOCAL_MACHINE, 'Software\Xpra');
    if RegDeleteValue(HKEY_LOCAL_MACHINE, 'Software\Xpra', 'InstallPath') then
      RegDeleteKeyIfEmpty(HKEY_LOCAL_MACHINE, 'Software\Xpra');
  end;
end;
