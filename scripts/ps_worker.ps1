[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

while (($line = [Console]::In.ReadLine()) -ne $null) {
    if ([string]::IsNullOrWhiteSpace($line)) {
        continue
    }

    try {
        $payload = $line | ConvertFrom-Json
        $commandId = [string]$payload.id
        $commandBytes = [System.Convert]::FromBase64String([string]$payload.command_b64)
        $command = [System.Text.Encoding]::UTF8.GetString($commandBytes)
        $doneMarker = "__TA_DONE__:$commandId"
        $errorMarker = "__TA_ERROR__:$commandId"

        try {
            $ErrorActionPreference = 'Stop'
            $result = Invoke-Expression $command | Out-String -Stream
            foreach ($entry in $result) {
                [Console]::WriteLine([string]$entry)
            }
        } catch {
            [Console]::WriteLine($errorMarker)
            [Console]::WriteLine($_.Exception.Message)
        }

        [Console]::WriteLine($doneMarker)
        [Console]::Out.Flush()
    } catch {
        [Console]::WriteLine("__TA_ERROR__:worker")
        [Console]::WriteLine($_.Exception.Message)
        [Console]::WriteLine("__TA_DONE__:worker")
        [Console]::Out.Flush()
    }
}
