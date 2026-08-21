#!/usr/bin/env python3
"""构建 lda-base 模板:LDA 的标准执行环境。

    python3 tools/e2b/template/build.py [模板名]

凭据只从环境读(E2B_API_KEY / E2B_API_URL / E2B_SANDBOX_URL),不进仓库。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # tools/e2b

from e2b_common import configure_shared_gateway, require_env  # noqa: E402


def patch_build_request() -> None:
    """共享网关的建模板接口要 name 字段,官方 SDK 发的是 alias。补上这一处差异。"""
    import httpx
    from types import SimpleNamespace
    from e2b.template_sync import build_api, main as tmain

    def request_build(client, name: str, cpu_count: int, memory_mb: int):
        base = os.environ["E2B_API_URL"].rstrip("/")
        hdr = {"X-API-KEY": os.environ["E2B_API_KEY"]}
        # 重建同名模板:网关的建模板接口是"新建并绑名",重名不给重绑,
        # 所以先摘掉旧的那一张(是我们自己的模板;正在跑的沙箱不受影响)。
        old = httpx.get(base + "/templates", headers=hdr, timeout=60).json()
        old = old if isinstance(old, list) else old.get("templates", [])
        for t_ in old:
            if name in (t_.get("names") or []):
                httpx.delete(f"{base}/templates/{t_['templateID']}", headers=hdr, timeout=60)
                print(f"替换同名旧模板 {t_['templateID']}")
        res = httpx.post(
            os.environ["E2B_API_URL"].rstrip("/") + "/v3/templates",
            headers={"X-API-KEY": os.environ["E2B_API_KEY"]},
            json={"name": name, "cpuCount": cpu_count, "memoryMB": memory_mb},
            timeout=60,
        )
        if res.status_code >= 300:
            raise SystemExit(f"建模板失败 {res.status_code}: {res.text[:300]}")
        d = res.json()
        return SimpleNamespace(template_id=d["templateID"], build_id=d["buildID"])

    build_api.request_build = request_build
    tmain.request_build = request_build


def sorted_skills() -> list:
    d = os.path.join(HERE, "skills")
    return sorted(f for f in os.listdir(d) if f.endswith(".md")) if os.path.isdir(d) else []


def harness_count() -> int:
    p = os.path.join(HERE, "harness.txt")
    if not os.path.exists(p):
        return 0
    return len([l for l in open(p) if l.strip() and not l.strip().startswith("#")])


def _write_step(path: str, content: str) -> str:
    """把一个文件内联进构建步骤(base64,避免任何引号与换行的坑)。"""
    import base64

    b64 = base64.b64encode(content.encode()).decode()
    return f"RUN echo '{b64}' | base64 -d > {path}\n"


def compose_dockerfile() -> str:
    """基础配方 + 内联技能包 + harness 清单与安装 —— 本网关的构建接口不支持 COPY。"""
    df = open(os.path.join(HERE, "lda-base.Dockerfile")).read()
    df += "RUN mkdir -p /opt/lda/skills /opt/lda/harness\n"
    for f in sorted_skills():
        df += _write_step(f"/opt/lda/skills/{f}", open(os.path.join(HERE, "skills", f)).read())
    # 沙箱默认用户是 user(HOME=/home/user),root 也可能用到:两个家目录都链上
    df += (
        "RUN for H in /root /home/user; do mkdir -p \"$H/.claude\" && "
        "ln -sfn /opt/lda/skills \"$H/.claude/skills\"; done; "
        "chown -R user:user /home/user/.claude 2>/dev/null || true\n"
    )
    hp = os.path.join(HERE, "harness.txt")
    if os.path.exists(hp):
        df += _write_step("/opt/lda/harness.txt", open(hp).read())
        df += (
            "RUN while IFS= read -r line; do case \"$line\" in \"\"|\\#*) continue ;; "
            "npm:*) npm install -g \"${line#npm:}\" || echo \"跳过 $line\" ;; "
            "pip:*) pip3 install --break-system-packages \"${line#pip:}\" || echo \"跳过 $line\" ;; "
            "git:*) git clone --depth 1 \"${line#git:}\" \"/opt/lda/harness/$(basename \"${line#git:}\" .git)\" || echo \"跳过 $line\" ;; "
            "esac; done < /opt/lda/harness.txt\n"
        )
    # 卡的落脚点在沙箱用户家目录(见 session.py);这里只把公共暂存备好
    df += "RUN mkdir -p /work && chmod 1777 /work\nWORKDIR /work\n"
    return df


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "lda-base"
    require_env("E2B_API_KEY")
    configure_shared_gateway()
    patch_build_request()

    from e2b import Template

    dockerfile = compose_dockerfile()
    print(f"构建模板 {name}(技能 {len(sorted_skills())} 个,harness 清单 {harness_count()} 条)")
    tmpl = Template().from_dockerfile(dockerfile)
    Template.build(
        tmpl,
        name,
        cpu_count=int(os.getenv("LDA_TEMPLATE_CPU", "8")),
        memory_mb=int(os.getenv("LDA_TEMPLATE_MEM", "16384")),
        on_build_logs=lambda m: print(str(m).rstrip()),
    )
    print(f"完成:{name}  用法 export E2B_TEMPLATE={name}")


if __name__ == "__main__":
    main()
