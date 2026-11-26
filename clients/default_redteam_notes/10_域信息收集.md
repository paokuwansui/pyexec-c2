# 第10章 域信息收集

## net 命令

```cmd
net user /domain
net group /domain
net group "domain admins" /domain
net group "domain computers" /domain
net group "domain controllers" /domain
```

## SPN

```cmd
setspn -q */*
```

SPN 可用于定位 LDAP、MSSQL、Exchange、IIS、RDP 等服务。

## LDAP 查询

- AdFind、dsquery/dsget。
- 常用属性：`sAMAccountName`、`objectSid`、`operatingSystem`、`servicePrincipalName`、`msDS-AllowedToDelegateTo`。
- 查询用户、组、计算机、OU、GPO、信任域、委派、ACL。

```cmd
AdFind.exe -sc u:* name sAMAccountName objectSid
AdFind.exe -sc c:* sAMAccountName
dsquery.exe * -filter "(&(objectcategory=computer)(operatingSystem=*2012*))" -limit 0
```

## DNS

- `SharpAdidnsdump` 可用于授权内网 DNS 信息收集。
- 域控上可用 `dnscmd /EnumRecords`。
- 不要在代理环境中直接做大量 DNS 解析，以免产生异常流量。
## 命令速查

### net / SPN

```cmd
net user /domain
net group /domain
net group "domain admins" /domain
net group "domain computers" /domain
net group "domain controllers" /domain
setspn -q */*
```

### AdFind

```cmd
AdFind.exe -h <DC> -u <USER> -up <PASSWORD> -sc u:* name sAMAccountName objectSid
AdFind.exe -h <DC> -u <USER> -up <PASSWORD> -sc c:* sAMAccountName
AdFind.exe -h <DC> -u <USER> -up <PASSWORD> -sc g:* sAMAccountName description
AdFind.exe -h <DC> -u <USER> -up <PASSWORD> -f "(&(msds-allowedtodelegateto=*))" distinguishedName msDS-AllowedToDelegateTo
AdFind.exe -h <DC> -u <USER> -up <PASSWORD> -f "(&(userAccountControl:1.2.840.113556.1.4.803:=524288))"
AdFind.exe -h <DC> -u <USER> -up <PASSWORD> -f "(&(objectClass=trustedDomain))"
```

### dsquery/dsget

```cmd
dsquery.exe * -limit 0 -s <DC> -u <USER> -p <PASSWORD>
dsquery.exe user -limit 0 -s <DC> -u <USER> -p <PASSWORD>
dsquery.exe computer -limit 0 -s <DC> -u <USER> -p <PASSWORD>
dsquery.exe group -name "Domain Admins" | dsget group -expand -members
dsquery.exe * -filter "(&(objectcategory=computer)(servicePrincipalName=ldap*))" -limit 0
```

### DNS

```cmd
dnscmd <DC> /EnumRecords <DOMAIN>
nslookup <HOST> <DC>
```
