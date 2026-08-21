---
name: lda-deb-rebuild
description: 在 Ubuntu 26.04 里取源码、打补丁、整族重建 .deb,并给出带 a0turboN 后缀且不阻挡官方安全更新的版本号
---

# 整族重建 .deb

1. **取源**:`apt-get source <src>`(模板已开 deb-src)。用 `dpkg-parsechangelog` 读当前版本。
2. **打补丁**:改动只落在 `debian/patches/`(quilt 格式),`quilt new`/`quilt add`/`quilt refresh`;
   不要直接改上游文件而不入 patch 队列——审查者会核对。
3. **版本号**:在当前版本后追加 `a0turboN`(如 `2.15.0-1ubuntu2a0turbo1`)。
   规则要点:它必须**大于**当前版本,又必须**小于**官方后续的 `ubuntu0.X` 安全更新形状,
   用 `dpkg --compare-versions` 三向实测验证,别凭直觉。
4. **整族重建**:以 `debian/control` 的二进制包清单为准,一个都不能少(含 -dev、-doc、udeb)。
   `dpkg-buildpackage -b -uc -us`(需要源码依赖时先 `apt-get build-dep`)。
5. **夹带检查**:除目标改动外的产物必须与"未打补丁的重建"逐字节相同。
   做法:同一环境先做一次干净重建留档,再做补丁重建,`cmp` 逐个二进制;
   有差异就查明(常见无害差异:构建时间戳、构建路径,应通过可复现构建选项消除后再比)。
6. **安装验证**:`dpkg -i` 全族安装 → 升级 → 卸载 → 重装循环 + `dpkg -V`,带一个未改动的对照臂。
