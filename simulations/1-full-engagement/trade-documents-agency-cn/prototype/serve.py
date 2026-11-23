# -*- coding: utf-8 -*-
"""serve.py —— 单端口部署入口。

用途：发布沙盒只暴露一个 HTTP 端口，本脚本从环境变量 PORT 读取端口，
绑定 0.0.0.0，由 uvicorn 同时提供网站页面与 /api 接口。
启动：python serve.py
"""
# 导入 os：读取部署平台注入的 PORT 环境变量
import os
# 导入 uvicorn：ASGI 服务器
import uvicorn


def main() -> None:
    """启动服务：监听 PORT 环境变量，绑定所有网卡。

    入参：无。
    出参：无（阻塞运行直到进程被终止）。
    失败行为：PORT 非整数时抛 ValueError，部署平台会捕获为启动失败——
    为什么这么卡：端口是唯一外部入口，配置错误必须快速失败，不能悄悄回退到固定端口。
    """
    # 读取端口：部署沙盒注入 PORT，本地默认 8000
    port = int(os.environ.get("PORT", "8000"))
    # 启动 uvicorn：host 必须是 0.0.0.0，否则反向代理无法访问
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    # 直接运行时进入主流程
    main()
