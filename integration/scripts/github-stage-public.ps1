[CmdletBinding()]
param(
    [string]$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$OutputRoot = (Join-Path (Split-Path (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path -Parent) 'bot-mode-public-staging-20260917')
)

$ErrorActionPreference = 'Stop'
$SourceRoot = (Resolve-Path $SourceRoot).Path
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
$expectedParent = [IO.Path]::GetFullPath((Split-Path $SourceRoot -Parent))
$outputParent = [IO.Path]::GetFullPath((Split-Path $OutputRoot -Parent))
$outputLeaf = Split-Path $OutputRoot -Leaf
if ($outputParent -ne $expectedParent -or $outputLeaf -notmatch '^bot-mode-public-staging-[0-9]{8}$' -or $OutputRoot -eq $SourceRoot -or $OutputRoot -eq $expectedParent) {
    throw "OutputRoot must be a dated bot-mode-public-staging child of $expectedParent"
}
if (Test-Path -LiteralPath $OutputRoot) { Remove-Item -LiteralPath $OutputRoot -Recurse -Force }
New-Item -ItemType Directory -Path $OutputRoot | Out-Null

$include = @('backend','desktop','frontend','integration','skills','docs','README.md','PRODUCT.md','DESIGN.md','LICENSE','.gitignore','.dockerignore')
$exclude = @('data','design-research','frontend/node_modules','backend/data','backend/.pytest_cache','**/__pycache__','**/*.pyc','**/*.sqlite*','**/*.db','**/*.log','**/*.env','**/*.bak','**/dist')
foreach ($item in $include) {
    $src = Join-Path $SourceRoot $item
    if (-not (Test-Path -LiteralPath $src)) { continue }
    $dst = Join-Path $OutputRoot $item
    if ((Get-Item -LiteralPath $src).PSIsContainer) {
        New-Item -ItemType Directory -Path $dst -Force | Out-Null
        robocopy $src $dst /E /R:0 /W:0 /XD (Join-Path $SourceRoot 'data') (Join-Path $SourceRoot 'design-research') (Join-Path $SourceRoot 'frontend\node_modules') (Join-Path $SourceRoot 'frontend\dist') (Join-Path $SourceRoot 'backend\data') (Join-Path $SourceRoot 'backend\.pytest_cache') (Join-Path $SourceRoot 'integration\.pytest_cache') /XF *.sqlite* *.db *.log *.env *.bak *.pyc github-backup-plan.ps1 | Out-Null
        if ($LASTEXITCODE -gt 7) { throw "robocopy failed for $item ($LASTEXITCODE)" }
    } else { Copy-Item -LiteralPath $src -Destination $dst }
}

# Public source must contain no deployment identity, personal path, Telegram identity, or live origin.
    $textFiles = Get-ChildItem -LiteralPath $OutputRoot -Recurse -File | Where-Object { $_.Extension -in @('.md','.py','.ps1','.yml','.yaml','.toml','.json','.ts','.tsx','.css','.sh','.example','.txt','.service') }
foreach ($file in $textFiles) {
    $text = Get-Content -LiteralPath $file.FullName -Raw
    $text = $text -replace 'https://minipc-hermes\.tailb22a44\.ts\.net', 'https://your-hermes-origin.example'
    $text = $text -replace 'https://t\.me/your-bot', 'https://t\.me/your-bot'
    $text = $text -replace '(?i)C:\\Users\\Work\\Documents\\Server\\bot-mode', '<checkout>'
    $text = $text.Replace('/var/lib/hermes-bot-mode', '/var/lib/hermes-bot-mode')
    $text = $text.Replace('/opt/hermes-bot-mode', '/opt/hermes-bot-mode')
    $text = $text.Replace('/var/lib/hermes', '/var/lib/hermes')
    $text = $text -replace '(?i)your-bot', 'your-bot'
    Set-Content -LiteralPath $file.FullName -Value $text -Encoding utf8NoBOM
}

$publicReadme = @'
# Hermes Bot Mode

Bot Mode is a self-hostable messenger for persistent AI Bots, durable conversations, bounded memory, optional routines, and optional desktop automation. The public package contains source and generic setup examples; private application data, browser profiles, runtime authentication, and deployment credentials stay outside the repository.

## Features

- React and TypeScript messenger with desktop and mobile layouts
- FastAPI backend with SQLite persistence, search, files, groups, approvals, and task streaming
- Optional Codex app-server runtime, Composio/OpenRouter provider configuration, and Telegram bridge
- Optional Docker desktop supervisor with per-Bot browser profiles and noVNC viewing
- Optional learned skills and scheduled routines when configured

## Setup

Read [docs/public-setup.md](docs/public-setup.md), then configure a private environment file from `backend/.env.example` or `integration/bot-mode.env.example`. Use an HTTPS origin for remote access and generate independent random session/internal secrets. Keep the data volume outside the checkout.

For a local operator login after the service is running:

```sh
PYTHONPATH=backend python integration/scripts/operator-login.py --user-id YOUR_OWNER_ID
```

The link is one-use and short-lived. Do not print it in logs or share it. Telegram sign-in is optional; when the bridge is configured, use the documented `/bot` flow instead.

The Compose template runs the service as its configured container user and mounts a dedicated data directory at `/data`. On a host deployment, create that directory with the UID/GID required by the image and keep ownership consistent; do not reuse a personal home directory or bind mount unrelated files. Desktop automation requires Docker, the desktop image, and its supervisor configuration.

## License

Application code is MIT licensed. See the vendored SlopMonster attribution and pinned upstream commit under `skills/slopmonster` before redistribution. Review third-party dependency licenses and service terms separately.
'@
Set-Content -LiteralPath (Join-Path $OutputRoot 'README.md') -Value $publicReadme -Encoding utf8NoBOM

Write-Output "Public staging created: $OutputRoot"

