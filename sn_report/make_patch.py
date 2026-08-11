#!/usr/bin/env python3
"""生成增量补丁:对比上次基线,只输出变更文件,供台式机应用。

用法(本机,改完代码后):
    python sn_report/make_patch.py
    python sn_report/make_patch.py -m "修复 VS 站查询慢/增加时间窗过滤"

产物: sn_report/patches/patch_<时间戳>/
    manifest.json      补丁清单(版本/文件哈希/说明)
    apply_patch.py     台式机应用脚本
    apply_patch.bat    台式机双击入口
    files/<相对路径>    变更文件(相对 oracle_download/)

台式机应用: 把 patch_<时间戳>/ 整个目录拷到 package_oracle_verify/ 下,
双击 apply_patch.bat 即可(自动覆盖 oracle_download/ 中对应文件)。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

SN_REPORT_DIR = Path(__file__).resolve().parent
PKG_DIR = SN_REPORT_DIR / "package_oracle_verify"
SRC_DIR = PKG_DIR / "oracle_download"          # 台式机运行根目录
BASELINE = SN_REPORT_DIR / ".patch_baseline.json"
PATCHES_DIR = SN_REPORT_DIR / "patches"

# 需要纳入补丁的文件(相对 SRC_DIR);不包含 wheels/instantclient/conns.json
PATCH_FILES = [
    "run_oracle_download.py",
    "lib/oracle_client.py",
    "lib/config.py",
    "lib/__init__.py",
    "lib/login_dialog.py",
    "lib/rayprush_auth.py",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_baseline() -> dict:
    if BASELINE.exists():
        return json.loads(BASELINE.read_text(encoding="utf-8"))
    return {"files": {}}


def build_manifest(prev: dict, message: str) -> dict:
    files = {}
    for rel in PATCH_FILES:
        p = SRC_DIR / rel
        if p.exists():
            files[rel] = sha256(p)
    changed = {
        rel: h for rel, h in files.items()
        if prev.get("files", {}).get(rel) != h
    }
    return {
        "patch_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "message": message,
        "base_files": prev.get("files", {}),
        "files": files,
        "changed": changed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--message", default="", help="补丁说明")
    args = parser.parse_args()

    prev = load_baseline()
    manifest = build_manifest(prev, args.message)
    changed = manifest["changed"]

    if not changed:
        print("无变更,跳过(代码与上次基线一致)。")
        return

    patch_dir = PATCHES_DIR / f"patch_{manifest['patch_id']}"
    (patch_dir / "files").mkdir(parents=True, exist_ok=True)
    for rel in changed:
        src = SRC_DIR / rel
        dst = patch_dir / "files" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    # 应用脚本
    apply_py = '''#!/usr/bin/env python3
"""应用补丁:把 files/ 下文件覆盖到上级 oracle_download/。"""
import json
import shutil
import sys
from pathlib import Path

patch_dir = Path(__file__).resolve().parent
root = patch_dir.parent          # package_oracle_verify/
target = root / "oracle_download"
manifest = json.loads((patch_dir / "manifest.json").read_text(encoding="utf-8"))

changed = manifest.get("changed", {})
if not changed:
    print("补丁清单为空,退出。")
    sys.exit(0)

ok, fail = 0, []
for rel in changed:
    src = patch_dir / "files" / rel
    dst = target / rel
    if not src.exists():
        fail.append(rel)
        continue
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    ok += 1

# 记录已应用
applied_path = root / ".applied_patches.json"
applied = json.loads(applied_path.read_text(encoding="utf-8")) if applied_path.exists() else []
applied.append({
    "patch_id": manifest["patch_id"],
    "applied": manifest["created"],
    "files": list(changed),
})
applied_path.write_text(json.dumps(applied, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"补丁 {manifest['patch_id']} 应用完成: 更新 {ok} 个文件")
if fail:
    print("失败文件:", fail)
'''
    (patch_dir / "apply_patch.py").write_text(apply_py, encoding="utf-8")
    (patch_dir / "apply_patch.bat").write_bytes(
        b"\xef\xbb\xbf" + (
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            "cd /d %~dp0\r\n"
            "echo Applying patch %~dp0 ...\r\n"
            "set PY=\r\n"
            "if exist ..\\python\\python.exe set PY=..\\python\\python.exe\r\n"
            "if not defined PY for %%F in (python python3) do (where %%F >nul 2>&1 && set PY=%%F)\r\n"
            "if not defined PY (\r\n"
            "  echo Python not found. Run: python apply_patch.py\r\n"
            "  pause\r\n"
            "  exit /b 1\r\n"
            ")\r\n"
            "%PY% apply_patch.py\r\n"
            "pause\r\n"
        ).encode("utf-8")
    )
    # 更新基线
    BASELINE.write_text(
        json.dumps({"files": manifest["files"], "last_patch": manifest["patch_id"]},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"补丁生成: {patch_dir}")
    print(f"变更文件: {len(changed)} 个")
    for rel in changed:
        print("  +", rel)
    print("台式机: 把 patch_<时间戳>/ 拷到 package_oracle_verify/ 下,双击 apply_patch.bat")


if __name__ == "__main__":
    main()
