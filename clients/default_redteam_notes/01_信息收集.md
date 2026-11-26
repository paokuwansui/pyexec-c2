# 第1章 信息收集

## 目标

收集 IP、端口、账号密码、主机信息、数据库结构、文件与业务数据，为后续授权测试提供支撑。

## 端口扫描

- TCP Connect / SYN 扫描：SYN 扫描不完成三次握手，速度快但需要原始包权限。
- 先扫描网关常见地址 `.1`、`.254`，再扩展整个网段。
- ICMP 可用时先做存活探测，再针对存活主机扫描端口。
- 控制扫描速率，避免触发防护和影响业务。

```bash
# fscan 仅端口探测：禁用爆破、POC 和 ICMP
fscan.exe -h 192.168.0.0/16 -nobr -nopoc -np
fscan.exe -h 192.168.0.0/16 -nobr -nopoc -np -p 135,445,5985,22,3306,1433

# masscan
masscan -iL ip.txt -p 1433,445 --rate=1000 -oL out.txt

# 生成网段网关地址字典（Linux）
for b in {1..254}; do for c in {1..254}; do echo "10.$b.$c.1" >> ip.txt; echo "10.$b.$c.254" >> ip.txt; done; done
```

## 口令爆破

- 只对明确授权的资产和账号进行测试。
- 注意账号锁定策略，优先少量账号、低频率验证。
- 常见协议：SMB、RDP、SSH、MySQL、MSSQL、WinRM。

```bash
fscan.exe -h 192.168.1.0/24 -m ssh -p 22 -nopoc
fscan.exe -h 192.168.1.0/24 -m rdp -p 3389 -nopoc
fscan.exe -h 192.168.1.0/24 -m smb -p 445 -nopoc
```

## 主机与目录信息

Windows：

```cmd
tasklist /svc
ipconfig /all
netstat -ano
net user
net localgroup administrators
cmdkey /list
klist
dir /s c:\users\
wmic product get name,version,vendor,installlocation
```

Linux：

```bash
ps aux
netstat -antp
last
cat /etc/passwd
cat /etc/hosts
cat ~/.bash_history
ls -alh ~/.ssh/
```

## 数据库信息

- MySQL：查 `information_schema.COLUMNS`、`information_schema.tables`，找 `pass/pwd` 字段。
- MSSQL：查 `syscolumns`、`sysobjects`、`sysindexes`，统计表行数并找敏感字段。
- Oracle：查 `DBA_TAB_COLUMNS`、`ALL_TABLES`、`all_tab_comments`，从 `NUM_ROWS` 找大表。

## 数据分析

- 打包前先做文件列表，避免把系统日志、缓存等无关内容一起带走。
- Windows 可用 `rar`、`7z`、`makecab`；Linux 可用 `tar`。
- 文档和软件在断网、隔离的虚拟机中查看。
- 大目录可先导出文件列表，再回传分析，不要直接全量下载。
## 命令速查

### fscan

```text
# 仅端口，不爆破/POC，不用 ICMP
fscan.exe -h <CIDR> -nobr -nopoc -np -p 22,80,135,139,443,445,1433,3306,3389,5985

# 从文件读取目标
fscan.exe -hf targets.txt -nobr -nopoc -np

# 查看模块名
fscan.exe -h 127.0.0.1 -m help
```

提示：`-nobr` 关闭爆破、`-nopoc` 关闭漏洞扫描、`-np` 跳过 ICMP 存活探测；结果通常写入 `result.txt`。

### masscan

```bash
masscan <CIDR> -p 22,80,443,445,1433,3306,3389 --rate=1000 -oL masscan.txt
masscan -iL targets.txt -p 445,1433 --rate=500 -oL masscan.txt
```

提示：`--rate` 必须按授权范围调整；高速扫描容易影响业务和触发防护。

### Windows 主机信息

```cmd
tasklist /svc
wmic process get ProcessId,CommandLine
ipconfig /all
netstat -ano
net user
net localgroup administrators
cmdkey /list
klist
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
wmic product get name,version,vendor,installlocation
wmic /namespace:\\root\SecurityCenter2 PATH AntiVirusProduct GET /value
type c:\windows\system32\inetsrv\config\applicationHost.config
dir /s c:\users\
```

### Linux 主机信息

```bash
ps aux
ss -antp
last
cat /etc/passwd
cat /etc/hosts
cat ~/.bash_history
cat ~/.ssh/known_hosts
ls -alh ~/.ssh/
find / -type f 2>/dev/null | head -200
```

### 数据库

```sql
-- MySQL：表字段
SELECT CONCAT(TABLE_SCHEMA,'.',TABLE_NAME),COLUMN_NAME,COLUMN_TYPE
FROM information_schema.COLUMNS
WHERE table_schema NOT IN ('mysql','sys','information_schema','performance_schema');

-- MySQL：表行数
SELECT CONCAT(table_schema,'.',table_name),table_rows,table_comment
FROM information_schema.tables
ORDER BY table_rows DESC;
```

```sql
-- MSSQL：当前库表结构
USE <DBNAME>;
SELECT sysobjects.name AS tablename, syscolumns.name AS columnname
FROM sysobjects JOIN syscolumns ON sysobjects.id=syscolumns.id
WHERE sysobjects.xtype='U'
  AND (syscolumns.name LIKE '%pass%' OR syscolumns.name LIKE '%pwd%');
```

```sql
-- Oracle：字段
SELECT OWNER,TABLE_NAME,COLUMN_NAME
FROM DBA_TAB_COLUMNS
WHERE OWNER='<DBNAME>';
```
