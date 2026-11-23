# -*- coding: utf-8 -*-
"""main.py —— FastAPI 应用入口（阶段1：骨架 + 只读查询 + 导入接口）。

启动命令：python -m uvicorn app.main:app --reload --port 8000
接口文档：http://127.0.0.1:8000/docs
"""
# 导入 FastAPI：应用主体
from fastapi import FastAPI, HTTPException, Query
# 导入静态资源与文件响应：由同一端口提供网站前端（部署沙盒只开放一个端口）
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
# 导入 contextlib：lifespan 上下文管理器（新版推荐写法，替代弃用的 on_event）
from contextlib import asynccontextmanager
# 导入 json：审计详情序列化
import json
# 导入项目模块：配置、数据库、响应结构、导入器
from app.config import load_config, PROJECT_ROOT
from app.db import init_db, db_session
from app.response import ok, err
from app.importer import audit

# 网站静态目录：与 API 共用同一端口，避免部署时多端口依赖
WEB_ROOT = PROJECT_ROOT / "web"

# lifespan 生命周期：替代已弃用的 on_event 写法（官方推荐，无弃用警告）
@asynccontextmanager
async def lifespan(application: FastAPI):
    """应用生命周期钩子：启动时建表，关闭时无额外清理。

    入参：application —— FastAPI 应用实例（由框架传入）。
    出参：yield None（生命周期信号）。
    失败行为：config.yaml 缺失或建表失败时抛异常，uvicorn 启动直接失败——
    为什么这么卡：配置与表结构是所有红线的前置条件，带病启动等于绕过红线。
    """
    # 先强制加载一次配置：配置文件坏了立刻暴露，而不是第一个请求才炸
    load_config(force_reload=True)
    # 初始化数据库表结构（幂等建表）
    init_db()
    # 启动完成，进入服务状态
    yield

# 创建 FastAPI 实例；标题与描述里带合成演练声明（数据红线 7：输出固定声明）
app = FastAPI(
    # 服务标题
    title="进出口代理单证一致性智能体系统",
    # 服务描述：固定携带演练声明
    description=load_config()["disclaimer"],
    # API 版本
    version="0.1.0-stage1",
    # 挂载生命周期
    lifespan=lifespan,
)

# 静态资源挂载：/assets/style.css 与 /assets/app.js 由本服务直接返回
app.mount("/assets", StaticFiles(directory=WEB_ROOT / "assets"), name="assets")


# ============ 网站首页（与 API 同端口） ============
@app.get("/", include_in_schema=False)
def index():
    """返回交互演示网站首页。

    入参：无。
    出参：web/index.html 文件响应。
    失败行为：页面文件缺失时抛 404——页面与代码同仓交付，缺失属部署问题，不做静默降级。
    """
    return FileResponse(WEB_ROOT / "index.html")


# 权限辅助函数：按角色键查权限表
def _role_perms(role_key: str) -> dict:
    """按角色键返回该角色的权限字典。

    入参：role_key —— config.yaml roles 段中的角色键。
    出参：dict，该角色权限项；角色不存在时返回全 False 的最小权限集。
    失败行为：无（未知角色按最小权限处理，这是安全默认值设计——
    为什么这么卡：未登记的角色绝不能默认拥有权限，防止越权访问 f41）。
    """
    # 读取角色配置段
    roles = load_config()["roles"]
    # 已登记角色返回其权限
    if role_key in roles:
        # 返回权限字典副本
        return dict(roles[role_key])
    # 未知角色给最小权限：什么都做不了
    return {"can_query": False, "can_submit_change": False, "can_confirm": False}


# ============ 接口1：健康检查 ============
@app.get("/api/health")
def health() -> dict:
    """健康检查接口。

    入参：无。
    出参：统一结构 {"ok": True, "data": {...状态信息...}, "error": None}。
    失败行为：配置缺失由 startup 拦截，本接口正常返回即代表服务与配置可用。
    """
    # 读配置取声明文案
    cfg = load_config()
    # 返回统一成功结构，data 里带版本与声明
    return ok({"status": "running", "disclaimer": cfg["disclaimer"]})


# ============ 接口2：导入合成样本（幂等） ============
@app.post("/api/import")
def import_samples_api(actor: str = Query("system", description="操作人")) -> dict:
    """导入合成样本数据（只读导入器，幂等可重复调用）。

    入参：actor —— 操作人（查询参数）。
    出参：统一结构，data 为 {"imported_packs": [...], "skipped_packs": [...]}。
    失败行为：样本结构非法抛异常 → 转 500 INTERNAL_ERROR；已导入的包会跳过不报错。
    """
    # 延迟导入导入器：避免循环依赖
    from app.importer import import_samples
    try:
        # 执行导入
        result = import_samples(actor=actor)
        # 返回统一成功结构
        return ok(result)
    except (ValueError, KeyError) as e:
        # 样本结构问题：返回业务级错误，不暴露堆栈
        return err("SAMPLE_INVALID", f"样本数据非法：{e}")


# ============ 接口3：查询单证包（只读） ============
@app.get("/api/packs/{pack_id}")
def query_pack(
    # 路径参数：单证包编号
    pack_id: str,
    # 查询参数：操作人与角色键（阶段1 简化为显式传参；阶段3 换成会话鉴权）
    actor: str = Query(..., description="操作人姓名"),
    role_key: str = Query(..., description="角色键，如 frontline/owner/auditor/coordinator"),
) -> dict:
    """查询单证包全部单证、版本与交接记录（只读接口）。

    入参：pack_id 包号；actor 操作人；role_key 角色键。
    出参：统一结构，data 含 disclaimer/单证列表(含版本)/交接列表。
    失败行为：角色无查询权限 → FORBIDDEN；包不存在 → NOT_FOUND；
    每次成功查询都写审计（f45：谁查过必须留痕，这是查询即审计的硬要求）。
    """
    # 先做权限校验：为什么这么卡——f41 要求按授权范围访问，越权访问为零，
    # 任何查询必须在取数据之前先验权限，而不是查完再筛
    perms = _role_perms(role_key)
    # 无查询权限直接拒绝
    if not perms.get("can_query"):
        # 返回统一禁止访问结构
        return err("FORBIDDEN", f"角色 {role_key} 无查询权限")
    # 打开只读会话查数据
    with db_session() as conn:
        # 查该包全部单证
        docs = conn.execute(
            # 按包号查单证
            "SELECT * FROM documents WHERE pack_id = ? ORDER BY id", (pack_id,)
        ).fetchall()
        # 包不存在返回业务级 NOT_FOUND
        if not docs:
            # 不写审计的失败查询不违反 f45（f45 针对查到数据的访问），但这里仍留痕便于排查
            audit(actor, role_key, "query", pack_id=pack_id, detail=json.dumps({"result": "not_found"}, ensure_ascii=False))
            # 返回未找到
            return err("NOT_FOUND", f"单证包 {pack_id} 不存在")
        # 组装单证+版本结果
        doc_list = []
        # 逐单证补版本
        for d in docs:
            # 查该单证全部版本（双条件字段随行返回）
            vers = conn.execute(
                # 按单证查版本
                "SELECT * FROM versions WHERE doc_id = ? ORDER BY id", (d["id"],)
            ).fetchall()
            # 组装单证条目：payload 解析回 JSON 对象，来源文件原样返回（f42 关联来源）
            doc_list.append({
                # 单证基础信息
                "id": d["id"], "doc_type": d["doc_type"], "doc_no": d["doc_no"],
                # 原始字段（白名单六项）
                "payload": json.loads(d["payload"]),
                # 来源文件标注
                "source_file": d["source_file"],
                # 版本列表（含有效期/确认状态双条件与双时间戳）
                "versions": [dict(v) for v in vers],
            })
        # 查该包交接记录（f20/f23 字段全量返回）
        handovers = conn.execute(
            # 按包号查交接
            "SELECT * FROM handovers WHERE pack_id = ? ORDER BY id", (pack_id,)
        ).fetchall()
        # 写审计留痕：记录谁查过这个包、查到多少条（f45 硬要求，不能只留摘要）
        audit(actor, role_key, "query", pack_id=pack_id,
              detail=json.dumps({"docs": len(doc_list), "handovers": len(handovers)}, ensure_ascii=False))
        # 返回统一成功结构；data 里固定带演练声明（数据红线 7）
        return ok({
            # 固定声明
            "disclaimer": load_config()["disclaimer"],
            # 包号
            "pack_id": pack_id,
            # 单证与版本
            "documents": doc_list,
            # 交接记录
            "handovers": [dict(h) for h in handovers],
        })


# ============ 接口4：概览统计（网站首页用，只返回计数不返回明细） ============
@app.get("/api/overview")
def overview() -> dict:
    """返回全库聚合计数，供网站统计条展示。

    入参：无。
    出参：统一结构，data 为各表计数 + 固定演练声明。
    失败行为：数据库异常由框架转 500；本接口只返回计数，不泄露任何单证明细。
    """
    # 表名列表全部硬编码，不接受外部输入拼 SQL（防注入）
    tables = (
        ("documents", "documents"), ("versions", "versions"),
        ("handovers", "handovers"), ("audit_logs", "audit_logs"),
        ("manual_queue", "manual_queue"),
    )
    counts = {}
    # 单连接内完成所有计数，避免多次开关连接
    with db_session() as conn:
        # 包数按 pack_id 去重，而不是单证条数
        counts["packs"] = conn.execute(
            "SELECT COUNT(DISTINCT pack_id) AS n FROM documents"
        ).fetchone()["n"]
        # 逐表计数
        for key, table in tables:
            counts[key] = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
    # 数据红线 7：输出固定携带演练声明
    counts["disclaimer"] = load_config()["disclaimer"]
    # 返回统一成功结构
    return ok(counts)


# ============ 接口5：角色权限配置（网站权限矩阵用，只读） ============
@app.get("/api/roles")
def roles() -> dict:
    """返回 config.yaml 中的角色权限矩阵，供网页直接渲染。

    入参：无。
    出参：统一结构，data.roles 为角色列表（键 + 权限项）。
    失败行为：配置为非法结构时由启动期校验拦截；本接口只暴露配置中已公开的权限口径。
    """
    # 读取配置段：角色键 -> 权限字典
    cfg = load_config()
    # 组装列表，补上角色键本身
    result = []
    for key, value in cfg["roles"].items():
        # 复制权限项，避免修改缓存
        item = dict(value)
        # 补角色键
        item["key"] = key
        # 加入结果
        result.append(item)
    # 返回统一成功结构
    return ok({"roles": result, "disclaimer": cfg["disclaimer"]})


# ============ 接口6：审计检索（仅 auditor 角色，f45） ============
@app.get("/api/audit")
def query_audit(
    actor: str = Query(..., description="操作人"),
    role_key: str = Query(..., description="角色键"),
    limit: int = Query(20, ge=1, le=200, description="最多返回条数（1-200）"),
) -> dict:
    """按角色权限检索审计记录（f45：留痕可被授权人查看，且查询本身留痕）。

    入参：actor 操作人；role_key 角色键；limit 返回条数上限。
    出参：统一结构，data 含 total 与 records（detail 解析为 JSON 对象）。
    失败行为：无 can_view_audit 权限返回 FORBIDDEN，并写一条拒绝留痕——
    为什么这么卡：越权尝试同样是可追溯事件，不能查不到也不记录。
    """
    # 先做权限校验：与查询接口同一顺序（f41 先验权限再取数据）
    perms = _role_perms(role_key)
    # 无审计查看权限直接拒绝
    if not perms.get("can_view_audit"):
        # 拒绝事件也留痕
        audit(actor, role_key, "audit_view",
              detail=json.dumps({"result": "forbidden", "limit": limit}, ensure_ascii=False))
        # 返回统一禁止访问结构
        return err("FORBIDDEN", f"角色 {role_key} 无审计查看权限")
    # f45：查询即留痕——在返回结果前先写审计
    audit(actor, role_key, "audit_view",
          detail=json.dumps({"result": "ok", "limit": limit}, ensure_ascii=False))
    # 打开只读会话取审计记录
    with db_session() as conn:
        # 总条数（含本次留痕）
        total = conn.execute("SELECT COUNT(*) AS n FROM audit_logs").fetchone()["n"]
        # 按 id 倒序取最近若干条
        rows = conn.execute(
            "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    # 组装记录：detail 从 JSON 字符串还原为对象，便于前端展示完整留痕
    records = []
    for row in rows:
        # 转普通字典
        item = dict(row)
        # 原始详情文本
        detail = item.get("detail") or ""
        try:
            # 合法 JSON 直接解析
            item["detail"] = json.loads(detail) if detail else {}
        except (ValueError, TypeError):
            # 非法 JSON 原文保留，不吞数据
            item["detail"] = {"raw": detail}
        # 收集
        records.append(item)
    # 返回统一成功结构；data 固定带演练声明
    return ok({
        "total": total, "records": records,
        "disclaimer": load_config()["disclaimer"],
    })
