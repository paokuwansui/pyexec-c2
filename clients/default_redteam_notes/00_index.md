# 红队笔记索引与命令速查

本目录是系统自带红队笔记，默认按章节拆分，导入记事本后会显示在“红队笔记”区域。

## 使用说明

- 仅限授权的内网渗透测试、攻防演练和自有实验环境。
- 默认 `ai_skill=false`，需要让 AI Agent 使用某一章时，到 AI 配置 → Skills 中启用。
- 开启 AI Skill 后，笔记标题和内容会进入 Agent 系统提示词，请勿在其中保存真实凭据。

## 人类速查方式

- 在记事本中直接搜索工具名或协议名：`fscan`、`masscan`、`frp`、`mimikatz`、`schtasks`、`wmic`、`BloodHound`、`certipy`、`ntlmrelayx`。
- 每章末尾的“命令速查”只使用占位符：`<TARGET>`、`<DOMAIN>`、`<USER>`、`<PASSWORD>`、`<HASH>`、`<COMMAND>`。
- 执行前逐项替换占位符；不要直接复制未经确认的 IP、域名或凭据。
- 先读“前置条件/风险”，再复制命令。

## 章节工具索引

| 章节 | 主要工具/关键词 |
|---|---|
| 第1章 信息收集 | fscan、masscan、Railgun、CrackMapExec、mimikatz、AdFind、PowerGREP |
| 第2章 下载与执行 | PowerShell、CertUtil、bitsadmin、wmic、schtasks、sc、msiexec、regsvr32 |
| 第3章 通道构建 | frp、pingtunnel、spp、stowaway、iodine、v2ray、Neo-reGeorg、goproxy、proxychains |
| 第4章 密码获取 | mimikatz、secretsdump、procdump、SharpDPAPI、HackBrowserData、LaZagne、hashcat |
| 第5章 权限提升 | UACME、SharpBypassUAC、JuicyPotato、PrintSpoofer、SweetPotato、linux-exploit-suggester |
| 第6章 横向移动 | schtasks、sc、wmic、winrs、wmiexec、psexec、CrackMapExec、SharpSQLTools |
| 第7章 权限维持 | schtasks、WMI subscription、Run 注册表、systemd、crontab、SSH/PAM、触发器 |
| 第8章 痕迹清理 | wevtutil、attrib、timestomp、sed、history、logman |
| 第9章 发现域和进入域 | ipconfig、net config、nltest、net use、ldapsearch |
| 第10章 域信息收集 | net、setspn、AdFind、dsquery/dsget、dnscmd、SharpAdidnsdump |
| 第11章 域控制器权限获取分析 | mscan、SharpHound/BloodHound、AdFind、dsacls、certipy、ZeroLogon、noPac |
| 第12章 NTLM 中继 | Responder、ntlmrelayx、PetitPotam、printerbug、certipy relay、RelayX |
| 第13章 域管权限利用分析 | ntdsutil、vssadmin、DCSync、secretsdump、CrackMapExec、SharpGPOAbuse |
| 第14章 域后门分析 | DCSync ACL、AdminSDHolder、Whisker、SIDHistory、DCShadow、Rubeus |
| 第15章 Exchange 权限利用分析 | ruler、owa_info、ProxyLogon、ProxyShell、ProxyNotShell、Exchange Management Shell |

## 命令占位符

```text
<TARGET>       目标 IP / 主机名
<CIDR>         授权网段
<DOMAIN>       域名，如 test.local
<TLD>          顶级域，如 local、com
<DC>           域控制器 IP / 主机名
<USER>         授权账号
<PASSWORD>     授权口令
<HASH>         NTLM Hash / 其他散列
<COMMAND>      要执行的命令
<TASK>         任务计划名称
<SERVICE>      服务名称
<TOKEN>        frp / 隧道令牌
```
