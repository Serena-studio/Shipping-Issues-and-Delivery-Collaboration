# -*- coding: utf-8 -*-
"""config.py —— 配置加载模块。

职责：唯一允许读取 config.yaml 的模块；其他代码一律通过本模块拿配置，
保证"配置集中在 config.yaml、代码里不出现模型地址与密钥"的代码规范。
"""
# 导入 os：用于读取环境变量（AGENT_DB_PATH / AGENT_LLM_KEY）
import os
# 导入 pathlib：跨平台路径处理
from pathlib import Path
# 导入 yaml：解析 config.yaml
import yaml

# 计算项目根目录：config.py 位于 app/ 下，其父目录即项目根
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 配置缓存：避免每个请求都重复读盘
_config_cache = None


def load_config(force_reload: bool = False) -> dict:
    """加载并缓存 config.yaml 的全部配置。

    入参：force_reload —— 是否强制重新读盘（默认 False 用缓存）。
    出参：dict，config.yaml 解析后的完整配置树。
    失败行为：config.yaml 不存在或 YAML 语法错误时抛出 FileNotFoundError /
    yaml.YAMLError，由调用方（FastAPI 启动逻辑）终止启动——配置坏了绝不带病运行。
    """
    # 声明引用全局缓存变量
    global _config_cache
    # 已有缓存且不强制刷新时直接返回，减少磁盘 IO
    if _config_cache is not None and not force_reload:
        # 返回缓存副本，防止调用方误改缓存
        return dict(_config_cache)
    # 拼出 config.yaml 的绝对路径
    cfg_path = PROJECT_ROOT / "config.yaml"
    # 文件不存在直接报错：这是启动期致命错误
    if not cfg_path.exists():
        # 抛出异常并给出中文提示，方便定位
        raise FileNotFoundError(f"缺少配置文件：{cfg_path}")
    # 以 UTF-8 打开并解析 YAML（Windows 默认编码不是 UTF-8，必须显式指定）
    with open(cfg_path, "r", encoding="utf-8") as f:
        # yaml.safe_load 只解析基础类型，防止反序列化任意对象的安全风险
        cfg = yaml.safe_load(f)
    # 写入缓存
    _config_cache = cfg
    # 返回缓存副本
    return dict(_config_cache)


def get_db_path() -> Path:
    """获取 SQLite 数据库文件的绝对路径。

    入参：无。
    出参：Path 对象，指向数据库文件（data/agent.db 或环境变量覆盖值）。
    失败行为：配置缺失 storage.db_path 时抛 KeyError，属配置错误，启动期即暴露。
    """
    # 读取 storage 配置段
    db_rel = load_config()["storage"]["db_path"]
    # 环境变量 AGENT_DB_PATH 优先：供 pytest 用临时库做测试隔离，避免污染正式库
    override = os.environ.get("AGENT_DB_PATH")
    # 有覆盖值时用覆盖值，否则用配置值，并转成绝对路径
    return Path(override) if override else PROJECT_ROOT / db_rel


def get_llm_config() -> dict:
    """获取 LLM 接入配置（阶段2 起使用）。

    入参：无。
    出参：dict，含 base_url / api_key / model / temperature。
    失败行为：密钥环境变量 AGENT_LLM_KEY 存在时覆盖配置占位符；
    两者都是占位符时原样返回，由调用方在真正调用 LLM 前校验并报错。
    """
    # 取 llm 配置段副本
    llm = dict(load_config()["llm"])
    # 环境变量优先：真实密钥只进环境变量，绝不进代码与配置文件
    env_key = os.environ.get("AGENT_LLM_KEY")
    # 存在真实密钥时覆盖占位符
    if env_key:
        # 覆盖 api_key 字段
        llm["api_key"] = env_key
    # 返回 LLM 配置
    return llm
