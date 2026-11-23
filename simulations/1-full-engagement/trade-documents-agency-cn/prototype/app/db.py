# -*- coding: utf-8 -*-
"""db.py —— SQLite 建表与连接模块。

职责：管理唯一的数据库连接入口与五类表结构（单证/版本/交接/审计/人工队列）。
不用 ORM（指令要求），直接使用 sqlite3 标准库。
"""
# 导入 sqlite3：标准库，无第三方依赖
import sqlite3
# 导入 Path：路径处理
from pathlib import Path
# 导入 contextmanager：写"with conn:"风格的连接上下文管理器
from contextlib import contextmanager
# 导入项目配置模块：获取数据库路径
from app.config import get_db_path


def get_conn() -> sqlite3.Connection:
    """获取一个已配置好行工厂的 SQLite 连接。

    入参：无（库路径来自 config / 环境变量覆盖）。
    出参：sqlite3.Connection，查询结果可直接按列名取值。
    失败行为：目录不存在会自动创建；磁盘/权限异常抛 sqlite3.OperationalError 由上层转 500。
    """
    # 取数据库绝对路径
    db_path: Path = get_db_path()
    # 确保父目录存在（首次运行 data/ 目录尚不存在）
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # 建立连接；check_same_thread=False 是因为 FastAPI 线程池可能跨线程使用连接，
    # SQLite 自身在每条 SQL 层面加锁，演示环境单写者足够安全
    conn = sqlite3.connect(db_path, check_same_thread=False)
    # 设置行工厂：让 SELECT 结果支持 row["列名"] 访问，替代脆弱的下标访问
    conn.row_factory = sqlite3.Row
    # 返回配置好的连接
    return conn


@contextmanager
def db_session():
    """数据库会话上下文管理器：自动提交或回滚。

    入参：无。
    出参：yield 一个 sqlite3.Connection，用法 `with db_session() as conn: ...`。
    失败行为：块内抛异常时自动 rollback 并向上抛出，保证不出现半提交的脏数据——
    这对"导入器必须整包原子写入"的红线要求（f33 问题记录保留原行）是必要的。
    """
    # 获取新连接
    conn = get_conn()
    try:
        # yield 连接给 with 块使用
        yield conn
        # 块内无异常则提交
        conn.commit()
    except Exception:
        # 任何异常先回滚，保证原子性
        conn.rollback()
        # 再把异常抛给调用方处理
        raise
    finally:
        # 无论成败都关闭连接，防止文件句柄泄漏
        conn.close()


# 五类表的建表语句：全部带 IF NOT EXISTS，重复执行安全（幂等）
_SCHEMA = """
-- 表1：单证表（一票多单：发票/装箱单/订单，payload 存白名单字段的原始 JSON）
CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT, -- 自增主键
    pack_id       TEXT NOT NULL,                     -- 单证包编号（演练无统一编号 f30，由导入器生成临时包号）
    doc_type      TEXT NOT NULL,                     -- 单证类型：invoice/packing_list/order
    doc_no        TEXT NOT NULL,                     -- 单据号（单据自身编号）
    payload       TEXT NOT NULL,                     -- 原始字段 JSON（保留原行 f33：问题记录不改写原文）
    source_file   TEXT NOT NULL,                     -- 来源文件标注（f42：结果需关联来源）
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')) -- 本系统接收时间
);

-- 表2：版本表（版本双条件 f24：有效期 + 确认状态；作废保留原因）
CREATE TABLE IF NOT EXISTS versions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT, -- 自增主键
    doc_id        INTEGER NOT NULL REFERENCES documents(id), -- 归属单证
    version_no    TEXT NOT NULL,                     -- 版本号（如 v1/v2）
    is_effective  INTEGER NOT NULL DEFAULT 1,        -- 版本有效期：1=有效 0=已过期（双条件之一）
    confirm_state TEXT NOT NULL DEFAULT 'pending',   -- 确认状态：pending/confirmed/voided（双条件之二）
    void_reason   TEXT,                              -- 作废原因（f24：作废必须保留原因）
    valid_until   TEXT,                              -- 有效期截止（未定口径前允许为空，属待核实项）
    business_time TEXT,                              -- 业务发生时间（f34 双时间戳之一）
    system_time   TEXT NOT NULL DEFAULT (datetime('now','localtime')), -- 系统接收时间（f34 双时间戳之二）
    UNIQUE(doc_id, version_no)                       -- 同一单证版本号唯一，防重复导入
);

-- 表3：交接表（f20/f23：每次交接记录接收人、版本、未结项、截止时间）
CREATE TABLE IF NOT EXISTS handovers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT, -- 自增主键
    pack_id       TEXT NOT NULL,                     -- 所属单证包
    node          TEXT NOT NULL,                     -- 交接发生的链路节点（五段之一）
    from_role     TEXT NOT NULL,                     -- 交接方角色
    to_role       TEXT NOT NULL,                     -- 接收方角色
    version_no    TEXT NOT NULL,                     -- 交接涉及的版本号
    open_items    TEXT NOT NULL DEFAULT '',          -- 未结项清单（f23：不能只发"已处理"）
    deadline      TEXT,                              -- 截止时间（f23：交接必须列明）
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')) -- 登记时间
);

-- 表4：审计表（f45：谁查过、用哪个版本、提什么建议、谁确认，不得只留摘要）
CREATE TABLE IF NOT EXISTS audit_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT, -- 自增主键
    actor         TEXT NOT NULL,                     -- 操作人姓名
    role_key      TEXT NOT NULL,                     -- 操作人角色键（对应 config.roles）
    action        TEXT NOT NULL,                     -- 动作：query/import/suggest/confirm/queue
    pack_id       TEXT,                              -- 涉及单证包（可空：如全库查询）
    doc_id        INTEGER,                           -- 涉及单证（可空）
    version_no    TEXT,                              -- 涉及版本（可空）
    detail        TEXT NOT NULL DEFAULT '',          -- 动作详情 JSON（完整留痕，非摘要）
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')) -- 发生时间（系统时间）
);

-- 表5：人工队列表（f44：存疑一律进队列、必要时暂停，禁止默认通过）
CREATE TABLE IF NOT EXISTS manual_queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT, -- 自增主键
    pack_id       TEXT NOT NULL,                     -- 所属单证包
    doc_id        INTEGER REFERENCES documents(id),  -- 涉及单证（可空：包级暂停）
    version_no    TEXT,                              -- 涉及版本（可空）
    reason        TEXT NOT NULL,                     -- 进队列原因（如：版本未同步/字段缺失）
    status        TEXT NOT NULL DEFAULT 'open',      -- 状态：open/confirmed/paused
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')), -- 入队时间
    resolved_by   TEXT,                              -- 处理人（傅景角色，f44）
    resolved_at   TEXT                               -- 处理时间
);

-- 审计表查询索引：按操作人与时间检索是审计高频路径
CREATE INDEX IF NOT EXISTS idx_audit_actor_time ON audit_logs(actor, created_at);
-- 人工队列状态索引：队列出口需要快速捞 open 状态
CREATE INDEX IF NOT EXISTS idx_queue_status ON manual_queue(status);
"""


def init_db() -> None:
    """初始化数据库：建目录、建五类表与索引。

    入参：无。
    出参：无（副作用：数据库文件与表结构就绪）。
    失败行为：SQL 语法错误或磁盘异常抛 sqlite3.Error，启动期直接失败——
    宁可起不来也不让业务跑在残缺表结构上（红线优先于可用性）。
    """
    # 打开独立连接执行建表（建表是启动期一次性动作，不需要会话管理器）
    conn = get_conn()
    try:
        # 逐语句执行整个建表脚本；executescript 自带提交语义
        conn.executescript(_SCHEMA)
        # 显式提交，保证建表立即落盘
        conn.commit()
    finally:
        # 关闭连接
        conn.close()
