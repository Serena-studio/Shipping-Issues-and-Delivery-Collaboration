# -*- coding: utf-8 -*-
"""run_harness.py —— 测试 Harness 一键跑批入口。

用途：交付演示时一条命令完成"环境自检 → 全量测试 → 结果汇总"。
运行：python scripts/run_harness.py
退出码：0 = 全部通过；1 = 存在失败（用于脚本化验收判断）。
"""
# 导入 sys：读取 Python 版本并以退出码反馈结果
import sys
# 导入 subprocess：调用 pytest 子进程，隔离测试运行环境
import subprocess
# 导入 pathlib：定位项目根目录
from pathlib import Path

# 计算项目根目录：本脚本位于 scripts/ 下，父目录即项目根
ROOT = Path(__file__).resolve().parent.parent


def check_python() -> bool:
    """环境自检第一步：校验 Python 版本 ≥ 3.11（技术栈硬要求）。

    入参：无。
    出参：bool，版本达标返回 True。
    失败行为：版本不达标打印中文提示并返回 False，由 main 终止跑批——
    为什么这么卡：低版本 Python 缺少 FastAPI/Pydantic 所需语法与类型特性，带病运行必炸。
    """
    # 拆出主次版本号
    major, minor = sys.version_info[:2]
    # 达标判断：主版本 >3 或 主版本=3 且次版本 ≥11
    if (major, minor) >= (3, 11):
        # 打印达标信息
        print(f"[OK] Python {major}.{minor} 满足 3.11+ 要求")
        # 返回达标
        return True
    # 不达标打印提示
    print(f"[FAIL] Python {major}.{minor} 低于 3.11，请升级后重试")
    # 返回不达标
    return False


def check_deps() -> bool:
    """环境自检第二步：校验关键依赖可导入。

    入参：无。
    出参：bool，全部可导入返回 True。
    失败行为：任一依赖缺失打印安装命令并返回 False——
    为什么这么卡：依赖缺失时 pytest 会以收集错误方式失败，提前拦截能给用户明确修复指引。
    """
    # 需要预检的依赖清单（与 requirements.txt 对应）
    deps = ["fastapi", "uvicorn", "yaml", "jinja2", "httpx", "pytest"]
    # 逐个尝试导入
    for name in deps:
        try:
            # __import__ 动态导入
            __import__(name)
            # 单个依赖正常
            print(f"[OK] 依赖 {name} 可用")
        except ImportError:
            # 缺失时给出修复命令
            print(f"[FAIL] 缺少依赖 {name}，请执行：python -m pip install -r requirements.txt -i https://pypi.org/simple/")
            # 立即返回失败
            return False
    # 全部通过
    return True


def run_pytest() -> int:
    """执行全量测试并返回 pytest 退出码。

    入参：无。
    出参：int，pytest 进程退出码（0=全部通过）。
    失败行为：tests 目录不存在返回 1；测试失败由 pytest 退出码如实上报，不做任何吞错——
    为什么这么卡：Harness 的价值就是如实暴露问题，屏蔽失败等于自欺。
    """
    # 测试目录
    tests_dir = ROOT / "tests"
    # 目录缺失直接失败
    if not tests_dir.exists():
        # 打印提示
        print("[FAIL] 未找到 tests 目录")
        # 返回失败码
        return 1
    # 以项目根为工作目录调用 pytest（-v 显示每个用例，--tb=short 精简堆栈）
    proc = subprocess.run(
        # 命令参数列表
        [sys.executable, "-m", "pytest", "tests", "-v", "--tb=short"],
        # 工作目录设为项目根，保证相对路径（config.yaml）生效
        cwd=str(ROOT),
    )
    # 返回 pytest 退出码
    return proc.returncode


def main() -> None:
    """Harness 主流程：环境自检 → 跑全量测试 → 汇总退出。

    入参：无。
    出参：无（副作用：控制台输出跑批报告；进程退出码 0/1）。
    失败行为：任一自检不通过直接终止且退出码 1；pytest 失败也以退出码 1 结束。
    """
    # 打印跑批标题
    print("=" * 46)
    # 项目名
    print("进出口代理单证一致性智能体系统 · 测试 Harness")
    # 分隔线
    print("=" * 46)
    # 第一步：Python 版本自检
    if not check_python():
        # 不达标以非零码退出
        sys.exit(1)
    # 第二步：依赖自检
    if not check_deps():
        # 缺依赖以非零码退出
        sys.exit(1)
    # 第三步：跑全量测试
    code = run_pytest()
    # 打印汇总分隔线
    print("=" * 46)
    # 按退出码输出汇总结论
    if code == 0:
        # 全部通过
        print("[PASS] Harness 全部通过，可以交付")
    else:
        # 存在失败
        print("[FAIL] Harness 存在失败，禁止交付")
    # 以 pytest 退出码作为进程退出码，供外部脚本判断
    sys.exit(code)


# 直接运行本脚本时进入主流程
if __name__ == "__main__":
    # 调用主流程
    main()
