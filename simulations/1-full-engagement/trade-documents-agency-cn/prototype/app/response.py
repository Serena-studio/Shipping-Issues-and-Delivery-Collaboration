# -*- coding: utf-8 -*-
"""response.py —— 统一响应结构模块。

代码规范要求所有对外接口返回：{"ok": bool, "data": ..., "error": {"code": str, "msg": str}}
本模块是该结构的唯一构造入口，保证全系统响应格式一致。
"""
# 导入 typing 的 Any：标注 data 参数可为任意类型
from typing import Any


def ok(data: Any = None) -> dict:
    """构造成功响应。

    入参：data —— 业务数据，默认 None（如健康检查无数据体）。
    出参：dict，形如 {"ok": True, "data": data, "error": None}。
    失败行为：无（纯构造函数）。
    """
    # 成功时 ok=True，error 固定为 None，保持三种键始终存在、结构可预测
    return {"ok": True, "data": data, "error": None}


def err(code: str, msg: str) -> dict:
    """构造失败响应。

    入参：code —— 机器可读错误码（如 NOT_FOUND / FORBIDDEN）；msg —— 中文可读信息。
    出参：dict，形如 {"ok": False, "data": None, "error": {"code": ..., "msg": ...}}。
    失败行为：无（纯构造函数）。
    """
    # 失败时 ok=False，data 固定为 None；error 内层只放码与文案两个字段
    return {"ok": False, "data": None, "error": {"code": code, "msg": msg}}
