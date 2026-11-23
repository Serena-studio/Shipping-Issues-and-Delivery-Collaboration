# -*- coding: utf-8 -*-
"""importer.py —— 只读数据导入器。

红线说明（f32）：本系统只对接"脱敏只读导出数据源"。导入器只做一件事——
把只读导出的合成样本 JSON 灌入本系统自己的 SQLite 库；不提供任何写回源系统的接口。
导入动作本身会写审计留痕（f45：谁导入了什么）。
"""
# 导入 json：解析样本文件
import json
# 导入 Path：定位样本文件
from pathlib import Path
# 导入项目模块：配置、数据库会话
from app.config import load_config, PROJECT_ROOT
from app.db import db_session


def import_samples(actor: str = "system", sample_file: str = None) -> dict:
    """把合成样本 JSON 整包导入数据库（幂等：已存在的包跳过）。

    入参：actor —— 执行导入的操作人（审计留痕用）；sample_file —— 样本文件相对路径
          （默认 app/samples/sample_documents.json，供测试注入其他样本）。
    出参：dict，{"imported_packs": 新导入包号列表, "skipped_packs": 已存在跳过的包号列表}。
    失败行为：样本 JSON 非法或结构缺失抛 ValueError/json.JSONDecodeError；
    任一包写库失败时整个事务回滚（db_session 保证），不会出现半包脏数据。
    """
    # 读链路节点配置：用于校验样本里的交接节点必须属于五段链路（防脏数据入库）
    cfg = load_config()
    # 取五段节点列表
    valid_nodes = cfg["chain_nodes"]
    # 拼样本文件绝对路径（未指定则用内置样本）
    path = PROJECT_ROOT / sample_file if sample_file else PROJECT_ROOT / "app/samples/sample_documents.json"
    # 以 UTF-8 读取并解析样本（Windows 下必须显式 utf-8）
    with open(path, "r", encoding="utf-8") as f:
        # 解析 JSON
        data = json.load(f)
    # 结果收集器：新导入与跳过的包号
    imported, skipped = [], []
    # 打开一个数据库会话：整包导入在同一事务内，失败全回滚
    with db_session() as conn:
        # 逐包处理
        for pack in data["packs"]:
            # 取包号
            pack_id = pack["pack_id"]
            # 幂等检查：该包已导入过则跳过（以单证表里是否存在该包为准）
            exists = conn.execute(
                # 查询该包是否已有单证记录
                "SELECT 1 FROM documents WHERE pack_id = ? LIMIT 1", (pack_id,)
            ).fetchone()
            # 已存在则记录跳过并继续下一包
            if exists:
                # 记入跳过列表
                skipped.append(pack_id)
                # 跳过本包
                continue
            # 逐单证写入：先 documents 拿 doc_id，再写 versions
            for doc in pack["documents"]:
                # 插入单证主记录；payload 存 JSON 字符串保留原始行（f33：问题记录保留原行，不改写）
                cur = conn.execute(
                    # 参数化 SQL 防注入
                    "INSERT INTO documents(pack_id, doc_type, doc_no, payload, source_file) VALUES (?,?,?,?,?)",
                    # payload 用 ensure_ascii=False 保留中文可读性
                    (pack_id, doc["doc_type"], doc["doc_no"], json.dumps(doc["payload"], ensure_ascii=False), doc["source_file"]),
                )
                # 取回刚插入的自增 doc_id
                doc_id = cur.lastrowid
                # 逐版本写入版本表（双条件字段：is_effective + confirm_state，f24）
                for ver in doc["versions"]:
                    # 插入版本记录；system_time 由表默认值自动写入（f34 双时间戳之二）
                    conn.execute(
                        # 唯一约束(doc_id, version_no)防同包同单重复版本
                        "INSERT INTO versions(doc_id, version_no, is_effective, confirm_state, void_reason, valid_until, business_time) VALUES (?,?,?,?,?,?,?)",
                        # None 字段（如 void_reason）允许为空
                        (doc_id, ver["version_no"], ver["is_effective"], ver["confirm_state"], ver.get("void_reason"), ver.get("valid_until"), ver.get("business_time")),
                    )
            # 逐交接写入交接表（f20/f23：接收人、版本、未结项、截止时间缺一不可）
            for hv in pack.get("handovers", []):
                # 交接节点必须在五段链路内：不属于链路的脏数据直接拒绝——为什么这么卡：
                # 链路外节点意味着流程口径与 f01 不一致，留着会污染后续定位
                if hv["node"] not in valid_nodes:
                    # 抛异常触发整包回滚
                    raise ValueError(f"样本包 {pack_id} 交接节点 {hv['node']} 不在五段链路内")
                # 插入交接记录
                conn.execute(
                    # 参数化插入
                    "INSERT INTO handovers(pack_id, node, from_role, to_role, version_no, open_items, deadline) VALUES (?,?,?,?,?,?,?)",
                    # 交接字段逐一对应
                    (pack_id, hv["node"], hv["from_role"], hv["to_role"], hv["version_no"], hv.get("open_items", ""), hv.get("deadline")),
                )
            # 写审计留痕：导入动作必须留痕（f45：审计要能看到谁做了什么）
            conn.execute(
                # 审计插入
                "INSERT INTO audit_logs(actor, role_key, action, pack_id, detail) VALUES (?,?,?,?,?)",
                # actor 为系统时角色键记 model（系统智能体）；detail 记录包号与样本来源
                (actor, "model" if actor == "system" else actor, "import", pack_id,
                 json.dumps({"sample_file": str(path.name)}, ensure_ascii=False)),
            )
            # 记入成功导入列表
            imported.append(pack_id)
    # 返回导入结果摘要
    return {"imported_packs": imported, "skipped_packs": skipped}


def audit(actor: str, role_key: str, action: str, pack_id: str = None, doc_id: int = None, version_no: str = None, detail: str = "") -> int:
    """写一条审计留痕（f45：谁查过、用哪个版本、提什么建议、谁确认）。

    入参：actor 操作人；role_key 角色键；action 动作；pack_id/doc_id/version_no 涉及对象；
          detail 详情 JSON 字符串（完整内容，非摘要）。
    出参：int，审计记录自增 id。
    失败行为：写库失败抛 sqlite3.Error，由调用方决定是否中断业务——
    为什么这么卡：审计写不进去就不能放行业务响应，否则违反 f45"不能只留最终摘要"的留痕要求。
    """
    # 打开会话写审计
    with db_session() as conn:
        # 插入审计记录
        cur = conn.execute(
            # 参数化插入
            "INSERT INTO audit_logs(actor, role_key, action, pack_id, doc_id, version_no, detail) VALUES (?,?,?,?,?,?,?)",
            # 字段对应
            (actor, role_key, action, pack_id, doc_id, version_no, detail),
        )
        # 返回审计记录 id
        return cur.lastrowid
