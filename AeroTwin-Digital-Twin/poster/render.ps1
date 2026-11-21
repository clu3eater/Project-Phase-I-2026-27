# Render the A3 poster to PDF + ~290-dpi PNG with headless Chrome.
# Chrome's temp profile is kept on this drive (C: was full).
$P = $PSScriptRoot
$C = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$U = Join-Path $P ".chrome-profile"
$env:TEMP = $U; $env:TMP = $U
New-Item -ItemType Directory -Force $U | Out-Null
$F = "file:///" + ((Join-Path $P "src\aerotwin_poster_A3.html") -replace '\\', '/')
& $C --headless=new --disable-gpu --user-data-dir=$U --no-pdf-header-footer "--print-to-pdf=$P\AeroTwin_Poster_A3.pdf" $F 2>$null | Out-Null
& $C --headless=new --disable-gpu --user-data-dir=$U --hide-scrollbars --window-size=1587,1123 --force-device-scale-factor=3 "--screenshot=$P\AeroTwin_Poster_A3.png" $F 2>$null | Out-Null
Remove-Item -Recurse -Force $U -Confirm:$false -ErrorAction SilentlyContinue
