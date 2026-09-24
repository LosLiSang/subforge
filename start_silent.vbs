Set WshShell = CreateObject("WScript.Shell")
' 启动 SubForge UI：后台静默运行（无黑框），不自动弹浏览器，开启本地免 Token 访问
' 如果需要使用固定 Token 模式，可将 --no-auth 改为 --token 你的密码
ScriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.Run "cmd /c cd /d """ & ScriptDir & """ && uv run subforge ui --no-browser --no-auth", 0, False
