; === 文件路径: installer/FileMaster.iss ===
; FileMaster 安装包脚本（Inno Setup 6）
; 编译：& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\FileMaster.iss
; 产物：installer\Output\FileMaster-Setup-<版本>.exe

#define MyAppName "FileMaster"
#define MyAppDisplayName "FileMaster 智能文件管家"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "FileMaster"
#define MyAppExeName "FileMaster.exe"

[Setup]
; AppId 固定不变，升级安装时才能识别为同一程序
AppId={{3F2A9C4E-7B1D-4E8A-9C5F-2D6A1B8E4F07}}
AppName={#MyAppDisplayName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppDisplayName}
OutputDir=Output
OutputBaseFilename=FileMaster-Setup-{#MyAppVersion}
SetupIconFile=..\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; exe 为 64 位，安装到 64 位 Program Files
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; 单文件 exe 已内置全部运行环境，复制这一个文件即可
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppDisplayName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppDisplayName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
