# 第9章 发现域和进入域

## 判断是否在域

```cmd
ipconfig /all
net config workstation
```

- 关注 DNS 后缀、域名、登录用户、域控制器地址。
- LDAP 默认使用 389/636，Kerberos 使用 88。

## 进入域

- 通过 SMB 445 验证域账号时注意账号锁定。
- LDAP 389/636 可用于域账号验证和信息查询。
- 爆破仅限授权范围，并优先使用低频率、少量账号。
- 获取域机器权限后先确认当前机器是否在域、域控位置和 DNS 配置。
## 命令速查

```cmd
ipconfig /all
net config workstation
nltest /dsgetdc:<DOMAIN>
nltest /trusted_domains
net view /domain
net group "domain controllers" /domain
```

```text
# 域服务端口
88/tcp    Kerberos
135/tcp   RPC
139/445   SMB
389/636   LDAP/LDAPS
5985/5986 WinRM
```

```cmd
# 通过 SMB 验证域账号（注意锁定策略）
net use \\<TARGET> /user:<DOMAIN>\<USER> <PASSWORD>
net use * /delete /y
```

```text
# LDAP 查询入口
ldapsearch -x -H ldap://<DC> -D '<USER>@<DOMAIN>' -w '<PASSWORD>' -b 'DC=<DOMAIN>,DC=<TLD>'
```
