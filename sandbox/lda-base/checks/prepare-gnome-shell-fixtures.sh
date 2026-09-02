#!/usr/bin/env bash
# Fixtures for the gnome-shell startup workbench: the mock-session runner
# (copied from the pinned baseline source so a candidate can never edit the
# harness it is measured with), the automation scripts and a background.
set -euo pipefail
directory="${LDA_FIXTURE_DIR:-/opt/lda/fixtures/gnome-shell}"
mkdir -p "$directory"
src=/opt/lda/work
git -C "$src" show 'refs/tags/lda-baseline^{}:tests/gnomeshell_dbusrunner.py' >"$directory/gnomeshell_dbusrunner.py"
mkdir -p "$directory/dbusmock-templates"
for f in $(git -C "$src" ls-tree --name-only 'refs/tags/lda-baseline^{}' tests/dbusmock-templates/); do
  git -C "$src" show "refs/tags/lda-baseline^{}:$f" >"$directory/dbusmock-templates/$(basename "$f")"
done
git -C "$src" show 'refs/tags/lda-baseline^{}:tests/data/background.png' >"$directory/background.png"
cat >"$directory/runner.py" <<'PY'
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(1, '/usr/share/mutter-18/tests')
sys.path.insert(2, here)
from mutter_dbusrunner import meta_run
from gnomeshell_dbusrunner import GnomeShellDBusRunner
sys.exit(meta_run(GnomeShellDBusRunner))
PY
cat >"$directory/startup.js" <<'JS'
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as Scripting from 'resource:///org/gnome/shell/ui/scripting.js';

export var METRICS = {};

export function init() {}

export async function run() {
    await Scripting.waitLeisure();
}

export function finish() {
    const monitors = global.display.get_n_monitors();
    const mode = Main.sessionMode.currentMode;
    const panel = Main.panel ? Main.panel.get_children().length : -1;
    const workspaces = global.workspace_manager.get_n_workspaces();
    print(`LDA-SHELL startup monitors=${monitors} mode=${mode} panel=${panel} workspaces=${workspaces}`);
}
JS
cat >"$directory/overview.js" <<'JS'
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as Scripting from 'resource:///org/gnome/shell/ui/scripting.js';

export var METRICS = {};
let shown = 0;
let hidden = 0;

export function init() {
    Main.overview.connect('shown', () => { shown += 1; });
    Main.overview.connect('hidden', () => { hidden += 1; });
}

export async function run() {
    await Scripting.waitLeisure();
    for (let i = 0; i < 3; i++) {
        Main.overview.show();
        await Scripting.waitLeisure();
        Main.overview.hide();
        await Scripting.waitLeisure();
    }
}

export function finish() {
    const monitors = global.display.get_n_monitors();
    print(`LDA-SHELL overview monitors=${monitors} shown=${shown} hidden=${hidden}`);
}
JS
printf 'gnome-shell fixtures ready in %s\n' "$directory"
