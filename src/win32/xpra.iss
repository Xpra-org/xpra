[Setup]
AppName=Xpra
AppVerName=Xpra 0.17.0
AppPublisher=devloop
AppPublisherURL=http://xpra.org/
DefaultDirName={pf}\Xpra
DefaultGroupName=Xpra
DisableProgramGroupPage=true
OutputBaseFilename=Xpra_Setup
Compression=lzma
SolidCompression=true
AllowUNCPath=false
VersionInfoVersion=0.17.0
VersionInfoCompany=devloop
VersionInfoDescription=screen for X
WizardImageFile=win32\xpra-logo.bmp
WizardSmallImageFile=win32\xpra.bmp
LicenseFile=COPYING
UninstallDisplayIcon={app}\Xpra-Launcher.exe

[Dirs]
Name: {app}; Flags: uninsalwaysuninstall;

[Files]
Source: dist\*; DestDir: {app}; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: {group}\Xpra; Filename: {app}\Xpra-Launcher.exe; WorkingDir: {app}
Name: "{group}\Xpra Homepage"; Filename: "{app}\website.url"
Name: "{group}\Xpra Command Manual"; Filename: "{app}\manual.html"

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
