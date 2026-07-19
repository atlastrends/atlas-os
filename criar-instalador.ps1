# ============================================================
# ATLAS OS - criar-instalador.ps1
#
# Gera UM UNICO arquivo: ATLAS-Instalador.exe
# Esse .exe e um instalador (assistente) que ja traz TUDO dentro:
#   - o programa ATLAS completo
#   - o painel ja compilado (nao precisa de Node no outro PC)
#   - o seu arquivo .env (contas e chaves)   <-- IMPORTANTE
#   - o componente do link publico (cloudflared), se existir
#
# COMO USAR (faca isto UMA vez, NESTE computador):
#   1) De dois cliques neste arquivo (ou rode no PowerShell).
#   2) Espere terminar.
#   3) Pegue o arquivo gerado em:  dist-installer\ATLAS-Instalador.exe
#   4) Leve SO esse .exe para o outro computador e instale como
#      qualquer programa. Nao precisa copiar mais nada.
#
# Nao precisa de admin nem de baixar programas: o instalador e
# montado com o compilador que ja vem dentro do Windows (.NET).
#
# OBS: como o .env vai DENTRO do instalador, trate o .exe como
# um arquivo confidencial (nao publique na internet).
# ============================================================

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$root = $PSScriptRoot

function Write-Step($m) { Write-Host "[BUILD] $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "[BUILD] $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "[BUILD] $m" -ForegroundColor Yellow }
function Write-Err($m)  { Write-Host "[BUILD] $m" -ForegroundColor Red }

try {
    # --------------------------------------------------------
    # 1) Compila o painel (frontend) para incluir pronto no pacote.
    #    Assim o outro PC NAO precisa de Node.js instalado.
    # --------------------------------------------------------
    if (Test-Path (Join-Path $root "frontend\package.json")) {
        $npm = Get-Command npm -ErrorAction SilentlyContinue
        if ($npm) {
            Write-Step "Compilando o painel para incluir no instalador ..."
            Push-Location (Join-Path $root "frontend")
            try {
                if (-not (Test-Path ".\node_modules")) { npm install } else { npm install --no-audit --no-fund }
                npm run build
            } finally { Pop-Location }
        } else {
            Write-Warn "Node.js (npm) nao encontrado: vou usar o painel ja compilado, se existir."
        }
    }
    if (-not (Test-Path (Join-Path $root "frontend\dist\index.html"))) {
        throw "O painel compilado (frontend\dist) nao existe. Instale o Node.js e rode de novo."
    }

    # --------------------------------------------------------
    # 2) Monta a pasta com os arquivos que vao DENTRO do instalador.
    #    Copia tudo, menos lixo e coisas especificas deste PC.
    #    (O .env E INCLUIDO de proposito.)
    # --------------------------------------------------------
    $build   = Join-Path $root "build"
    $payload = Join-Path $build "payload"
    if (Test-Path $build) { Remove-Item $build -Recurse -Force }
    New-Item -ItemType Directory -Path $payload -Force | Out-Null

    Write-Step "Preparando os arquivos do programa ..."
    $excludeDirs = @(
        ".git", ".venv-dash", "node_modules", "storage", "data",
        "outputs", "output_videos", "output_metadata", "temp_media",
        "logs", "backups", "build", "dist-installer"
    ) | ForEach-Object { Join-Path $root $_ }

    $excludeFiles = @(
        (Join-Path $root "atlas_local.db")
    )

    $roboArgs = @($root, $payload, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:1", "/W:1")
    $roboArgs += "/XD"; $roboArgs += $excludeDirs
    $roboArgs += "/XF"; $roboArgs += $excludeFiles
    $roboArgs += "*.bak"; $roboArgs += "*.before_*"; $roboArgs += "*.backup"; $roboArgs += "*.backup_*"
    & robocopy @roboArgs | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Falha ao preparar os arquivos (robocopy $LASTEXITCODE)." }

    # Confirma que o .env foi incluido (e o coracao das contas/chaves).
    if (Test-Path (Join-Path $payload ".env")) {
        Write-Ok "Seu .env foi incluido no instalador (contas e chaves)."
    } else {
        Write-Warn "Atencao: nao havia um .env neste PC. O outro PC comecara sem contas configuradas."
    }

    # --------------------------------------------------------
    # 3) Compacta tudo em um unico .zip (sera embutido no .exe).
    # --------------------------------------------------------
    Write-Step "Compactando o programa ..."
    $zipInside = Join-Path $build "payload.zip"
    Compress-Archive -Path (Join-Path $payload "*") -DestinationPath $zipInside -Force

    # --------------------------------------------------------
    # 4) Codigo do instalador (C#). Ele extrai o programa, cria os
    #    atalhos e abre o ATLAS. Roda por usuario, sem admin.
    # --------------------------------------------------------
    $cs = @'
using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Windows.Forms;

class AtlasInstaller
{
    [STAThread]
    static void Main()
    {
        try
        {
            string target = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs", "ATLAS OS");

            DialogResult ask = MessageBox.Show(
                "Deseja instalar o ATLAS OS neste computador?\n\nSera instalado em:\n" + target,
                "ATLAS OS - Instalador",
                MessageBoxButtons.OKCancel, MessageBoxIcon.Information);
            if (ask != DialogResult.OK) return;

            Directory.CreateDirectory(target);

            string tmpZip = Path.Combine(Path.GetTempPath(),
                "atlas_payload_" + Guid.NewGuid().ToString("N") + ".zip");
            Assembly asm = Assembly.GetExecutingAssembly();
            using (Stream s = asm.GetManifestResourceStream("payload.zip"))
            using (FileStream f = File.Create(tmpZip))
            {
                s.CopyTo(f);
            }

            using (ZipArchive za = ZipFile.OpenRead(tmpZip))
            {
                foreach (ZipArchiveEntry entry in za.Entries)
                {
                    string dest = Path.Combine(target, entry.FullName);
                    if (string.IsNullOrEmpty(entry.Name))
                    {
                        Directory.CreateDirectory(dest);
                        continue;
                    }
                    Directory.CreateDirectory(Path.GetDirectoryName(dest));
                    entry.ExtractToFile(dest, true);
                }
            }
            try { File.Delete(tmpZip); } catch { }

            string bat = Path.Combine(target, "ATLAS.bat");
            CreateShortcut(Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.Desktop), "ATLAS OS.lnk"), bat, target);
            CreateShortcut(Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.Programs), "ATLAS OS.lnk"), bat, target);

            MessageBox.Show(
                "ATLAS OS instalado com sucesso!\n\nUm atalho foi criado na Area de Trabalho.\nO painel vai abrir agora.",
                "ATLAS OS", MessageBoxButtons.OK, MessageBoxIcon.Information);

            ProcessStartInfo psi = new ProcessStartInfo(bat);
            psi.WorkingDirectory = target;
            psi.UseShellExecute = true;
            Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show("Falha na instalacao:\n" + ex.Message,
                "ATLAS OS", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    static void CreateShortcut(string lnkPath, string targetPath, string workDir)
    {
        try
        {
            Type t = Type.GetTypeFromProgID("WScript.Shell");
            object shell = Activator.CreateInstance(t);
            object sc = t.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod,
                null, shell, new object[] { lnkPath });
            Type st = sc.GetType();
            st.InvokeMember("TargetPath", BindingFlags.SetProperty, null, sc, new object[] { targetPath });
            st.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, sc, new object[] { workDir });
            st.InvokeMember("IconLocation", BindingFlags.SetProperty, null, sc, new object[] { "shell32.dll,220" });
            st.InvokeMember("Save", BindingFlags.InvokeMethod, null, sc, null);
        }
        catch { }
    }
}
'@
    $csPath = Join-Path $build "installer.cs"
    Set-Content -Path $csPath -Value $cs -Encoding utf8

    # --------------------------------------------------------
    # 5) Compila o instalador final (.exe) com o compilador do Windows.
    # --------------------------------------------------------
    $fw = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319"
    $csc = Join-Path $fw "csc.exe"
    if (-not (Test-Path $csc)) { throw ".NET Framework (csc.exe) nao encontrado neste Windows." }

    $distOut = Join-Path $root "dist-installer"
    New-Item -ItemType Directory -Path $distOut -Force | Out-Null
    $finalExe = Join-Path $distOut "ATLAS-Instalador.exe"
    if (Test-Path $finalExe) { Remove-Item $finalExe -Force }

    Write-Step "Montando o instalador final (.exe) ..."
    $refs = @(
        "System.dll", "System.Core.dll",
        "System.IO.Compression.dll", "System.IO.Compression.FileSystem.dll",
        "System.Windows.Forms.dll", "System.Drawing.dll"
    ) | ForEach-Object { "/reference:" + (Join-Path $fw $_) }

    $cscArgs = @(
        "/nologo", "/target:winexe",
        "/out:$finalExe",
        "/resource:$zipInside,payload.zip"
    ) + $refs + @($csPath)

    & $csc @cscArgs
    if ($LASTEXITCODE -ne 0) { throw "O compilador retornou erro ($LASTEXITCODE)." }
    if (-not (Test-Path $finalExe)) { throw "O instalador nao foi gerado." }

    # Limpa a pasta temporaria de montagem.
    try { Remove-Item $build -Recurse -Force -ErrorAction SilentlyContinue } catch {}

    $mb = [math]::Round((Get-Item $finalExe).Length / 1MB, 1)
    Write-Host ""
    Write-Ok "PRONTO! Instalador criado com sucesso ($mb MB):"
    Write-Host "   $finalExe" -ForegroundColor Green
    Write-Host ""
    Write-Host "Leve SO esse arquivo para o outro computador e de dois cliques nele." -ForegroundColor Yellow
    Write-Host "Ele instala o ATLAS, cria o atalho na Area de Trabalho e ja abre o painel." -ForegroundColor Yellow
    Write-Host "Nao precisa copiar mais nenhum arquivo (o .env ja vai dentro)." -ForegroundColor Yellow
    Write-Host ""
    Write-Warn "Guarde esse .exe com cuidado: ele contem suas contas e chaves."
}
catch {
    Write-Err "Falha ao criar o instalador: $($_.Exception.Message)"
    Read-Host "Pressione ENTER para fechar"
    exit 1
}

Read-Host "Pressione ENTER para fechar"
