; BTCRechnung Windows Installer (Inno Setup 6)
; Nutzung: iscc scripts/setup.iss  (benoetigt PyInstaller-Build in dist/BTCRechnung)

#define MyAppName "BTCRechnung"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "BTCRechnung"
#define MyAppURL "https://btcrechnung.de"
#define MyAppExeName "BTCRechnung.exe"

[Setup]
AppId={{3F2A1B7C-BTCR-ECHN-UNG0-000000000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\BTCRechnung
DefaultGroupName=BTCRechnung
DisableProgramGroupPage=yes
OutputDir=build
OutputBaseFilename=btcrechnung-setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Files]
Source: "..\dist\BTCRechnung\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\BTCRechnung"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\BTCRechnung"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Desktop-Symbol erstellen"; GroupDescription: "Zusaetzlich:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "BTCRechnung starten"; Flags: nowait postinstall skipifsilent
