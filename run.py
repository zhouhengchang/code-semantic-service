"""
启动入口（部署平台只需执行 python run.py）

为什么不用 `uvicorn core.main:app --port $PORT`：
部分部署平台的启动命令不会展开环境变量，直接把 `$PORT` 当字符串传给 uvicorn 会报
「--port requires an argument」。这里在 Python 里读环境变量，最稳。
"""

import os

import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("core.main:app", host=host, port=port, log_level="info")
