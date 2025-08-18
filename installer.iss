; installer.iss — Script de Inno Setup (Windows)
; -----------------------------------------------------------
; Empaqueta la app (PyInstaller) + prerequisitos opcionales.
; Los prereqs se copian a {tmp} y se ejecutan con /quiet.
; En Windows 7 SP1 se puede aplicar KB2999226 (UCRT) si está incluido.
; -----------------------------------------------------------

#define MyAppName     "Sistema de Gestión"
#define MyAppVersion  "1.0.0"
#define MyAppPublisher "Synapse IT"
#define MyAppExeName  "SistemaGestion.exe"
#define PrereqsDir    "assets\prereqs"

[Setup]
AppId={{A1B2C3D4-E5F6-4711-8899-001122334455}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=out
OutputBaseFilename=Instalador_{#MyAppName}_{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
MinVersion=6.1sp1

[Files]
; App (salida de PyInstaller)
Source: ".\dist\SistemaGestion\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

; === PREREQS (incluidos solo si existen) ===
#ifexist "{#PrereqsDir}\vc_redist.x64.exe"
Source: "{#PrereqsDir}\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: ignoreversion deleteafterinstall
#endif

#ifexist "{#PrereqsDir}\vc_redist.x86.exe"
Source: "{#PrereqsDir}\vc_redist.x86.exe"; DestDir: "{tmp}"; Flags: ignoreversion deleteafterinstall
#endif

#ifexist "{#PrereqsDir}\Windows6.1-KB2999226-x64.msu"
Source: "{#PrereqsDir}\Windows6.1-KB2999226-x64.msu"; DestDir: "{tmp}"; Flags: ignoreversion deleteafterinstall
#endif

#ifexist "{#PrereqsDir}\Windows6.1-KB2999226-x86.msu"
Source: "{#PrereqsDir}\Windows6.1-KB2999226-x86.msu";  DestDir: "{tmp}"; Flags: ignoreversion deleteafterinstall
#endif

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Run]
; --- (Opcional) KB2999226 para Windows 7 SP1 ---
Filename: "{sys}\wusa.exe"; Parameters: """{tmp}\Windows6.1-KB2999226-x64.msu"" /quiet /norestart"; StatusMsg: "Aplicando actualización (KB2999226 x64)..."; Check: IsWindows7() and IsWin64 and FileExists(ExpandConstant('{tmp}\Windows6.1-KB2999226-x64.msu')); Flags: waituntilterminated
Filename: "{sys}\wusa.exe"; Parameters: """{tmp}\Windows6.1-KB2999226-x86.msu"" /quiet /norestart"; StatusMsg: "Aplicando actualización (KB2999226 x86)..."; Check: IsWindows7() and (not IsWin64) and FileExists(ExpandConstant('{tmp}\Windows6.1-KB2999226-x86.msu')); Flags: waituntilterminated

; --- VC++ 2015–2022 (solo si no está instalado) ---
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/quiet /norestart"; StatusMsg: "Instalando Microsoft Visual C++ Redistributable (x64)..."; Check: IsWin64 and (not IsVCRedistInstalledX64()) and FileExists(ExpandConstant('{tmp}\vc_redist.x64.exe')); Flags: waituntilterminated
Filename: "{tmp}\vc_redist.x86.exe"; Parameters: "/quiet /norestart"; StatusMsg: "Instalando Microsoft Visual C++ Redistributable (x86)..."; Check: (not IsWin64) and (not IsVCRedistInstalledX86()) and FileExists(ExpandConstant('{tmp}\vc_redist.x86.exe')); Flags: waituntilterminated

; --- Lanzar la app al finalizar ---
Filename: "{app}\{#MyAppExeName}"; Description: "Iniciar {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function IsWindows7: Boolean;
var v: TWindowsVersion;
begin
  GetWindowsVersionEx(v);
  Result := (v.Major = 6) and (v.Minor = 1);  { 6.1 = Windows 7 }
end;

function IsVCRedistInstalledX64: Boolean;
var Installed: Cardinal;
begin
  Result := False;
  if IsWin64 then
    Result := RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) and (Installed = 1);
end;

function IsVCRedistInstalledX86: Boolean;
var Installed: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM32, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x86', 'Installed', Installed) and (Installed = 1);
end;

