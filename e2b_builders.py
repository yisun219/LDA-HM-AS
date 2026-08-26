import base64
import shlex
from pathlib import Path

from e2b import Template


CODEX_CLI_VERSION = "0.149.1"
INTEL_SKILLS_COMMIT = "e9d0b6410fb1ad7a50fb81e0868fd23ae886882c"
UV_VERSION = "0.8.13"
PYTHON_VERSION = "3.12.12"
PYTHON_SOURCE_SHA256 = "fb85a13414b028c49ba18bbd523c2d055a30b56b18b92ce454ea2c51edc656c4"
ROOT = Path(__file__).resolve().parent


PYTHON_BUILD_PACKAGES = (
    "build-essential curl ca-certificates xz-utils libssl-dev zlib1g-dev "
    "libbz2-dev libreadline-dev libsqlite3-dev libffi-dev liblzma-dev "
    "libncursesw5-dev libgdbm-dev libnss3-dev uuid-dev"
)


def python_runtime_command() -> str:
    return (
        f"curl -fsSL https://www.python.org/ftp/python/{PYTHON_VERSION}/Python-{PYTHON_VERSION}.tar.xz -o /tmp/python.tar.xz && "
        f"printf '%s  %s\\n' {PYTHON_SOURCE_SHA256} /tmp/python.tar.xz | sha256sum -c - && "
        "mkdir -p /tmp/python-src && tar -xJf /tmp/python.tar.xz -C /tmp/python-src --strip-components=1 && "
        "cd /tmp/python-src && ./configure --prefix=/opt/python3.12 --with-ensurepip=install && "
        "make -j$(nproc) && make install && "
        "/opt/python3.12/bin/python3.12 -m venv /opt/lda/venv && "
        "rm -rf /tmp/python-src /tmp/python.tar.xz"
    )


def embed_file(builder, source: Path, destination: Path):
    encoded = base64.b64encode(source.read_bytes()).decode("ascii")
    command = (
        f"mkdir -p {shlex.quote(str(destination.parent))} && "
        f"printf %s {shlex.quote(encoded)} | base64 -d > {shlex.quote(str(destination))}"
    )
    if source.stat().st_mode & 0o111:
        command += f" && chmod +x {shlex.quote(str(destination))}"
    return builder.run_cmd(command)


def embed_path(builder, relative: str, destination: str):
    source = ROOT / relative
    target = Path(destination)
    if source.is_file():
        return embed_file(builder, source, target)
    for item in sorted(source.rglob("*")):
        if item.is_file() and "__pycache__" not in item.parts and not item.name.endswith((".pyc", ".DS_Store")):
            builder = embed_file(builder, item, target / item.relative_to(source))
    return builder


def embed_runtime(builder):
    builder = embed_path(builder, "pyproject.toml", "/opt/lda/runtime/pyproject.toml")
    for directory in ("src", "configs", "schemas", "prompts"):
        builder = embed_path(builder, directory, f"/opt/lda/runtime/{directory}")
    return builder


def controller_template():
    builder = (
        Template().from_ubuntu_image("26.04").set_user("root")
        .run_cmd(f"apt-get update && apt-get install -y --no-install-recommends {PYTHON_BUILD_PACKAGES} git jq sqlite3 && rm -rf /var/lib/apt/lists/*")
        .run_cmd(python_runtime_command())
    )
    builder = embed_runtime(builder)
    return (
        builder.run_cmd("/opt/lda/venv/bin/pip install --no-cache-dir /opt/lda/runtime && ln -sf /opt/lda/venv/bin/lda /usr/local/bin/lda && ln -sf /opt/lda/venv/bin/lda-tool-gateway /usr/local/bin/lda-tool-gateway")
        .run_cmd("useradd --create-home --shell /bin/bash lda || true; mkdir -p /opt/lda/state /opt/lda/artifacts; chown -R lda:lda /opt/lda")
        .set_workdir("/opt/lda")
        .set_envs({"PATH": "/opt/lda/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"})
        .set_user("lda")
    )


def agent_template():
    builder = (
        Template().from_ubuntu_image("26.04").set_user("root")
        .run_cmd(f"apt-get update && apt-get install -y --no-install-recommends {PYTHON_BUILD_PACKAGES} nodejs npm git jq && rm -rf /var/lib/apt/lists/*")
        .run_cmd(python_runtime_command())
        .run_cmd(f"npm install -g @openai/codex@{CODEX_CLI_VERSION}")
    )
    builder = embed_runtime(builder)
    builder = embed_path(builder, "sandbox/lda-base/skills", "/opt/lda/skills")
    return (
        builder.run_cmd("/opt/lda/venv/bin/pip install --no-cache-dir /opt/lda/runtime && ln -sf /opt/lda/venv/bin/lda-mcp /usr/local/bin/lda-mcp")
        .run_cmd("useradd --create-home --shell /bin/bash agent || true; mkdir -p /opt/lda/work /opt/lda/agent-state /opt/lda/skills; " f"printf '%s\\n' {INTEL_SKILLS_COMMIT} >/opt/lda/skills/INTEL_SKILLS_COMMIT; chown -R agent:agent /opt/lda")
        .set_workdir("/opt/lda/work")
        .set_envs({"PATH": "/opt/lda/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"})
        .set_user("agent")
    )


def base_template():
    builder = (
        Template().from_ubuntu_image("26.04").set_user("root")
        .run_cmd(
            "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "
            "build-essential gcc g++ clang lld cmake ninja-build meson autoconf automake libtool "
            "dpkg-dev sbuild debhelper devscripts quilt fakeroot pkg-config git curl jq ca-certificates "
            "linux-tools-generic strace valgrind bpftrace sysstat numactl abi-dumper abi-compliance-checker "
            "abigail-tools binutils elfutils dwarves python3 python3-dev python3-pip python3-venv python3-cffi "
            f"rustc cargo file time procps xz-utils zstd apt-utils sudo gperf {PYTHON_BUILD_PACKAGES} && rm -rf /var/lib/apt/lists/*"
        )
        .run_cmd(python_runtime_command())
        .run_cmd("/opt/lda/venv/bin/pip install --no-cache-dir cffi==1.17.1")
    )
    builder = embed_path(builder, "sandbox/lda-base/skills", "/opt/lda/skills")
    builder = embed_path(builder, "sandbox/lda-base/checks", "/opt/lda/harness/checks")
    builder = embed_path(builder, "fixtures", "/opt/lda/fixtures")
    return (
        builder.run_cmd("chmod +x /opt/lda/harness/checks/*.sh /opt/lda/harness/checks/*.py; " f"printf '%s\\n' {INTEL_SKILLS_COMMIT} >/opt/lda/skills/INTEL_SKILLS_COMMIT; " "useradd --create-home --shell /bin/bash worker || true; printf '%s\\n' 'worker ALL=(ALL) NOPASSWD:ALL' >/etc/sudoers.d/lda-worker; chmod 0440 /etc/sudoers.d/lda-worker; mkdir -p /opt/lda/work /opt/lda/input /opt/lda/output /opt/lda/baseline; chown -R worker:worker /opt/lda/work /opt/lda/input /opt/lda/output")
        .set_workdir("/opt/lda/work")
        .set_envs({"PATH": "/opt/lda/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"})
        .set_user("worker")
    )


def judge_template(base_alias: str):
    builder = (
        Template().from_template(base_alias).set_user("root")
        .run_cmd("sudo mkdir -p /opt/lda/runtime /opt/lda/runtime/src && sudo chown -R worker:worker /opt/lda/runtime")
    )
    builder = embed_path(builder, "src", "/opt/lda/runtime/src")
    builder = embed_path(builder, "pyproject.toml", "/opt/lda/runtime/pyproject.toml")
    return (
        builder.run_cmd("sudo /opt/lda/venv/bin/pip install --no-cache-dir /opt/lda/runtime")
        .run_cmd("sudo mkdir -p /opt/lda/judge /opt/lda/input /opt/lda/output; sudo chown -R root:root /opt/lda/judge /opt/lda/baseline; sudo chmod -R a-w /opt/lda/judge /opt/lda/baseline; sudo chown -R worker:worker /opt/lda/input /opt/lda/output")
        .set_workdir("/opt/lda/work").set_user("worker")
    )


def e2e_template():
    builder = (
        Template().from_ubuntu_image("26.04").set_user("root")
        .run_cmd(
            f"apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "
            f"nodejs npm nginx apache2-utils xvfb xauth dbus-x11 fonts-dejavu-core "
            f"jq dpkg-dev apt-utils {PYTHON_BUILD_PACKAGES} "
            "libglib2.0-0t64 libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64 "
            "libgtk-3-0t64 libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 libasound2t64 libcairo2 "
            "libcups2t64 libdbus-1-3 libdrm2 libgbm1 libnspr4 libnss3 libpango-1.0-0 "
            "libx11-6 libx11-xcb1 libxcb1 libxext6 libxrandr2 libxshmfence1 && rm -rf /var/lib/apt/lists/*"
        )
        .run_cmd(python_runtime_command())
        .run_cmd("mkdir -p /opt/playwright /opt/lda && chmod 0755 /opt/playwright /opt/lda")
        .set_envs({"PLAYWRIGHT_BROWSERS_PATH": "/opt/playwright", "PLAYWRIGHT_HOST_PLATFORM_OVERRIDE": "ubuntu24.04-x64"})
        .run_cmd(
            "npm install -g playwright@1.55.0 && "
            "PLAYWRIGHT_BROWSERS_PATH=/opt/playwright PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 "
            "npx playwright install chromium && "
            "browser=$(find /opt/playwright -type f -path '*/chrome-linux*/chrome' | head -1) && "
            "test -n \"$browser\" && ln -sf \"$browser\" /usr/local/bin/chromium"
        )
    )
    builder = embed_path(builder, "fixtures", "/opt/lda/fixtures")
    return (
        builder.run_cmd("useradd --create-home --shell /bin/bash e2e || true; printf '%s\\n' 'e2e ALL=(ALL) NOPASSWD:/usr/bin/dpkg' >/etc/sudoers.d/lda-e2e; chmod 0440 /etc/sudoers.d/lda-e2e; mkdir -p /opt/lda/work /opt/lda/packages/candidate /opt/lda/packages/baseline /opt/lda/results; chown -R e2e:e2e /opt/lda")
        .set_workdir("/opt/lda/work")
        .set_envs({"PATH": "/opt/lda/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "PLAYWRIGHT_BROWSERS_PATH": "/opt/playwright", "PLAYWRIGHT_HOST_PLATFORM_OVERRIDE": "ubuntu24.04-x64"})
        .set_user("e2e")
    )
