param(
  [string]$Ffmpeg = $env:YINGMU_FFMPEG_BINARY
)

$ErrorActionPreference = 'Stop'
$mediaDir = Join-Path $PSScriptRoot '..\public\media'
$mediaDir = [IO.Path]::GetFullPath($mediaDir)

if (-not $Ffmpeg) {
  $candidates = @(
    'C:\Program Files (x86)\Lenovo\LegionZone\2.0.28.8182\SEGamingAI\services\editor\ffmpeg.exe',
    'C:\Program Files (x86)\Lenovo\LegionZone\2.0.27.7062\SEGamingAI\services\editor\ffmpeg.exe'
  )
  $Ffmpeg = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $Ffmpeg -or -not (Test-Path -LiteralPath $Ffmpeg)) {
  throw 'FFmpeg not found; set YINGMU_FFMPEG_BINARY.'
}

$jobs = @(
  @{ Source = 'activity-route-replay.mp4'; Target = 'activity-route-replay-browser.mp4' },
  @{ Source = 'daily-baseline-replay.mp4'; Target = 'daily-baseline-replay-browser.mp4' }
)

foreach ($job in $jobs) {
  $source = Join-Path $mediaDir $job.Source
  $target = Join-Path $mediaDir $job.Target
  if (-not (Test-Path -LiteralPath $source)) { throw "Missing source media: $source" }
  $temp = "$target.tmp.mp4"
  Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue

  & $Ffmpeg -hide_banner -loglevel error -y -i $source -map 0:v:0 -map 0:a? -c:v h264_nvenc -preset p5 -cq 20 -b:v 0 -pix_fmt yuv420p -tag:v avc1 -c:a copy -movflags +faststart $temp
  if ($LASTEXITCODE -ne 0) {
    Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    & $Ffmpeg -hide_banner -loglevel error -y -i $source -map 0:v:0 -map 0:a? -c:v h264_qsv -global_quality 22 -pix_fmt nv12 -tag:v avc1 -c:a copy -movflags +faststart $temp
  }
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $temp)) { throw "Transcode failed: $($job.Source)" }
  Move-Item -LiteralPath $temp -Destination $target -Force
  $bytes = [IO.File]::ReadAllBytes($target)
  $signature = [Text.Encoding]::ASCII.GetString($bytes)
  if (-not $signature.Contains('avc1') -or $signature.Contains('hvc1')) { throw "Output is not browser-compatible H.264: $target" }
  Write-Host "Generated $target ($((Get-Item -LiteralPath $target).Length) bytes)"
}
