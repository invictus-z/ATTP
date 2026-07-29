# 构建并导出 protocol/tool/agent 三镜像为 tar.gz（gzip 压缩），供 GitHub Release 离线分发。
# 评委 docker load 后镜像以 attp-*:latest tag 进本地，docker compose up 直接命中。
#
# 用法:  powershell -ExecutionPolicy Bypass -File docker\save-images.ps1 [version]
$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '..'))

$Ver = if ($args[0]) { $args[0] } else { '0.2.0-alpha.1.demo' }
$Images = @(
  'attp-protocol:latest',
  'attp-tool:latest',
  'attp-agent:latest'
)

Write-Host "▶ docker compose build"
docker compose -f docker-compose.yml build
if ($LASTEXITCODE -ne 0) { throw "docker compose build failed" }

$ReleaseDir = "docker\release"
New-Item -ItemType Directory -Force $ReleaseDir | Out-Null
$Tar = "$ReleaseDir\attp-images-$Ver.tar"
$Out = "$ReleaseDir\attp-images-$Ver.tar.gz"
Write-Host "▶ docker save → $Tar"
& docker save -o $Tar @Images
if ($LASTEXITCODE -ne 0) { throw "docker save failed" }

# gzip 压缩（.NET GZipStream，无需外部 gzip；docker load 可直接读 .tar.gz）
Write-Host "▶ gzip → $Out"
$src = [System.IO.File]::OpenRead($Tar)
try {
    $dst = [System.IO.File]::Create($Out)
    try {
        $gzStream = New-Object System.IO.Compression.GZipStream($dst, [System.IO.Compression.CompressionLevel]::Optimal)
        try { $src.CopyTo($gzStream) } finally { $gzStream.Close() }
    } finally { $dst.Close() }
} finally { $src.Close() }
Remove-Item $Tar

$Size = [math]::Round((Get-Item $Out).Length / 1MB, 1)
Write-Host "✓ $Out ($Size MB)"
Write-Host "  上传到 GitHub Release；评委用：docker load -i $Out"
