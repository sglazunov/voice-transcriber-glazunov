; Inno Setup script for the Voice Transcriber desktop app.
; Build the .exe first (build_desktop.bat), then open this file in Inno Setup
; (https://jrsoftware.org/isdl.php) and press Compile to produce Setup.exe.

#define MyAppName "Voice Transcriber"
#define MyAppVersion "1.0"
#define MyAppPublisher "sglazunov"
#define MyAppExeName "VoiceTranscriber.exe"

[Setup]
AppId={{8E6F7A20-2C2B-4E0A-9C7E-VOICETX0001}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\VoiceTranscriber
DefaultGroupName={#MyAppName}
OutputBaseFilename=VoiceTranscriber-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Per-user install needs no admin; flip to admin if you target Program Files.
PrivilegesRequired=lowest
DisableProgramGroupPage=yes

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"
Name: "installollama"; Description: "Установить локальный ИИ (Ollama) и модель — для протоколов оффлайн (~4.7 ГБ)"; GroupDescription: "Локальный ИИ:"

[Files]
; The whole onedir output from PyInstaller.
Source: "dist\VoiceTranscriber\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; Helper that installs Ollama + pulls/creates the model, plus the Modelfile.
Source: "setup_ollama.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "Modelfile"; DestDir: "{app}"; Flags: ignoreversion
; Visual C++ Redistributable (x64) — needed at runtime by onnxruntime (the VAD
; used in transcription). OPTIONAL to bundle: download VC_redist.x64.exe from
; https://aka.ms/vs/17/release/vc_redist.x64.exe and place it next to this .iss
; before compiling. If absent, the installer falls back to winget.
Source: "VC_redist.x64.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Visual C++ Redistributable — required at runtime by onnxruntime, regardless of
; the chosen AI engine. Installed automatically (skipped if already present).
; Prefer the bundled redist (self-elevates via UAC); fall back to winget.
Filename: "{app}\VC_redist.x64.exe"; Parameters: "/install /quiet /norestart"; \
    StatusMsg: "Установка Visual C++ Redistributable..."; \
    Flags: runhidden waituntilterminated; Check: NeedVCBundled
Filename: "{cmd}"; Parameters: "/c winget install --id Microsoft.VCRedist.2015+.x64 --silent --accept-package-agreements --accept-source-agreements"; \
    StatusMsg: "Установка Visual C++ Redistributable..."; \
    Flags: runhidden waituntilterminated; Check: NeedVCWinget
; Optionally set up the local AI engine right after install.
Filename: "{app}\setup_ollama.bat"; Description: "Установить локальный ИИ (Ollama) и модель"; \
    Flags: postinstall runascurrentuser; Tasks: installollama
; Offer to launch the app at the end.
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; \
    Flags: postinstall nowait skipifsilent

[Code]
function VCInstalled: Boolean;
var
  installed: Cardinal;
begin
  // VC++ 2015-2022 x64 runtime marks itself here when present.
  Result := RegQueryDWordValue(HKLM,
    'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', installed)
    and (installed = 1);
end;

function BundledVCExists: Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\VC_redist.x64.exe'));
end;

function NeedVCBundled: Boolean;
begin
  Result := (not VCInstalled) and BundledVCExists;
end;

function NeedVCWinget: Boolean;
begin
  Result := (not VCInstalled) and (not BundledVCExists);
end;
