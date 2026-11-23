# -*- coding: utf-8 -*-
"""test_stage1.py —— 阶段1 验证脚本（可直接跑通）。

运行命令：python -m pytest tests/test_stage1.py -v
覆盖点：临时库隔离 → 启动事件建表 → 导入合成样本 → 只读查询 → 统一响应结构 → 审计留痕落库。
"""
# 导入 os：设置环境变量隔离测试库
import os
# 导入 tempfile：创建临时目录存放测试数据库
import tempfile
# 导入 json：解析响应
import json
# 导入 pytest：测试框架
import pytest
# 导入 TestClient：进程内调用 FastAPI，无需真正起服务
from fastapi.testclient import TestClient
# 导入项目模块：配置路径与数据库会话
from app.config import PROJECT_ROOT
from app.db import db_session

# 模块级夹具：在所有测试前建立一次客户端（建表+导样本只做一次，节省时间）
@pytest.fixture(scope="module")
def client():
    """构建阶段1 测试客户端：临时库隔离 + 启动事件 + 预导入样本。

    入参：无。
    出参：yield 配置好的 TestClient。
    失败行为：环境异常抛出后所有测试跳过失败，能快速定位是环境问题而非逻辑问题。
    """
    # 建临时目录：测试库放这里，跑完自动清理，不污染正式 data/agent.db
    tmp = tempfile.mkdtemp()
    # 设置数据库路径覆盖环境变量：config.get_db_path 会优先读它
    os.environ["AGENT_DB_PATH"] = os.path.join(tmp, "test.db")
    # 延迟导入 main：确保环境变量先生效（main 的 startup 会调 get_db_path）
    from app.main import app
    # 用 with 管理客户端生命周期（触发 startup 建表）
    with TestClient(app) as c:
        # 调导入接口预置三票合成样本
        resp = c.post("/api/import", params={"actor": "tester"})
        # 断言导入成功
        assert resp.json()["ok"] is True, f"样本导入失败：{resp.json()}"
        # yield 客户端给各测试用
        yield c
    # 清理环境变量，避免影响同进程其他测试
    os.environ.pop("AGENT_DB_PATH", None)


def test_health(client):
    """用例1：健康检查返回统一成功结构且带演练声明。"""
    # 调健康检查接口
    r = client.get("/api/health").json()
    # 断言 ok 为真
    assert r["ok"] is True
    # 断言 error 为空
    assert r["error"] is None
    # 断言 data 中带固定演练声明（数据红线 7）
    assert "合成演练" in r["data"]["disclaimer"]


def test_import_idempotent(client):
    """用例2：导入接口幂等——重复导入时三包全部跳过。"""
    # 再次调用导入接口
    r = client.post("/api/import", params={"actor": "tester"}).json()
    # 断言无新增
    assert r["data"]["imported_packs"] == []
    # 断言三包都被跳过
    assert len(r["data"]["skipped_packs"]) == 3


def test_query_pack_structure(client):
    """用例3：查询返回统一结构，单证带版本双条件与来源标注（f24/f42）。"""
    # 以一线专员身份查询 P2026-002（内置 f11 模拟异常的包）
    r = client.get("/api/packs/P2026-002", params={"actor": "林亦舟", "role_key": "frontline"}).json()
    # 断言成功
    assert r["ok"] is True
    # 断言三份单证
    assert len(r["data"]["documents"]) == 3
    # 断言每份单证带来源文件（f42：结果关联来源）
    assert all(d["source_file"] for d in r["data"]["documents"])
    # 找到装箱单
    pl = next(d for d in r["data"]["documents"] if d["doc_type"] == "packing_list")
    # 断言装箱单 v2 是"有效但未确认"状态（f11 模拟异常种子已入库）
    v2 = next(v for v in pl["versions"] if v["version_no"] == "v2")
    # 断言确认状态为 pending
    assert v2["confirm_state"] == "pending"
    # 断言业务发生时间与系统接收时间两个字段都存在（f34 双时间戳）
    assert v2["business_time"] and v2["system_time"]


def test_query_forbidden_for_unknown_role(client):
    """用例4：未登记角色查询被拒（f41：越权访问为零）。"""
    # 用不存在的角色键查询
    r = client.get("/api/packs/P2026-001", params={"actor": "路人", "role_key": "hacker"}).json()
    # 断言失败
    assert r["ok"] is False
    # 断言错误码为 FORBIDDEN
    assert r["error"]["code"] == "FORBIDDEN"


def test_query_not_found(client):
    """用例5：不存在的包返回 NOT_FOUND 业务错误而非 500。"""
    # 查询不存在的包
    r = client.get("/api/packs/NO-SUCH-PACK", params={"actor": "顾明岚", "role_key": "owner"}).json()
    # 断言失败
    assert r["ok"] is False
    # 断言错误码
    assert r["error"]["code"] == "NOT_FOUND"


def test_audit_trail_written(client):
    """用例6：查询动作已落审计表且 detail 非摘要（f45：谁查过必须留痕）。"""
    # 以一线身份再查一次 P2026-003
    client.get("/api/packs/P2026-003", params={"actor": "林亦舟", "role_key": "frontline"})
    # 直连测试库查审计表
    with db_session() as conn:
        # 查询林亦舟的 query 类审计记录
        rows = conn.execute(
            # 按操作人与动作过滤
            "SELECT * FROM audit_logs WHERE actor = '林亦舟' AND action = 'query'"
        ).fetchall()
        # 断言有留痕
        assert len(rows) >= 1
        # 断言 detail 是完整 JSON（含查到条数），不是只留一句摘要文本
        detail = json.loads(rows[-1]["detail"])
        # 断言 detail 里记录了单证条数
        assert "docs" in detail
