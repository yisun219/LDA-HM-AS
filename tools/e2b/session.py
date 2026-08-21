#!/usr/bin/env python3
"""在沙箱里跑完整整一轮 agent 会话:卡进箱 → 箱内干活 → 取回 → 销毁。

它是一个引擎适配器,遵守流程的引擎协议(提示词作为最后一个参数),可直接交给驱动器:

    LDA_EXEC=sandbox ./lda run <卡目录>          # 默认形态
    ENGINE_CMD="python3 tools/e2b/session.py --card <卡目录>" ./lda run <卡目录>

这样执行端全部在 E2B 里:编译、测试、agent 会话本身都在箱内,宿主只留卡的持久副本。
凭据全部从环境读,不进仓库也不进模板。
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from e2b_common import configure_shared_gateway, default_template, require_env  # noqa: E402

# 卡落在 /tmp 下:根目录属 root,而沙箱以普通用户身份运行;箱本身是一次性的,
# 持久副本始终在宿主上,箱内路径只是这一轮的工作面
BOX_CARD = "/tmp/lda-card"
UP, DOWN = "/tmp/card.tgz", "/tmp/card.out.tgz"
PROMPT_FILE = "/tmp/lda-prompt"
# 跟着卡进箱的凭据与网络设置(只从环境读)
PASS_ENV = (
    "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL",
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "LDA_GIT_NAME", "LDA_GIT_EMAIL",
    "https_proxy", "http_proxy", "HTTPS_PROXY", "HTTP_PROXY", "no_proxy", "NO_PROXY",
)
EXCLUDE = {".lda-run"}  # 驱动器运行区属于宿主,不进箱


def pack(card: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in sorted(os.listdir(card)):
            if name in EXCLUDE or name.startswith("._"):
                continue
            tar.add(os.path.join(card, name), arcname=name)
    return buf.getvalue()


def unpack(card: str, blob: bytes) -> None:
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        tar.extractall(card)


def box_script(engine: str, timeout_s: int) -> str:
    """箱内一轮:准备 git 身份 → 后台跑引擎 → 心跳保活 → 回吐输出与退出码。

    网关会掐断静默超过约 30 秒的命令流,所以长会话必须周期性输出(心跳只防掐流,
    不等于进度——引擎自己的输出在结束时一次性回吐)。
    """
    return (
        f'set -u; CARD="{BOX_CARD}"; mkdir -p "$CARD"; cd "$CARD"; '
        'git config --global --add safe.directory "$CARD" 2>/dev/null; '
        'git config --global user.name "${LDA_GIT_NAME:-LDA agent}"; '
        'git config --global user.email "${LDA_GIT_EMAIL:-agent@lda.local}"; '
        'git config --global init.defaultBranch main; '
        '[ -d "$CARD/.git" ] || { git init -q "$CARD" && git add -A && git commit -qm 开卡 >/dev/null 2>&1; }; '
        f'( {engine} "$(cat {PROMPT_FILE})" > /tmp/engine.out 2>&1; echo $? > /tmp/engine.rc ) & '
        'P=$!; '
        'while kill -0 $P 2>/dev/null; do echo "[箱内运行中 $(date +%H:%M:%S)]"; sleep 10; done; '
        'wait $P; cat /tmp/engine.out; exit $(cat /tmp/engine.rc 2>/dev/null || echo 1)'
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", required=True, help="卡目录(宿主上的持久副本)")
    ap.add_argument("--template", default=None)
    ap.add_argument("--timeout", type=int, default=int(os.getenv("LDA_BOX_TIMEOUT", "5400")))
    ap.add_argument("prompt", nargs="+", help="提示词(最后一个参数)")
    a = ap.parse_args()
    card = os.path.abspath(a.card)
    prompt = a.prompt[-1]

    require_env("E2B_API_KEY")
    configure_shared_gateway()
    from e2b import Sandbox

    template = a.template or default_template()
    envs = {k: os.environ[k] for k in PASS_ENV if os.environ.get(k)}
    # 传 envs 时网关不与镜像环境合并,基础变量要自己补上
    envs.setdefault("HOME", "/home/user")
    envs.setdefault("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
    engine = os.getenv(
        "LDA_BOX_ENGINE", "claude -p --model opus --effort max --dangerously-skip-permissions"
    )

    t0 = time.time()
    sb = Sandbox.create(template=template, timeout=a.timeout, envs=envs)
    print(f"[sandbox {sb.sandbox_id} template={template}]", flush=True)
    rc = 1
    try:
        sb.files.write(UP, pack(card))
        sb.files.write(PROMPT_FILE, prompt)
        r0 = sb.commands.run(f'mkdir -p "{BOX_CARD}" && tar xzf {UP} -C "{BOX_CARD}"', timeout=300)
        if r0.exit_code != 0:
            raise RuntimeError(f"卡进箱失败: {r0.stderr[:300]}")
        r = sb.commands.run(box_script(engine, a.timeout), timeout=a.timeout)
        # 引擎输出原样回宿主:驱动器靠它识别限额与网络中断
        print(r.stdout, flush=True)
        if r.stderr:
            print(r.stderr, file=sys.stderr, flush=True)
        rc = r.exit_code
    except Exception as exc:  # 取证先于销毁:失败也要把箱内的卡取回来
        print(f"[箱内会话异常] {exc}", file=sys.stderr, flush=True)
    finally:
        try:
            rt = sb.commands.run(f'tar czf {DOWN} -C "{BOX_CARD}" .', timeout=300)
            if rt.exit_code == 0:
                unpack(card, sb.files.read(DOWN, format="bytes"))
                print(f"[卡已取回 {time.time() - t0:.0f}s sandbox={sb.sandbox_id}]", flush=True)
            else:
                print(f"[取回失败] {rt.stderr[:300]}", file=sys.stderr, flush=True)
        except Exception as exc:
            print(f"[取回失败] {exc}", file=sys.stderr, flush=True)
        finally:
            try:
                sb.kill()
            except Exception:
                pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
