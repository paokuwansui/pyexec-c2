# 第8章 痕迹清理

## 删除文件

- 普通删除不等于安全擦除；可用大文件覆盖原磁盘区域降低恢复概率。
- 重要环境应先保留证据，再按授权要求处理。

## Windows

```cmd
wevtutil.exe cl "System"
wevtutil.exe cl "Security"
wevtutil.exe cl "Application"
wmic nteventlog where filename!='' cleareventlog
reg query HKLM\Software\Microsoft\Windows\CurrentVersion\Policies\System\Audit /v ProcessCreationIncludeCmdLine_Enabled
reg add HKLM\Software\Microsoft\Windows\CurrentVersion\Policies\System\Audit /v ProcessCreationIncludeCmdLine_Enabled /t REG_DWORD /d 0
```

- Sysmon/ETW 日志抑制与清理属于高风险操作，需确认授权和检测影响。

## Linux

```bash
last
lastip=$(last -i -n 1 | head -n 1 | awk '{print $3}')
sed -i "/$lastip/d" /var/log/wtmp
touch -r /bin/bash /tmp/tool
```

- 清理登录日志、命令历史、文件时间戳前必须确认审计和取证要求。

## 注意

- 防守方通常会集中收集日志；仅删除本机日志不一定能清除 SIEM/EDR 记录。
- 任何清理操作都必须记录在授权测试报告中。
## 命令速查

### Windows

```cmd
wevtutil.exe cl "System"
wevtutil.exe cl "Security"
wevtutil.exe cl "Application"
wevtutil.exe cl "Microsoft-Windows-PowerShell/Operational"
wmic nteventlog where filename!='' cleareventlog
reg query HKLM\Software\Microsoft\Windows\CurrentVersion\Policies\System\Audit /v ProcessCreationIncludeCmdLine_Enabled
attrib +s +a +r +h C:\ProgramData\tool.exe
powershell -c "(Get-Item C:\ProgramData\tool.exe).LastWriteTime='03/11/2018 22:13:36'"
```

### Linux

```bash
last
last -i -n 5
sed -i '/<IP>/d' /var/log/wtmp
sed -i '/<IP>/d' /var/log/secure
unset HISTFILE HISTFILESIZE
export HISTFILE=/dev/null HISTSIZE=0 HISTFILESIZE=0
touch -r /bin/bash /tmp/tool
```

### 注意

- 仅清理授权范围内的测试痕迹，不要破坏取证或业务日志。
- 本机日志清理通常无法删除 SIEM/EDR 的集中日志。
- 删除前先保存测试记录；报告里写明清理项和未清理项。
