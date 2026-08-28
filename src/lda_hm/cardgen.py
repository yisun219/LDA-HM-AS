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
}

# Benchmark profiles the CURRENT template supports end to end. Everything
# else is refused with its template requirements listed.
BENCHMARK_PROFILES = {
    "libcairo2": {
        "micro": {
            "name": "cairo-ops-micro",
            "script": "run-cairo-ops-micro.sh",
            "repetitions": 7,
            "timeout_seconds": 1800,
            "inputs": ["png-load", "paint", "mask", "text-path"],
            "max_regression_percent": 2.0,
            "min_speedup_percent": 2.0,
            "holdout_min_speedup_percent": 1.0,
            "holdout_env": "LDA_CAIRO_FIXDIR",
            "holdout_setup": [
                "env", "LDA_FIXTURE_DIR={dir}", "LDA_FIXTURE_SEED={seed}",
                "LDA_FIXTURE_PNGS_ONLY=1",
                "/opt/lda/harness/checks/prepare-libpng-fixtures.sh",
            ],
        },
        "e2e": {
            "name": "cairo-stack-e2e",
            "script": "run-cairo-stack-e2e.sh",
            "repetitions": 7,
            "timeout_seconds": 1800,
            "inputs": ["cairo-png-load"],
            "max_regression_percent": 3.0,
            "min_speedup_percent": 1.0,
        },
    },
}

# Card check-script names per profile family; cairo doubles as the reference
# shape for future dlopen-consumer packages.
CHECKS = {
    "libcairo2": {
        "ffi": "run-cairo-ffi-fence.sh",
        "behavior": "run-cairo-behavior-fence.sh",
        "selfcheck": "run-cairo-selfcheck.sh",
    },
}

TEMPLATE_NEEDS = {
    "libgtk-4-1": "gtk4 runtime + libgtk-4-dev-tools + weston/xvfb widget bench (template v11)",
    "libgtk-3-0t64": "gtk3 runtime + gtk3-widget bench under Xvfb (template v11)",
    "gnome-shell": "full GNOME session harness; out of headless scope until template v12",
    "libreoffice-core": "LibreOffice + document corpus (template v12)",
    "sssd-common": "sssd + LDAP fixture harness (template v12)",
    "gnome-settings-daemon": "GNOME session harness (template v12)",
    "ibus": "ibus daemon + input fixture harness (template v12)",
    "gstreamer1.0-plugins-good": "gstreamer runtime + gst-launch decode corpus (template v11)",
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
        f"LDA_PKG_SOURCE={source}",
        f"LDA_PKG_VERSION={version}",
        f"LDA_PKG_RUNTIME_DEBS={runtime_debs}",
    ]

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
            ["/opt/lda/harness/checks/prepare-libpng-fixtures.sh"],
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
