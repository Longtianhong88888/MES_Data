#!/usr/bin/env python3
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
