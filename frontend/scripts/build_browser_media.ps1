param(
  [string]$SourceRoot = (Join-Path $PSScriptRoot '..\..'),
  [string]$Ffmpeg = $env:YINGMU_FFMPEG_BINARY,
  [string]$Ffprobe = $env:YINGMU_FFPROBE_BINARY,
  [string]$Manifest = (Join-Path $PSScriptRoot '..\media-selection.manifest.json')
)

$ErrorActionPreference = 'Stop'
$SourceRoot = [IO.Path]::GetFullPath($SourceRoot)
$targetDir = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\public\media\selected'))
$Manifest = [IO.Path]::GetFullPath($Manifest)

if (-not $Ffmpeg) {
  $ffmpegCommand = Get-Command ffmpeg -ErrorAction SilentlyContinue
  if ($ffmpegCommand) { $Ffmpeg = $ffmpegCommand.Source }
}
if (-not $Ffprobe) {
  $ffprobeCommand = Get-Command ffprobe -ErrorAction SilentlyContinue
  if ($ffprobeCommand) { $Ffprobe = $ffprobeCommand.Source }
}
if (-not $Ffmpeg -or -not (Test-Path -LiteralPath $Ffmpeg)) { throw 'FFmpeg not found; set -Ffmpeg or YINGMU_FFMPEG_BINARY.' }
if (-not $Ffprobe -or -not (Test-Path -LiteralPath $Ffprobe)) { throw 'ffprobe not found; set -Ffprobe or YINGMU_FFPROBE_BINARY.' }
if (-not (Test-Path -LiteralPath $Manifest)) { throw "Missing selected media manifest: $Manifest" }

$manifestObject = Get-Content -Raw -Encoding utf8 -LiteralPath $Manifest | ConvertFrom-Json
$entries = @($manifestObject.entries)
if ($entries.Count -ne 28) { throw "Expected 28 selected media entries, found $($entries.Count)." }
if ($manifestObject.source_mode -ne 'RECORDED_REPLAY' -or $manifestObject.simulated -ne $true) { throw 'Selected media manifest must be RECORDED_REPLAY / simulated=true.' }
$buildEntries = @($entries) + @($manifestObject.auxiliary_entries)
New-Item -ItemType Directory -Force -Path $targetDir | Out-Null

function Probe-Video([string]$path) {
  $json = & $Ffprobe -v error -show_entries format=duration:stream=index,codec_type,codec_name,width,height -of json -- $path
  if ($LASTEXITCODE -ne 0) { throw "ffprobe failed: $path" }
  return ($json | ConvertFrom-Json)
}

function Is-FastStart([string]$path) {
  $bytes = [IO.File]::ReadAllBytes($path)
  $moov = [Text.Encoding]::ASCII.GetString($bytes).IndexOf('moov', [StringComparison]::Ordinal)
  $mdat = [Text.Encoding]::ASCII.GetString($bytes).IndexOf('mdat', [StringComparison]::Ordinal)
  return $moov -ge 0 -and ($mdat -lt 0 -or $moov -lt $mdat)
}

function Convert-ToBrowserMp4([string]$source, [string]$target, [bool]$transcode) {
  $temp = "$target.tmp.mp4"
  Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
  if ($transcode) {
    & $Ffmpeg -hide_banner -loglevel error -y -i $source -map 0:v:0 -map 0:a? -c:v libx264 -preset veryfast -crf 22 -pix_fmt yuv420p -tag:v avc1 -c:a aac -b:a 128k -movflags +faststart $temp
  } else {
    & $Ffmpeg -hide_banner -loglevel error -y -i $source -map 0 -c copy -movflags +faststart $temp
  }
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $temp)) { throw "Browser media conversion failed: $source" }
  Move-Item -LiteralPath $temp -Destination $target -Force
}

$failures = @()
foreach ($entry in $buildEntries) {
  $source = Join-Path $SourceRoot ($entry.source_relpath -replace '/', '\')
  $target = Join-Path $targetDir $entry.target_filename
  if (-not (Test-Path -LiteralPath $source)) { $failures += "$($entry.clip_id): source missing"; continue }
  $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash.ToLowerInvariant()
  if ($hash -ne $entry.sha256.ToLowerInvariant()) { $failures += "$($entry.clip_id): source SHA-256 mismatch"; continue }
  $probe = Probe-Video $source
  $video = @($probe.streams | Where-Object { $_.codec_type -eq 'video' } | Select-Object -First 1)
  if (-not $video) { $failures += "$($entry.clip_id): no video stream"; continue }
  $needsTranscode = $video.codec_name -ne 'h264'
  if (-not $needsTranscode -and (Test-Path -LiteralPath $target)) {
    $existing = Probe-Video $target
    $existingVideo = @($existing.streams | Where-Object { $_.codec_type -eq 'video' } | Select-Object -First 1)
    if ($existingVideo.codec_name -eq 'h264' -and (Is-FastStart $target)) { continue }
  }
  Convert-ToBrowserMp4 $source $target $needsTranscode
}
if ($failures.Count) { throw ($failures -join [Environment]::NewLine) }

$verification = @()
foreach ($entry in $buildEntries) {
  $target = Join-Path $targetDir $entry.target_filename
  $source = Join-Path $SourceRoot ($entry.source_relpath -replace '/', '\')
  if (-not (Test-Path -LiteralPath $target)) { throw "Target missing: $($entry.target_filename)" }
  $probe = Probe-Video $target
  $sourceProbe = Probe-Video $source
  $video = @($probe.streams | Where-Object { $_.codec_type -eq 'video' } | Select-Object -First 1)
  $sourceVideo = @($sourceProbe.streams | Where-Object { $_.codec_type -eq 'video' } | Select-Object -First 1)
  $duration = [double]$probe.format.duration
  if ($video.codec_name -ne 'h264') { throw "Target is not H.264: $($entry.target_filename)" }
  if ($video.width -le 0 -or $video.height -le 0 -or $duration -le 0) { throw "Invalid dimensions or duration: $($entry.target_filename)" }
  if ($video.width -ne $sourceVideo.width -or $video.height -ne $sourceVideo.height) { throw "Target resolution differs from source: $($entry.target_filename)" }
  if ([Math]::Abs(($duration * 1000) - [double]$entry.duration_ms) -gt 2000) { throw "Target duration differs from manifest: $($entry.target_filename)" }
  if (-not (Is-FastStart $target)) { throw "Target is not faststart: $($entry.target_filename)" }
  $verification += [pscustomobject]@{ clip_id = $entry.clip_id; target_filename = $entry.target_filename; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLowerInvariant(); duration_ms = [Math]::Round($duration * 1000); codec = $video.codec_name; width = $video.width; height = $video.height; source_mode = 'RECORDED_REPLAY'; simulated = $true }
}
$reportPath = Join-Path $targetDir 'selection-verification.local.json'
$verification | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 -LiteralPath $reportPath
Write-Host "Browser media verified: $($verification.Count) H.264 clips ($($entries.Count) selected) in $targetDir"
