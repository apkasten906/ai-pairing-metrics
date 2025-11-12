
param(
  [int]$SinceDays = 30,
  [string]$Author = "",
  [string]$Branch = "HEAD",
  [string]$Output = "ai_acceptance_metrics.csv",
  [switch]$IgnoreComments,
  [int]$MinLineLength = 3,
  [int]$ImmediateWindowMinutes = 90
)

function Exec-Git {
  param([string]$GitArgs, [switch]$IgnoreErrors)
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = "git"
  $psi.Arguments = $GitArgs
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.UseShellExecute = $false
  Write-Host "[Exec-Git] running: git $GitArgs"
  $p = New-Object System.Diagnostics.Process
  $p.StartInfo = $psi
  try {
    [void]$p.Start()
  }
  catch {
    throw "Failed to start git process for args: $GitArgs. Exception: $($_.Exception.Message)"
  }

  $stdout = $p.StandardOutput.ReadToEnd()
  $stderr = $p.StandardError.ReadToEnd()
  $p.WaitForExit()
  if (!$IgnoreErrors -and $p.ExitCode -ne 0) {
    $cwd = (Get-Location).Path
    $msg = @()
    $msg += "git $GitArgs failed (exit $($p.ExitCode))"
    $msg += "WorkingDirectory: $cwd"
    if ($stderr -ne "") { $msg += "STDERR:"; $msg += $stderr }
    if ($stdout -ne "") { $msg += "STDOUT:"; $msg += $stdout }
    throw ($msg -join "`n")
  }
  return $stdout
}

function Get-Commits {
  param([int]$SinceDays, [string]$Author)
  $since = (Get-Date).AddDays(-$SinceDays).ToUniversalTime()
  $sinceUnix = [int][double]::Parse((Get-Date $since -UFormat %s))
  $authorFilter = ""
  if ($Author -ne "") { $authorFilter = " --author=`"$Author`"" }
  $gitArgs = "log --no-merges --pretty=format:`"%H|%ct|%an|%s`" --since=$sinceUnix$authorFilter"
  $out = Exec-Git $gitArgs
  $lines = $out -split "`n" | Where-Object { $_.Trim() -ne "" }
  foreach ($l in $lines) {
    $parts = $l -split "\|", 4
    [PSCustomObject]@{
      Hash     = $parts[0]
      UnixTime = [int64]$parts[1]
      Author   = $parts[2]
      Subject  = $parts[3]
    }
  }
}

function Get-Parent {
  param([string]$Commit)
  $line = Exec-Git "rev-list --parents -n 1 $Commit"
  $parts = $line.Trim() -split "\s+"
  if ($parts.Length -ge 2) { return $parts[1] } else { return $null }
}

function Get-Patch {
  param([string]$Commit)
  # unified=0 to isolate exact added lines
  Exec-Git "show --format= --unified=0 --no-renames $Commit"
}

function Is-CommentLine {
  param([string]$Path, [string]$Line)
  $trim = $Line.Trim()
  if ($trim -eq "") { return $true }
  $ext = [System.IO.Path]::GetExtension($Path).ToLowerInvariant()
  switch ($ext) {
    ".ts" { return ($trim -match "^(//|\*\/|/\*|\*)") }
    ".tsx" { return ($trim -match "^(//|\*\/|/\*|\*)") }
    ".js" { return ($trim -match "^(//|\*\/|/\*|\*)") }
    ".jsx" { return ($trim -match "^(//|\*\/|/\*|\*)") }
    ".json" { return $false }
    default { return ($trim -match "^(//|#|\*\/|/\*|\*)") }
  }
}

function Get-AddedLinesFromPatch {
  param([string]$Patch)
  $results = @()
  $currentFile = $null
  $lines = $Patch -split "`n"
  foreach ($l in $lines) {
    if ($l.StartsWith("diff --git")) {
      $currentFile = $null
    }
    elseif ($l.StartsWith("+++ b/")) {
      $currentFile = $l.Substring(6).Trim()
    }
    elseif ($currentFile -ne $null -and $l.StartsWith("+") -and -not $l.StartsWith("+++")) {
      $added = $l.Substring(1)
      $results += [PSCustomObject]@{ Path = $currentFile; Line = $added }
    }
  }
  return $results
}

function Get-FileContentAt {
  param([string]$Ref, [string]$Path)
  try {
    return Exec-Git "show ${Ref}:`"$Path`"" -IgnoreErrors
  }
  catch {
    return ""
  }
}

function Get-NextCommitAffectingFileWithinWindow {
  param([string]$StartCommit, [int64]$StartUnix, [int]$WindowMinutes, [string]$FilePath)
  $untilUnix = $StartUnix + ($WindowMinutes * 60)
  $gitArgs = "log --format=format:%H --since=$StartUnix --until=$untilUnix --reverse -- `"$FilePath`""
  $out = Exec-Git $gitArgs -IgnoreErrors
  $list = $out -split "`n" | Where-Object { $_.Trim() -ne "" }
  foreach ($h in $list) {
    if ($h -ne $StartCommit) { return $h }
  }
  return $null
}

function Measure-Acceptance {
  param([int]$SinceDays, [string]$Author, [string]$Branch, [switch]$IgnoreComments, [int]$MinLineLength, [int]$ImmediateWindowMinutes)
  $commits = Get-Commits -SinceDays $SinceDays -Author $Author
  $rows = @()
  $fileCache = @{}
  foreach ($c in $commits) {
    $patch = Get-Patch -Commit $c.Hash
    $added = Get-AddedLinesFromPatch -Patch $patch

    if ($IgnoreComments) {
      $added = $added | Where-Object { -not (Is-CommentLine -Path $_.Path -Line $_.Line) }
    }
    if ($MinLineLength -gt 0) {
      $added = $added | Where-Object { $_.Line.Trim().Length -ge $MinLineLength }
    }

    if ($added.Count -eq 0) {
      $rows += [PSCustomObject]@{
        Commit                 = $c.Hash
        Date                   = ([DateTimeOffset]::FromUnixTimeSeconds($c.UnixTime)).ToString("u")
        FilesTouched           = 0
        LinesAdded             = 0
        SurvivedInHEAD         = 0
        SurvivalRate           = 0.0
        ImmediateReworkUnknown = $true
        ImmediateReworkRate    = ""
      }
      continue
    }

    # Build a set of files to check
    $files = $added | Select-Object -ExpandProperty Path -Unique
    foreach ($f in $files) {
      if (-not $fileCache.ContainsKey($f)) {
        $fileCache[$f] = Get-FileContentAt -Ref $Branch -Path $f
      }
    }

    $survived = 0
    foreach ($item in $added) {
      $content = $fileCache[$item.Path]
      if ($content -match [regex]::Escape($item.Line.Trim())) {
        $survived += 1
      }
    }

    # Immediate rework: compare presence in next commit affecting the file within window
    $nextCommit = $null
    $immediateReworkTotal = 0
    $immediateReworkMissing = 0
    foreach ($f in $files) {
      $nc = Get-NextCommitAffectingFileWithinWindow -StartCommit $c.Hash -StartUnix $c.UnixTime -WindowMinutes $ImmediateWindowMinutes -FilePath $f
      if ($nc) {
        if (-not $fileCache.ContainsKey("$nc`|$f")) {
          $fileCache["$nc`|$f"] = Get-FileContentAt -Ref $nc -Path $f
        }
        $nextContent = $fileCache["$nc`|$f"]
        $linesForFile = $added | Where-Object { $_.Path -eq $f }
        foreach ($item in $linesForFile) {
          $immediateReworkTotal += 1
          if (-not ($nextContent -match [regex]::Escape($item.Line.Trim()))) {
            $immediateReworkMissing += 1
          }
        }
      }
    }

    $survivalRate = if ($added.Count -gt 0) { [math]::Round($survived / $added.Count, 4) } else { 0 }
    $immediateRate = ""
    $immediateUnknown = $true
    if ($immediateReworkTotal -gt 0) {
      $immediateUnknown = $false
      $immediateRate = [math]::Round($immediateReworkMissing / $immediateReworkTotal, 4)
    }

    $rows += [PSCustomObject]@{
      Commit                 = $c.Hash
      Date                   = ([DateTimeOffset]::FromUnixTimeSeconds($c.UnixTime)).ToString("u")
      FilesTouched           = $files.Count
      LinesAdded             = $added.Count
      SurvivedInHEAD         = $survived
      SurvivalRate           = $survivalRate
      ImmediateReworkUnknown = $immediateUnknown
      ImmediateReworkRate    = $immediateRate
    }
  }

  return , $rows
}

# Compute and write CSV
$rows = Measure-Acceptance -SinceDays $SinceDays -Author $Author -Branch $Branch -IgnoreComments:$IgnoreComments -MinLineLength $MinLineLength -ImmediateWindowMinutes $ImmediateWindowMinutes

# Add a summary line
$totalAdded = ($rows | Measure-Object -Property LinesAdded -Sum).Sum
$totalSurvived = ($rows | Measure-Object -Property SurvivedInHEAD -Sum).Sum
$overallSurvival = if ($totalAdded -gt 0) { [math]::Round($totalSurvived / $totalAdded, 4) } else { 0 }

$knownImmediate = $rows | Where-Object { -not $_.ImmediateReworkUnknown }
if ($knownImmediate.Count -gt 0) {
  $immediateMissing = ($knownImmediate | Measure-Object -Property ImmediateReworkRate -Sum).Sum * 1.0
  $overallImmediate = [math]::Round(($immediateMissing / $knownImmediate.Count), 4)
}
else {
  $overallImmediate = ""
}

# Output CSV
$rows | Export-Csv -NoTypeInformation -Encoding UTF8 $Output

# Write a separate SUMMARY text file
$summary = @()
$summary += "AI Acceptance (Survival) Metrics Summary"
$summary += "SinceDays: $SinceDays"
if ($Author -ne "") { $summary += "Author filter: $Author" }
$summary += "Branch: $Branch"
$summary += "Total lines added: $totalAdded"
$summary += "Total survived in HEAD: $totalSurvived"
$summary += "Overall survival rate: $overallSurvival"
if ($overallImmediate -ne "") { $summary += "Average immediate rework rate (within $ImmediateWindowMinutes min): $overallImmediate" } else { $summary += "Immediate rework rate: N/A" }
$summaryText = ($summary -join "`r`n")
[IO.File]::WriteAllText("ai_acceptance_summary.txt", $summaryText, [Text.Encoding]::UTF8)

Write-Host "Done. Wrote $($rows.Count) commit rows to $Output"
Write-Host "Overall survival rate (proxy for corrected acceptance): $overallSurvival"
Write-Host "Summary saved to ai_acceptance_summary.txt"
