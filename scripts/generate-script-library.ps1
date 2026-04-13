$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$windowsDir = Join-Path $scriptsDir "windows"
$libraryDir = Join-Path $windowsDir "library"
$catalogPath = Join-Path $windowsDir "script-library.json"
$manifestPath = Join-Path $scriptsDir "manifest.json"

New-Item -ItemType Directory -Path $libraryDir -Force | Out-Null

function New-ScriptDef {
    param(
        [string]$Name,
        [string]$Description,
        [string[]]$Aliases,
        [string]$Handler,
        [hashtable]$Extra
    )
    $item = [ordered]@{
        name = $Name
        description = $Description
        aliases = $Aliases
        handler = $Handler
        chainable = $true
    }
    foreach ($key in $Extra.Keys) {
        $item[$key] = $Extra[$key]
    }
    [pscustomobject]$item
}

$scriptDefs = New-Object System.Collections.Generic.List[object]

$existing = @(
    [pscustomobject]@{
        name = "outlook_repair"
        path = "scripts/windows/outlook_repair.ps1"
        description = "Outlook icin temel onarim akisi"
        aliases = @("outlook onar", "outlook duzelt", "outlook tamir et")
    },
    [pscustomobject]@{
        name = "dns_flush"
        path = "scripts/windows/dns_flush.ps1"
        description = "DNS cache temizleme"
        aliases = @("dns temizle", "dns flush", "dns onbellegini temizle")
    },
    [pscustomobject]@{
        name = "clear_temp"
        path = "scripts/windows/clear_temp.ps1"
        description = "Temp klasorlerini temizleme"
        aliases = @("temp temizle", "gecici dosyalari temizle", "temp dosyalarini temizle")
    },
    [pscustomobject]@{
        name = "office_repair"
        path = "scripts/windows/office_repair.ps1"
        description = "Office onarim akisi"
        aliases = @("office onar", "office duzelt", "office tamir et")
    },
    [pscustomobject]@{
        name = "restart_service"
        path = "scripts/windows/restart_service.ps1"
        description = "Servis yeniden baslatma"
        aliases = @("servisi yeniden baslat", "service restart", "servis restart")
    }
)

$startProcessDefs = @(
    @{ name="open_chrome"; description="Chrome ac"; file="chrome"; args=@("--new-window","about:blank"); aliases=@("chrome ac","google chrome ac","chrome baslat") },
    @{ name="open_edge"; description="Edge ac"; file="msedge"; args=@("--new-window","about:blank"); aliases=@("edge ac","microsoft edge ac","edge baslat") },
    @{ name="open_firefox"; description="Firefox ac"; file="firefox"; args=@(); aliases=@("firefox ac","mozilla firefox ac") },
    @{ name="open_outlook"; description="Outlook ac"; candidates=@("olk","outlook","C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE","C:\Program Files (x86)\Microsoft Office\root\Office16\OUTLOOK.EXE"); args=@(); aliases=@("outlook ac","outlok ac","outlook uygulamasini ac","outlok uygulamasini ac") },
    @{ name="open_excel"; description="Excel ac"; candidates=@("excel","C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE","C:\Program Files (x86)\Microsoft Office\root\Office16\EXCEL.EXE"); args=@(); aliases=@("excel ac","excel uygulamasini ac") },
    @{ name="open_word"; description="Word ac"; candidates=@("winword","C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE","C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE"); args=@(); aliases=@("word ac","word uygulamasini ac") },
    @{ name="open_powerpoint"; description="PowerPoint ac"; candidates=@("powerpnt","C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE","C:\Program Files (x86)\Microsoft Office\root\Office16\POWERPNT.EXE"); args=@(); aliases=@("powerpoint ac","slayt uygulamasini ac") },
    @{ name="open_notepad"; description="Notepad ac"; file="notepad"; args=@(); aliases=@("notepad ac","not defteri ac") },
    @{ name="open_calc"; description="Hesap makinesi ac"; file="calc"; args=@(); aliases=@("hesap makinesi ac","calculator ac","calc ac") },
    @{ name="open_paint"; description="Paint ac"; file="mspaint"; args=@(); aliases=@("paint ac","boya ac","mspaint ac") },
    @{ name="open_explorer"; description="Dosya gezgini ac"; file="explorer"; args=@(); aliases=@("dosya gezgini ac","explorer ac","file explorer ac") },
    @{ name="open_snipping_tool"; description="Ekran alintisi aracini ac"; file="SnippingTool"; args=@(); aliases=@("snipping tool ac","ekran alintisi aracini ac","kirpma aracini ac") }
)
foreach ($def in $startProcessDefs) {
    if ($def.ContainsKey("candidates")) {
        $scriptDefs.Add((New-ScriptDef -Name $def.name -Description $def.description -Aliases $def.aliases -Handler "start_process_candidates" -Extra @{ file_candidates = $def.candidates; arguments = $def.args }))
    }
    else {
        $scriptDefs.Add((New-ScriptDef -Name $def.name -Description $def.description -Aliases $def.aliases -Handler "start_process" -Extra @{ file_path = $def.file; arguments = $def.args }))
    }
}

$stopProcessDefs = @(
    @{ name="close_chrome"; description="Chrome kapat"; processes=@("chrome"); aliases=@("chrome kapat","chrome kapansin") },
    @{ name="close_edge"; description="Edge kapat"; processes=@("msedge"); aliases=@("edge kapat","edge kapansin") },
    @{ name="close_firefox"; description="Firefox kapat"; processes=@("firefox"); aliases=@("firefox kapat") },
    @{ name="close_outlook"; description="Outlook kapat"; processes=@("outlook"); aliases=@("outlook kapat","outlok kapat") },
    @{ name="close_excel"; description="Excel kapat"; processes=@("excel"); aliases=@("excel kapat") },
    @{ name="close_word"; description="Word kapat"; processes=@("winword"); aliases=@("word kapat") },
    @{ name="close_powerpoint"; description="PowerPoint kapat"; processes=@("powerpnt"); aliases=@("powerpoint kapat") },
    @{ name="close_notepad"; description="Notepad kapat"; processes=@("notepad"); aliases=@("notepad kapat","not defterini kapat") },
    @{ name="close_teams"; description="Teams kapat"; processes=@("ms-teams","teams"); aliases=@("teams kapat","microsoft teams kapat") },
    @{ name="close_onedrive"; description="OneDrive kapat"; processes=@("OneDrive"); aliases=@("onedrive kapat","one drive kapat") }
)
foreach ($def in $stopProcessDefs) {
    $scriptDefs.Add((New-ScriptDef -Name $def.name -Description $def.description -Aliases $def.aliases -Handler "stop_process" -Extra @{ process_names = $def.processes }))
}

$folderDefs = @(
    @{ name="open_desktop"; description="Masaustunu ac"; target='$env:USERPROFILE\Desktop'; aliases=@("masaustunu ac","desktop ac") },
    @{ name="open_documents"; description="Belgeleri ac"; target='$env:USERPROFILE\Documents'; aliases=@("belgeleri ac","documents ac") },
    @{ name="open_downloads"; description="Indirilenleri ac"; target='$env:USERPROFILE\Downloads'; aliases=@("indirilenleri ac","downloads ac") },
    @{ name="open_pictures"; description="Resimler klasorunu ac"; target='$env:USERPROFILE\Pictures'; aliases=@("resimleri ac","pictures ac") },
    @{ name="open_videos"; description="Videolar klasorunu ac"; target='$env:USERPROFILE\Videos'; aliases=@("videolari ac","videos ac") },
    @{ name="open_music"; description="Muzik klasorunu ac"; target='$env:USERPROFILE\Music'; aliases=@("muzikleri ac","music klasorunu ac") },
    @{ name="open_temp_folder"; description="Temp klasorunu ac"; target='$env:TEMP'; aliases=@("temp klasorunu ac","gecici klasoru ac") },
    @{ name="open_startup_folder"; description="Startup klasorunu ac"; target='shell:startup'; aliases=@("startup klasorunu ac","baslangic klasorunu ac") },
    @{ name="open_program_files"; description="Program Files klasorunu ac"; target='C:\Program Files'; aliases=@("program files klasorunu ac") },
    @{ name="open_public_desktop"; description="Ortak masaustunu ac"; target='C:\Users\Public\Desktop'; aliases=@("ortak masaustunu ac","public desktop ac") }
)
foreach ($def in $folderDefs) {
    $scriptDefs.Add((New-ScriptDef -Name $def.name -Description $def.description -Aliases $def.aliases -Handler "start_shell_target" -Extra @{ target = $def.target }))
}

$settingsDefs = @(
    @{ name="open_task_manager"; description="Gorev yoneticisini ac"; file="taskmgr"; args=@(); aliases=@("gorev yoneticisini ac","task manager ac") },
    @{ name="open_control_panel"; description="Denetim masasini ac"; file="control"; args=@(); aliases=@("denetim masasini ac","control panel ac") },
    @{ name="open_programs_features"; description="Programlar ve ozellikleri ac"; file="appwiz.cpl"; args=@(); aliases=@("program ekle kaldiri ac","programlar ve ozellikler ac") },
    @{ name="open_services_console"; description="Servisler konsolunu ac"; file="services.msc"; args=@(); aliases=@("servisleri ac","services ac") },
    @{ name="open_device_manager"; description="Aygit yoneticisini ac"; file="devmgmt.msc"; args=@(); aliases=@("aygit yoneticisini ac","device manager ac") },
    @{ name="open_event_viewer"; description="Olay goruntuleyicisini ac"; file="eventvwr.msc"; args=@(); aliases=@("olay goruntuleyicisini ac","event viewer ac") },
    @{ name="open_system_settings"; description="Sistem ayarlarini ac"; target="ms-settings:system"; aliases=@("sistem ayarlarini ac","system settings ac") },
    @{ name="open_network_settings"; description="Ag ayarlarini ac"; target="ms-settings:network"; aliases=@("ag ayarlarini ac","network settings ac") },
    @{ name="open_printer_settings"; description="Yazici ayarlarini ac"; target="ms-settings:printers"; aliases=@("yazici ayarlarini ac","printers settings ac") },
    @{ name="open_sound_settings"; description="Ses ayarlarini ac"; target="ms-settings:sound"; aliases=@("ses ayarlarini ac","sound settings ac") },
    @{ name="open_display_settings"; description="Ekran ayarlarini ac"; target="ms-settings:display"; aliases=@("ekran ayarlarini ac","display settings ac") },
    @{ name="open_apps_settings"; description="Uygulama ayarlarini ac"; target="ms-settings:appsfeatures"; aliases=@("uygulama ayarlarini ac","apps settings ac") },
    @{ name="open_storage_settings"; description="Depolama ayarlarini ac"; target="ms-settings:storagesense"; aliases=@("depolama ayarlarini ac","storage settings ac") }
)
foreach ($def in $settingsDefs) {
    if ($def.ContainsKey("file")) {
        $scriptDefs.Add((New-ScriptDef -Name $def.name -Description $def.description -Aliases $def.aliases -Handler "start_process" -Extra @{ file_path = $def.file; arguments = $def.args }))
    }
    else {
        $scriptDefs.Add((New-ScriptDef -Name $def.name -Description $def.description -Aliases $def.aliases -Handler "start_shell_target" -Extra @{ target = $def.target }))
    }
}

$webDefs = @(
    @{ name="open_gmail"; description="Gmail ac"; target="https://mail.google.com/"; aliases=@("gmail ac","gmaili ac") },
    @{ name="open_outlook_web"; description="Outlook web mail ac"; target="https://outlook.office.com/mail/"; aliases=@("outlook web ac","outlook mail ac") },
    @{ name="open_google"; description="Google ac"; target="https://www.google.com/"; aliases=@("google ac") },
    @{ name="open_youtube"; description="YouTube ac"; target="https://www.youtube.com/"; aliases=@("youtube ac") },
    @{ name="open_google_drive"; description="Google Drive ac"; target="https://drive.google.com/"; aliases=@("google drive ac","drive ac") },
    @{ name="open_whatsapp_web"; description="WhatsApp Web ac"; target="https://web.whatsapp.com/"; aliases=@("whatsapp web ac","whatsapp ac") },
    @{ name="open_github"; description="GitHub ac"; target="https://github.com/"; aliases=@("github ac") },
    @{ name="open_linkedin"; description="LinkedIn ac"; target="https://www.linkedin.com/"; aliases=@("linkedin ac") }
)
foreach ($def in $webDefs) {
    $scriptDefs.Add((New-ScriptDef -Name $def.name -Description $def.description -Aliases $def.aliases -Handler "start_shell_target" -Extra @{ target = $def.target }))
}

$diagnosticDefs = @(
    @{ name="capture_screenshot"; description="Ekran goruntusu al"; handler="powershell_inline"; aliases=@("ekran resmi al","screenshot al","ekran goruntusu al"); extra=@{ script = @'
$screenshotsDir = Join-Path $LibraryRepoBase "data\screenshots"
New-Item -ItemType Directory -Path $screenshotsDir -Force | Out-Null
$savePath = Join-Path $screenshotsDir ("library-screenshot-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".png")
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($bounds.X, $bounds.Y, 0, 0, $bitmap.Size)
$bitmap.Save($savePath, [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
Write-Output $savePath
'@ } },
    @{ name="system_status_report"; description="Sistem durumu raporu al"; handler="powershell_inline"; aliases=@("sistem raporu al","system status report"); extra=@{ script = @'
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
[pscustomobject]@{
    ComputerName = $env:COMPUTERNAME
    OS = $os.Caption
    RAM_GB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
    CPU = $cpu.Name
    FreePhysicalMemoryMB = [math]::Round($os.FreePhysicalMemory / 1KB, 2)
} | ConvertTo-Json -Depth 4
'@ } },
    @{ name="list_processes"; description="Surecleri listele"; handler="powershell_inline"; aliases=@("surecleri listele","processleri listele"); extra=@{ script = "Get-Process | Sort-Object ProcessName | Select-Object -First 30 ProcessName, Id | Format-Table -AutoSize | Out-String" } },
    @{ name="list_services"; description="Servisleri listele"; handler="powershell_inline"; aliases=@("servisleri listele","services listele"); extra=@{ script = "Get-Service | Sort-Object Status, DisplayName | Select-Object -First 30 Status, Name, DisplayName | Format-Table -AutoSize | Out-String" } },
    @{ name="ipconfig_all"; description="IP konfigurasyonunu goster"; handler="run_command_capture"; aliases=@("ip bilgilerini goster","ipconfig goster","ag bilgisini goster"); extra=@{ command = "ipconfig"; arguments = @("/all") } },
    @{ name="ping_google"; description="Google ping testi yap"; handler="run_command_capture"; aliases=@("google ping at","googlea ping at"); extra=@{ command = "ping"; arguments = @("google.com","-n","4") } },
    @{ name="ping_cloudflare"; description="Cloudflare ping testi yap"; handler="run_command_capture"; aliases=@("cloudflare ping at","1.1.1.1 ping at"); extra=@{ command = "ping"; arguments = @("1.1.1.1","-n","4") } },
    @{ name="open_resource_monitor"; description="Kaynak izleyiciyi ac"; handler="start_process"; aliases=@("kaynak izleyiciyi ac","resource monitor ac"); extra=@{ file_path = "resmon"; arguments = @() } },
    @{ name="open_reliability_monitor"; description="Guvenilirlik gecmisini ac"; handler="start_process"; aliases=@("guvenilirlik monitorunu ac","reliability monitor ac"); extra=@{ file_path = "perfmon"; arguments = @("/rel") } },
    @{ name="open_msinfo32"; description="Sistem bilgisini ac"; handler="start_process"; aliases=@("sistem bilgisini ac","msinfo32 ac"); extra=@{ file_path = "msinfo32"; arguments = @() } }
)
foreach ($def in $diagnosticDefs) {
    $scriptDefs.Add((New-ScriptDef -Name $def.name -Description $def.description -Aliases $def.aliases -Handler $def.handler -Extra $def.extra))
}

$maintenanceDefs = @(
    @{ name="restart_print_spooler"; description="Yazdirma servisini yeniden baslat"; handler="powershell_inline"; aliases=@("spooleri yeniden baslat","print spooleri yeniden baslat"); extra=@{ script = "Restart-Service -Name Spooler -ErrorAction Stop; 'Spooler yeniden baslatildi.'" } },
    @{ name="restart_explorer_shell"; description="Explorer kabugunu yeniden baslat"; handler="powershell_inline"; aliases=@("exploreri yeniden baslat","kabugu yeniden baslat"); extra=@{ script = "Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue; Start-Process explorer.exe; 'Explorer yeniden baslatildi.'" } },
    @{ name="clear_clipboard"; description="Panoyu temizle"; handler="powershell_inline"; aliases=@("panoyu temizle","clipboard temizle"); extra=@{ script = 'Set-Clipboard -Value ""; "Pano temizlendi."' } },
    @{ name="open_windows_update"; description="Windows Update ayarlarini ac"; handler="start_shell_target"; aliases=@("windows update ac","guncelleme ayarlarini ac"); extra=@{ target = "ms-settings:windowsupdate" } },
    @{ name="open_defender"; description="Windows Guvenligi ac"; handler="start_shell_target"; aliases=@("defender ac","windows guvenligini ac"); extra=@{ target = "windowsdefender:" } },
    @{ name="open_date_time_settings"; description="Tarih saat ayarlarini ac"; handler="start_shell_target"; aliases=@("tarih saat ayarlarini ac","date time settings ac"); extra=@{ target = "ms-settings:dateandtime" } },
    @{ name="open_bluetooth_settings"; description="Bluetooth ayarlarini ac"; handler="start_shell_target"; aliases=@("bluetooth ayarlarini ac"); extra=@{ target = "ms-settings:bluetooth" } },
    @{ name="open_wifi_settings"; description="WiFi ayarlarini ac"; handler="start_shell_target"; aliases=@("wifi ayarlarini ac","kablosuz ayarlarini ac"); extra=@{ target = "ms-settings:network-wifi" } },
    @{ name="open_taskbar_settings"; description="Gorev cubugu ayarlarini ac"; handler="start_shell_target"; aliases=@("gorev cubugu ayarlarini ac","taskbar settings ac"); extra=@{ target = "ms-settings:taskbar" } },
    @{ name="open_personalization_settings"; description="Kisisellestirme ayarlarini ac"; handler="start_shell_target"; aliases=@("kisisellestirme ayarlarini ac","personalization settings ac"); extra=@{ target = "ms-settings:personalization" } },
    @{ name="open_default_apps"; description="Varsayilan uygulamalari ac"; handler="start_shell_target"; aliases=@("varsayilan uygulamalari ac","default apps ac"); extra=@{ target = "ms-settings:defaultapps" } },
    @{ name="open_optional_features"; description="Istege bagli ozellikleri ac"; handler="start_shell_target"; aliases=@("optional features ac","istege bagli ozellikleri ac"); extra=@{ target = "ms-settings:optionalfeatures" } }
)
foreach ($def in $maintenanceDefs) {
    $scriptDefs.Add((New-ScriptDef -Name $def.name -Description $def.description -Aliases $def.aliases -Handler $def.handler -Extra $def.extra))
}

if ($scriptDefs.Count -ne 75) {
    throw "Beklenen 75 yeni script yerine $($scriptDefs.Count) script uretildi."
}

$catalogJson = $scriptDefs | ConvertTo-Json -Depth 8
Set-Content -LiteralPath $catalogPath -Value $catalogJson -Encoding UTF8

Get-ChildItem -LiteralPath $libraryDir -Filter *.ps1 -File | Remove-Item -Force
foreach ($def in $scriptDefs) {
    $ps1Path = Join-Path $libraryDir ($def.name + ".ps1")
@"
`$ErrorActionPreference = 'Stop'
`$scriptRoot = Split-Path -Parent `$MyInvocation.MyCommand.Path
`$runner = Join-Path `$(Split-Path -Parent `$scriptRoot) 'run-library-script.ps1'
powershell -ExecutionPolicy Bypass -File `$runner -ScriptName "$($def.name)"
"@ | Set-Content -LiteralPath $ps1Path -Encoding UTF8
}

$manifestEntries = New-Object System.Collections.Generic.List[object]
foreach ($item in $existing) {
    $manifestEntries.Add([pscustomobject]$item)
}
foreach ($def in $scriptDefs) {
    $manifestEntries.Add([pscustomobject]@{
        name = $def.name
        path = "scripts/windows/library/$($def.name).ps1"
        description = $def.description
        aliases = $def.aliases
    })
}

$manifest = [ordered]@{
    scripts = $manifestEntries
}
Set-Content -LiteralPath $manifestPath -Value ($manifest | ConvertTo-Json -Depth 6) -Encoding UTF8
Write-Output "Generated $($manifestEntries.Count) script entries."
