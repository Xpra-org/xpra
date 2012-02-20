[Setup]
AppName=Xpra
AppVerName=Xpra 0.1.0
AppPublisher=devloop
AppPublisherURL=http://xpra.org/
DefaultDirName={pf}\Xpra
DefaultGroupName=Xpra
DisableProgramGroupPage=true
OutputBaseFilename=Xpra_Setup
Compression=lzma
SolidCompression=true
AllowUNCPath=false
VersionInfoVersion=0.1.0
VersionInfoCompany=devloop
VersionInfoDescription=screen for X

[Dirs]
Name: {app}; Flags: uninsalwaysuninstall;

[Files]
Source: dist\*; DestDir: {app}; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: {group}\Xpra; Filename: {app}\Xpra-Launcher.exe; WorkingDir: {app}
Name: "{group}\Xpra Homepage"; Filename: "{app}\website.url"

[Run]
Filename: {app}\Xpra-Launcher.exe; Description: {cm:LaunchProgram,xpra}; Flags: nowait postinstall skipifsilent
