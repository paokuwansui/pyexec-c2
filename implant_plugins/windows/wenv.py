import json
import os

PLUGIN = {"name": "Windows 环境变量", "commands": ["wenv"], "platform": "windows", "risk": "R1", "description": "Python 实现的 env", "write_disk": False}


def run(runtime, args):
    data = dict(sorted(os.environ.items()))
    runtime.emit(json.dumps(data, ensure_ascii=False, indent=2))
    return {"environment": data}
