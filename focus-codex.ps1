$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class CodexFocusWindow {
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
 [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr window,int cmd);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}
'@
function Get-CodexWindows {
 @(Get-Process -Name ChatGPT,Codex -ErrorAction SilentlyContinue | Where-Object {
  $_.MainWindowHandle -ne 0 -and $_.Path -match 'OpenAI|OpenAI\.Codex'
 })
}
$targets=Get-CodexWindows
if(-not $targets.Count){
 Start-Process explorer.exe -ArgumentList 'shell:AppsFolder\OpenAI.Codex_2p2nqsd0c76g0!App' -WindowStyle Hidden
 for($attempt=0;$attempt -lt 40;$attempt++){
  Start-Sleep -Milliseconds 200
  $targets=Get-CodexWindows
  if($targets.Count){break}
 }
}
$foreground=[CodexFocusWindow]::GetForegroundWindow()
$active=@($targets | Where-Object MainWindowHandle -eq $foreground)
if($active.Count -eq 1){$target=$active[0]}
elseif($targets.Count -eq 1){$target=$targets[0]}
else{throw 'Cannot uniquely identify a Codex window'}
[void][CodexFocusWindow]::ShowWindowAsync($target.MainWindowHandle,9)
[void][CodexFocusWindow]::SetForegroundWindow($target.MainWindowHandle)
$window=[Windows.Automation.AutomationElement]::FromHandle($target.MainWindowHandle)
$condition=[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ControlTypeProperty,[Windows.Automation.ControlType]::Edit)
$editors=@($window.FindAll([Windows.Automation.TreeScope]::Descendants,$condition) | Where-Object {
 $_.Current.IsEnabled -and -not $_.Current.IsOffscreen -and $_.Current.IsKeyboardFocusable -and
 $_.Current.Name -match 'Codex'
})
if($editors.Count -ne 1){throw 'Codex composer is unavailable or ambiguous; no key was sent'}
$editors[0].SetFocus()
$focused=[Windows.Automation.AutomationElement]::FocusedElement
if(-not [Windows.Automation.Automation]::Compare($focused,$editors[0])){throw 'Composer focus could not be confirmed'}
Write-Output 'Codex composer focused; no text entered or sent'
