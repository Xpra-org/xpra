[Setup]
AppName=Xpra
AppVerName=Xpra 0.8.2
AppPublisher=devloop
AppPublisherURL=http://xpra.org/
DefaultDirName={pf}\Xpra
DefaultGroupName=Xpra
DisableProgramGroupPage=true
OutputBaseFilename=Xpra_Setup
Compression=lzma
SolidCompression=true
AllowUNCPath=false
VersionInfoVersion=0.8.2
VersionInfoCompany=devloop
VersionInfoDescription=screen for X
WizardImageFile=win32\xpra-logo.bmp
WizardSmallImageFile=win32\xpra.bmp
LicenseFile=COPYING

[Dirs]
Name: {app}; Flags: uninsalwaysuninstall;

[Files]
Source: dist\*; DestDir: {app}; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: {group}\Xpra; Filename: {app}\Xpra-Launcher.exe; WorkingDir: {app}
Name: "{group}\Xpra Homepage"; Filename: "{app}\website.url"

[Run]
Filename: {app}\Xpra-Launcher.exe; Description: {cm:LaunchProgram,xpra}; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCR; Subkey: ".xpra"; ValueType: string; ValueName: ""; ValueData: "Xpra.Session"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "Xpra.Session"; ValueType: string; ValueName: ""; ValueData: "Xpra Session File"; Flags: uninsdeletekey
Root: HKCR; Subkey: "Xpra.Session\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\Xpra-Launcher.exe,0"; Flags: uninsdeletekey
Root: HKCR; Subkey: "Xpra.Session\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Xpra-Launcher.exe"" ""%1"""; Flags: uninsdeletekey
