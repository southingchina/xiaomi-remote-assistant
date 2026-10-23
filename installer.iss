#define AppVersion "0.1.1"
[Setup]
AppId={{99F53938-D51E-48A6-94D9-CA414F310FB8}
AppName=小米遥控助手（测试版）
AppVersion={#AppVersion}
AppPublisher=Remote Assistant
DefaultDirName={localappdata}\Programs\XiaomiRemoteAssistant
DefaultGroupName=小米遥控助手
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0
OutputDir=release
OutputBaseFilename=XiaomiRemoteAssistant-0.1.1-test-win-x64-Setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\XiaomiRemoteAssistant.exe
CloseApplications=yes
RestartApplications=no
InfoAfterFile=TESTING.txt

[Tasks]
Name: desktopicon; Description: "创建桌面快捷方式"

[Files]
Source: "dist\XiaomiRemoteAssistant\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "TESTING.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "release\XiaomiRemoteAssistant-0.1.1-source.zip"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\小米遥控助手"; Filename: "{app}\XiaomiRemoteAssistant.exe"; Tasks: desktopicon
Name: "{group}\小米遥控助手"; Filename: "{app}\XiaomiRemoteAssistant.exe"
Name: "{group}\测试说明"; Filename: "{app}\TESTING.txt"
Name: "{group}\卸载小米遥控助手"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\XiaomiRemoteAssistant.exe"; Description: "打开小米遥控助手"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\XiaomiRemoteCore.exe"; Parameters: "--stop"; Flags: runhidden waituntilterminated; RunOnceId: "StopRemoteAssistant"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "XiaomiRemoteAssistant"; Flags: uninsdeletevalue
