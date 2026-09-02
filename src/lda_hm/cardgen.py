"""Task-card generation for ranked Ubuntu 26.04 candidates.

`lda gen-card <binary-package>` turns one ranked candidate into a runnable
card: exact version from the pinned ISO manifest, generic build/fence
commands, and - where the current template can measure it rigorously - a
vetted benchmark profile. Packages whose workloads need template additions
are refused with the exact missing pieces listed, because an unmeasurable
card would burn agent rounds against nothing.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional

from .candidates import load_candidates

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "sandbox" / "lda-base" / "baseline" / "manifest" / "debian-packages.tsv"

# Binary package -> Debian source package + workbench parameters.
SOURCE_MAP = {
    "libcairo2": {
        "source": "cairo",
        "runtime_debs": "libcairo2",
        "probe": "test -e /usr/lib/x86_64-linux-gnu/libcairo.so.2",
    },
    "libgdk-pixbuf-2.0-0": {
        "source": "gdk-pixbuf",
        "runtime_debs": "libgdk-pixbuf-2.0-0",
        "probe": "gdk-pixbuf-csource --help >/dev/null",
    },
    "libpng16-16t64": {"source": "libpng1.6", "runtime_debs": "libpng16-16t64"},
    "libgtk-4-1": {"source": "gtk4", "runtime_debs": "libgtk-4-1"},
    "sssd-common": {
        "source": "sssd",
        "runtime_debs": "sssd-common libnss-sss sssd-proxy",
        "probe": "test -x /usr/sbin/sssd",
    },
    "libgtk-3-0t64": {"source": "gtk+3.0", "runtime_debs": "libgtk-3-0t64"},
    "libsoup-3.0-0": {"source": "libsoup3", "runtime_debs": "libsoup-3.0-0"},
    "libpango-1.0-0": {"source": "pango1.0", "runtime_debs": "libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0"},
    "gstreamer1.0-plugins-good": {"source": "gst-plugins-good1.0", "runtime_debs": "gstreamer1.0-plugins-good"},
    "libtiff6": {"source": "tiff", "runtime_debs": "libtiff6"},
    "libheif1": {"source": "libheif", "runtime_debs": "libheif1"},
    "libpulse0": {"source": "pulseaudio", "runtime_debs": "libpulse0"},
    "libadwaita-1-0": {"source": "libadwaita-1", "runtime_debs": "libadwaita-1-0"},
    "libgstreamer-gl1.0-0": {"source": "gst-plugins-base1.0", "runtime_debs": "libgstreamer-gl1.0-0"},
    "libgstreamer-plugins-base1.0-0": {"source": "gst-plugins-base1.0", "runtime_debs": "libgstreamer-plugins-base1.0-0"},
    "gstreamer1.0-plugins-base": {"source": "gst-plugins-base1.0", "runtime_debs": "gstreamer1.0-plugins-base"},
    "gnome-shell": {"source": "gnome-shell", "runtime_debs": "gnome-shell", "probe": "test -x /usr/bin/gnome-shell"},
    "libreoffice-core": {"source": "libreoffice", "runtime_debs": "libreoffice-core", "probe": "test -x /usr/lib/libreoffice/program/soffice.bin"},
    "gnome-settings-daemon": {"source": "gnome-settings-daemon", "runtime_debs": "gnome-settings-daemon", "probe": "test -d /usr/libexec"},
    "ibus": {"source": "ibus", "runtime_debs": "ibus libibus-1.0-5", "probe": "test -x /usr/bin/ibus-daemon"},
}

# Benchmark profiles the CURRENT template supports end to end. Everything
# else is refused with its template requirements listed.
BENCHMARK_PROFILES = {
    "libsoup-3.0-0": {
        "tests_policy": "reference",
        "setup": [
            "prepare-soup-fixtures.sh",
            "install-soup-workbench.sh",
        ],
        "micro": {
            "name": "soup-headers-micro",
            "script": "run-soup-headers-micro.sh",
            "repetitions": 7,
            "timeout_seconds": 1800,
            "inputs": ["header-churn"],
            "max_regression_percent": 2.0,
            "min_speedup_percent": 2.0,
            "holdout_min_speedup_percent": 1.0,
            "holdout_env": "LDA_SOUP_FIXDIR",
            "holdout_setup": [
                "env", "LDA_FIXTURE_DIR={dir}", "LDA_FIXTURE_SEED={seed}",
                "/opt/lda/harness/checks/prepare-soup-fixtures.sh",
            ],
        },
        "e2e": {
            "name": "soup-http-e2e",
            "script": "run-soup-http-e2e.sh",
            "repetitions": 7,
            "timeout_seconds": 1800,
            "inputs": ["http-roundtrip"],
            "max_regression_percent": 3.0,
        },
    },
    "sssd-common": {
        "tests_policy": "reference",
        "setup": [
            "prepare-sssd-fixtures.sh",
            "install-sssd-workbench.sh",
        ],
        "micro": {
            "name": "sssd-nss-micro",
            "script": "run-sssd-nss-micro.sh",
            "repetitions": 7,
            "timeout_seconds": 2400,
            "inputs": ["nss-lookups"],
            "max_regression_percent": 2.0,
            "min_speedup_percent": 2.0,
            "holdout_min_speedup_percent": 1.0,
            "holdout_env": "LDA_SSSD_FIXDIR",
            "holdout_setup": [
                "env", "LDA_FIXTURE_DIR={dir}", "LDA_FIXTURE_SEED={seed}",
                "/opt/lda/harness/checks/prepare-sssd-fixtures.sh",
            ],
        },
        "e2e": {
            "name": "sssd-id-e2e",
            "script": "run-sssd-id-e2e.sh",
            "repetitions": 7,
            "timeout_seconds": 2400,
            "inputs": ["getent-processes"],
            "max_regression_percent": 3.0,
        },
    },
    "libgtk-4-1": {
        "tests_policy": "reference",
        "extra_env": {"LDA_GTK_MAJOR": "4"},
        "setup": [
            "prepare-gtk-fixtures.sh",
            "install-gtk-workbench.sh",
        ],
        "micro": {
            "name": "gtk-ops-micro",
            "script": "run-gtk-ops-micro.sh",
            "repetitions": 7,
            "timeout_seconds": 2400,
            "inputs": ["css-parse", "style-match", "layout"],
            "max_regression_percent": 2.0,
            "min_speedup_percent": 2.0,
            "holdout_min_speedup_percent": 1.0,
            "holdout_env": "LDA_GTK_FIXDIR",
            "holdout_setup": [
                "env", "LDA_FIXTURE_DIR={dir}", "LDA_FIXTURE_SEED={seed}",
                "/opt/lda/harness/checks/prepare-gtk-fixtures.sh",
            ],
        },
        "e2e": {
            "name": "gtk-gi-churn",
            "script": "run-gtk-gi-e2e.sh",
            "repetitions": 7,
            "timeout_seconds": 2400,
            "inputs": ["gtk-gi-churn"],
            "max_regression_percent": 3.0,
        },
    },
    "libgtk-3-0t64": {
        "tests_policy": "reference",
        "extra_env": {"LDA_GTK_MAJOR": "3"},
        "setup": [
            "prepare-gtk-fixtures.sh",
            "install-gtk-workbench.sh",
        ],
        "micro": {
            "name": "gtk-ops-micro",
            "script": "run-gtk-ops-micro.sh",
            "repetitions": 7,
            "timeout_seconds": 2400,
            "inputs": ["css-parse", "style-match", "layout"],
            "max_regression_percent": 2.0,
            "min_speedup_percent": 2.0,
            "holdout_min_speedup_percent": 1.0,
            "holdout_env": "LDA_GTK_FIXDIR",
            "holdout_setup": [
                "env", "LDA_FIXTURE_DIR={dir}", "LDA_FIXTURE_SEED={seed}",
                "/opt/lda/harness/checks/prepare-gtk-fixtures.sh",
            ],
        },
        "e2e": {
            "name": "gtk-gi-churn",
            "script": "run-gtk-gi-e2e.sh",
            "repetitions": 7,
            "timeout_seconds": 2400,
            "inputs": ["gtk-gi-churn"],
            "max_regression_percent": 3.0,
        },
    },
    "libcairo2": {
        "setup": [
            "prepare-libpng-fixtures.sh",
            "prepare-cairo-path-fixtures.sh",
        ],
        "micro": {
            "name": "cairo-owned-micro",
            "script": "run-cairo-owned-micro.sh",
            "repetitions": 7,
            "timeout_seconds": 1800,
            "inputs": ["stroke-dash", "fill-tess", "text-corpus"],
            "max_regression_percent": 2.0,
            "min_speedup_percent": 2.0,
            "holdout_min_speedup_percent": 1.0,
            "holdout_env": "LDA_CAIRO_PATHDIR",
            "holdout_setup": [
                "env", "LDA_FIXTURE_DIR={dir}", "LDA_FIXTURE_SEED={seed}",
                "/opt/lda/harness/checks/prepare-cairo-path-fixtures.sh",
            ],
        },
        "e2e": {
            "name": "cairo-stack-e2e",
            "script": "run-cairo-stack-e2e.sh",
            "repetitions": 7,
            "timeout_seconds": 1800,
            "inputs": ["cairo-png-load"],
            "max_regression_percent": 3.0,
        },
    },
    "gnome-shell": {
        "tests_policy": "reference",
        "setup": ["install-gnome-shell-workbench.sh"],
        "micro": {
            "name": "gnome-shell-startup",
            "script": "run-gnome-shell-micro.sh",
            "repetitions": 7,
            "timeout_seconds": 1800,
            "inputs": ["headless-startup"],
            "max_regression_percent": 2.0,
            "min_speedup_percent": 2.0,
        },
        "e2e": {
            "name": "gnome-shell-overview-e2e",
            "script": "run-gnome-shell-e2e.sh",
            "repetitions": 7,
            "timeout_seconds": 1800,
            "inputs": ["overview-session"],
            "max_regression_percent": 3.0,
        },
    },
    "libreoffice-core": {
        "tests_policy": "reference",
        "setup": ["install-lo-workbench.sh"],
        "micro": {
            "name": "libreoffice-convert-micro",
            "script": "run-lo-micro.sh",
            "repetitions": 7,
            "timeout_seconds": 2400,
            "inputs": ["writer-to-pdf", "calc-to-pdf"],
            "max_regression_percent": 2.0,
            "min_speedup_percent": 2.0,
            "holdout_min_speedup_percent": 1.0,
            "holdout_env": "LDA_LO_FIXDIR",
            "holdout_setup": [
                "env", "LDA_FIXTURE_DIR={dir}", "LDA_FIXTURE_SEED={seed}",
                "/opt/lda/harness/checks/prepare-lo-fixtures.sh",
            ],
        },
        "e2e": {
            "name": "libreoffice-roundtrip-e2e",
            "script": "run-lo-e2e.sh",
            "repetitions": 7,
            "timeout_seconds": 2400,
            "inputs": ["office-roundtrip"],
            "max_regression_percent": 3.0,
        },
    },
    "gnome-settings-daemon": {
        "tests_policy": "reference",
        "setup": ["install-gsd-workbench.sh"],
        "micro": {
            "name": "gsd-plugin-startup",
            "script": "run-gsd-micro.sh",
            "repetitions": 7,
            "timeout_seconds": 1800,
            "inputs": ["plugin-startup"],
            "max_regression_percent": 2.0,
            "min_speedup_percent": 2.0,
        },
        "e2e": {
            "name": "gsd-session-start-e2e",
            "script": "run-gsd-e2e.sh",
            "repetitions": 7,
            "timeout_seconds": 1800,
            "inputs": ["session-start"],
            "max_regression_percent": 3.0,
        },
    },
    "gstreamer1.0-plugins-good": {
        "tests_policy": "reference",
        "setup": ["install-gst-workbench.sh"],
        "micro": {
            "name": "gst-good-micro",
            "script": "run-gst-good-micro.sh",
            "repetitions": 7,
            "timeout_seconds": 2400,
            "inputs": ["video-filters", "video-effects", "audio-fx"],
            "max_regression_percent": 2.0,
            "min_speedup_percent": 2.0,
            "holdout_min_speedup_percent": 1.0,
            "holdout_env": "LDA_GST_FIXDIR",
            "holdout_setup": [
                "env", "LDA_FIXTURE_DIR={dir}", "LDA_FIXTURE_SEED={seed}",
                "/opt/lda/harness/checks/prepare-gst-fixtures.sh",
            ],
        },
        "e2e": {
            "name": "gst-good-transcode-e2e",
            "script": "run-gst-good-e2e.sh",
            "repetitions": 7,
            "timeout_seconds": 1800,
            "inputs": ["transcode"],
            "max_regression_percent": 3.0,
        },
    },
    "ibus": {
        "tests_policy": "reference",
        "setup": ["install-ibus-workbench.sh"],
        "micro": {
            "name": "ibus-registry-micro",
            "script": "run-ibus-micro.sh",
            "repetitions": 7,
            "timeout_seconds": 2400,
            "inputs": ["registry"],
            "max_regression_percent": 2.0,
            "min_speedup_percent": 2.0,
            "holdout_min_speedup_percent": 1.0,
            "holdout_env": "LDA_IBUS_FIXDIR",
            "holdout_setup": [
                "env", "LDA_FIXTURE_DIR={dir}", "LDA_FIXTURE_SEED={seed}",
                "/opt/lda/harness/checks/prepare-ibus-fixtures.sh",
            ],
        },
        "e2e": {
            "name": "ibus-key-session-e2e",
            "script": "run-ibus-e2e.sh",
            "repetitions": 7,
            "timeout_seconds": 2400,
            "inputs": ["key-session"],
            "max_regression_percent": 3.0,
        },
    },
}

# Card check-script names per profile family; cairo doubles as the reference
# shape for future dlopen-consumer packages.
CHECKS = {
    "libsoup-3.0-0": {
        "ffi": "run-soup-ffi-fence.sh",
        "behavior": "run-soup-behavior-fence.sh",
        "selfcheck": "run-soup-selfcheck.sh",
    },
    "libcairo2": {
        "ffi": "run-cairo-ffi-fence.sh",
        "behavior": "run-cairo-owned-behavior-fence.sh",
        "selfcheck": "run-cairo-owned-selfcheck.sh",
    },
    "sssd-common": {
        "ffi": "run-sssd-ffi-fence.sh",
        "behavior": "run-sssd-behavior-fence.sh",
        "selfcheck": "run-sssd-selfcheck.sh",
    },
    "libgtk-4-1": {
        "ffi": "run-gtk-ffi-fence.sh",
        "behavior": "run-gtk-behavior-fence.sh",
        "selfcheck": "run-gtk-selfcheck.sh",
    },
    "libgtk-3-0t64": {
        "ffi": "run-gtk-ffi-fence.sh",
        "behavior": "run-gtk-behavior-fence.sh",
        "selfcheck": "run-gtk-selfcheck.sh",
    },
    "gnome-shell": {
        "ffi": "run-gnome-shell-ffi-fence.sh",
        "behavior": "run-gnome-shell-behavior-fence.sh",
        "selfcheck": "run-gnome-shell-selfcheck.sh",
    },
    "libreoffice-core": {
        "ffi": "run-lo-ffi-fence.sh",
        "behavior": "run-lo-behavior-fence.sh",
        "selfcheck": "run-lo-selfcheck.sh",
    },
    "gnome-settings-daemon": {
        "ffi": "run-gsd-ffi-fence.sh",
        "behavior": "run-gsd-behavior-fence.sh",
        "selfcheck": "run-gsd-selfcheck.sh",
    },
    "gstreamer1.0-plugins-good": {
        "ffi": "run-gst-good-ffi-fence.sh",
        "behavior": "run-gst-good-behavior-fence.sh",
        "selfcheck": "run-gst-good-selfcheck.sh",
    },
    "ibus": {
        "ffi": "run-ibus-ffi-fence.sh",
        "behavior": "run-ibus-behavior-fence.sh",
        "selfcheck": "run-ibus-selfcheck.sh",
    },
}

TEMPLATE_NEEDS = {
    "gnome-shell": "headless startup probe; frame-loop acceleration is not claimed",
    "libreoffice-core": "LibreOffice document corpus and headless conversion",
    "gnome-settings-daemon": "headless plugin startup subset",
    "ibus": "headless daemon and engine-list fixture",
    "gstreamer1.0-plugins-good": "gstreamer runtime and demux/decode corpus",
    "libsoup-3.0-0": "libsoup runtime + local HTTP fixture server (template v11)",
}


def manifest_version(binary_package: str) -> Optional[str]:
    with MANIFEST.open(encoding="utf-8") as stream:
        for row in csv.reader(stream, delimiter="\t"):
            if len(row) >= 2 and row[0].split(":", 1)[0] == binary_package:
                return row[1]
    return None


def generate_card(binary_package: str, apt_snapshot_card: dict) -> dict:
    ranked = {candidate.package: candidate for candidate in load_candidates()}
    if binary_package not in ranked:
        raise SystemExit(
            f"{binary_package} is not in the ranked top-30; "
            "gen-card only serves the priority list"
        )
    version = manifest_version(binary_package)
    if version is None:
        raise SystemExit(f"{binary_package} not found in the pinned ISO manifest")
    mapping = SOURCE_MAP.get(binary_package)
    if mapping is None:
        raise SystemExit(
            f"no source mapping for {binary_package}; add it to cardgen.SOURCE_MAP"
        )
    profile = BENCHMARK_PROFILES.get(binary_package)
    if profile is None:
        need = TEMPLATE_NEEDS.get(binary_package, "a vetted benchmark profile")
        raise SystemExit(
            f"{binary_package} has no benchmark profile the current template can "
            f"measure rigorously. Needed: {need}. Refusing to emit an "
            "unmeasurable card."
        )
    candidate = ranked[binary_package]
    source = mapping["source"]
    runtime_debs = mapping["runtime_debs"]
    env = [
        "env",
        f"LDA_TOP10_PACKAGE={binary_package}",
        f"LDA_PKG_SOURCE={source}",
        f"LDA_PKG_VERSION={version}",
        f"LDA_PKG_RUNTIME_DEBS={runtime_debs}",
    ]
    tests_policy = profile.get("tests_policy", "required")
    if tests_policy != "required":
        env.append(f"LDA_UPSTREAM_TESTS={tests_policy}")
    for key, value in sorted((profile.get("extra_env") or {}).items()):
        env.append(f"{key}={value}")

    def wrapped(script: str, *arguments: str) -> list:
        return env + [f"/opt/lda/harness/checks/{script}", *arguments]

    checks = CHECKS[binary_package]
    probe = mapping.get("probe")
    lifecycle = env + ([f"LDA_PKG_PROBE={probe}"] if probe else []) + [
        "/opt/lda/harness/checks/run-generic-lifecycle.sh"
    ]

    def benchmark(profile_entry: dict, layer: str) -> dict:
        script = profile_entry["script"]
        entry = {
            key: value for key, value in profile_entry.items() if key != "script"
        }
        entry["layer"] = layer
        entry["command"] = wrapped(script)
        entry["baseline_command"] = wrapped(script, "baseline")
        return entry

    def setup_scripts() -> list:
        # Setup scripts get the same card environment as every other check,
        # so a workbench that needs LDA_GTK_MAJOR (or a future card knob)
        # reads it from the card, not from the host shell.
        return [
            wrapped(script)
            for script in profile.get("setup", ["prepare-libpng-fixtures.sh"])
        ]

    card = {
        "package": {
            "package": binary_package,
            "usage_frequency": min(1.0, candidate.score / 100.0 + 0.2),
            "performance_criticality": min(1.0, candidate.score / 100.0 + 0.2),
            "dependency_centrality": min(1.0, candidate.score / 80.0),
            "architecture_fit": 1.0,
            "rationale": f"dependency-graph rank score {candidate.score} (direction {candidate.direction})",
        },
        "goal": (
            f"Optimize {binary_package} for Ubuntu 26.04 while preserving "
            "surgical replacement compatibility"
        ),
        "source_reference": f"ubuntu:resolute/{source}={version}@{apt_snapshot_card['apt_snapshot'].rstrip('/').rsplit('/', 1)[-1]}",
        "setup_commands": [
            ["/opt/lda/harness/checks/prepare-ubuntu-source.sh", source, version],
            wrapped("build-package.sh", "baseline"),
        ]
        + setup_scripts()
        + [
            ["/opt/lda/harness/checks/install-test-tools.sh"],
            wrapped("run-autopkgtest-fence.sh", "baseline"),
        ],
        "candidate_build": wrapped("ensure-pkg-candidate.sh"),
        "selfcheck_commands": (
            [wrapped(checks["selfcheck"])] if checks.get("selfcheck") else []
        ),
        "baseline_tests": [wrapped("run-generic-build-tests.sh")],
        "dependency_tests": [
            wrapped("run-autopkgtest-fence.sh", "candidate"),
            [
                "sh", "-c",
                "ldconfig -p >/dev/null && test -s /opt/lda/candidate/libraries.list",
            ],
        ],
        "abi_checks": [wrapped("run-generic-abi-fence.sh")],
        "ffi_checks": [wrapped(checks["ffi"])],
        "behavior_checks": [wrapped(checks["behavior"])],
        "package_lifecycle_checks": [lifecycle],
        "security_checks": [wrapped("run-generic-security-fence.sh")],
        "result_equivalence_checks": [wrapped(checks["behavior"])],
        "micro_benchmarks": [benchmark(profile["micro"], "micro")],
        "end_to_end_benchmarks": [benchmark(profile["e2e"], "end_to_end")],
        "baseline": apt_snapshot_card,
        "compatibility": {
            "soname_unchanged": True,
            "exported_symbols_unchanged": True,
            "abi_types_unchanged": True,
            "ffi_call_surface_unchanged": True,
            "behavior_unchanged": True,
            "configuration_preserved": True,
            "security_defaults_preserved": True,
            "result_equivalence_required": True,
        },
        "lane": "mainline",
        "metadata": {
            "target_cpu": "INTEL(R) XEON(R) GOLD 6548Y+",
            "target_release": "ubuntu-26.04",
            "generated_by": "lda gen-card",
            "rank_score": candidate.score,
            "direction": candidate.direction,
        },
    }
    return card
