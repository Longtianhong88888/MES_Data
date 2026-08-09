#!/usr/bin/env python3
"""SN 全制程追溯报告工具(入口)。

功能:
  输入一个或多个 SN(通常为 FACA 用 Fail SN),一键查询每个 SN 的
  站位轨迹 / 机台号 / 载板号 / 穴位号 / 组件绑定 / PR 图片,
  并汇总生成 PPT 报告。

用法(Windows):
  双击 run_sn_report.bat,或在命令行:
    python sn_report.py --sns sns.txt --out output/报告.pptx

常用参数:
  --sns PATH       SN 列表(.txt 每行一个 / .csv / .xlsx 第一列)
  --sn SN          单个 SN 快速查询
  --out PATH       PPT 输出路径(默认 output/SN全制程追溯报告.pptx)
  --discover       发现模式:只查第一个 SN 并把所有页面表格结构 dump 出来
  --no-images      不查询 MC IMG 图片
  --no-acf         不查询 ACF 测试数据
  --c4             启用战情中心 C4 批量接口(机台/载板/穴位,需在 config.json 填 token)
  --init-config    生成默认配置文件后退出
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# 让本工具可以被直接 python sn_report.py 运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sn_report.lib.config import (
    PROJECT_DIR,
    SN_REPORT_DIR,
    ensure_windows_lib,
    get_root_config,
    get_sn_report_config,
    load_sn_list,
)

# Windows 下优先用项目内 lib/ 离线依赖(必须在导入 requests/bs4 之前)
ensure_windows_lib()

from sn_report.lib import config as cfg_mod
from sn_report.lib.mes_client import MesClient
from sn_report.lib.models import SnRecord
from sn_report.lib.ppt_report import build_ppt


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    _LOG_LINES.append(line)


_LOG_LINES: List[str] = []


def save_log(path: Path) -> None:
    path.write_text("\n".join(_LOG_LINES) + "\n", encoding="utf-8")


def init_config() -> None:
    path = SN_REPORT_DIR / "config.json"
    if path.exists():
        print(f"配置文件已存在: {path}")
        return
    path.write_text(
        json.dumps(cfg_mod.DEFAULT_SN_REPORT_CONFIG, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已生成默认配置: {path}")
    print("请至少检查: 1) sn_list_file; 2) analysis_window; 3) c4.token(如启用 C4)")


def discover(args: argparse.Namespace, mes: MesClient, cfg: Dict[str, Any],
             sns: List[str]) -> None:
    """发现模式:dump 第一个 SN 的 snsearch/sntotalinfo 表格结构,帮助确认字段。"""
    sn = sns[0]
    log(f"[discover] 分析 SN: {sn}")
    out = SN_REPORT_DIR / "output" / "discover"
    out.mkdir(parents=True, exist_ok=True)

    html = mes.sn_search(sn)
    tables = mes.parse_tables(html)
    lines: List[str] = [f"===== snsearch: {sn} ===== 表格数: {len(tables)}"]
    for ti, tbl in enumerate(tables, start=1):
        lines.append(f"--- 表 {ti} | caption={tbl['caption']} | 列数={len(tbl['headers'])}")
        lines.append("表头: " + " | ".join(tbl["headers"]))
        for row in tbl["rows"][:20]:
            lines.append("  " + " | ".join(row))
    try:
        html2 = mes.sntotalinfo(sn)
        if html2:
            tables2 = mes.parse_tables(html2)
            lines.append(f"\n===== sntotalinfo: {sn} ===== 表格数: {len(tables2)}")
            for ti, tbl in enumerate(tables2, start=1):
                lines.append(f"--- 表 {ti} | caption={tbl['caption']} | 列数={len(tbl['headers'])}")
                lines.append("表头: " + " | ".join(tbl["headers"]))
                for row in tbl["rows"][:20]:
                    lines.append("  " + " | ".join(row))
    except Exception as exc:  # noqa: BLE001
        lines.append(f"sntotalinfo 失败: {exc}")

    dump = out / f"discover_{sn}.txt"
    dump.write_text("\n".join(lines), encoding="utf-8")
    log(f"[discover] 表格结构已保存: {dump}")
    log("[discover] 对照表头确认 机台/载板/穴位 字段后,在 config.json 配置 C4 列或调整解析关键词")


def run(args: argparse.Namespace) -> int:
    cfg = get_sn_report_config()
    root = get_root_config()

    sn_report_dir = SN_REPORT_DIR
    out_dir = sn_report_dir / str(cfg["report"]["output_dir"])
    dl_dir = sn_report_dir / str(cfg["report"]["download_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    dl_dir.mkdir(parents=True, exist_ok=True)

    if args.sn:
        sns = [args.sn]
    else:
        sn_path = Path(args.sns) if args.sns else sn_report_dir / str(cfg.get("sn_list_file", "sns.txt"))
        if not sn_path.is_absolute():
            sn_path = PROJECT_DIR / sn_path
        sns = load_sn_list(sn_path)
    if not sns:
        log("SN 列表为空,请检查输入文件")
        return 2
    log(f"SN 数量: {len(sns)} -> {sns[:5]}{'...' if len(sns) > 5 else ''}")

    mes = MesClient(root, out_dir)
    log("Step 1/5: 登录 MES ...")
    mes.login()
    log(f"Step 1/5: 登录成功({len(mes.frames)} frames)")

    if args.discover:
        discover(args, mes, cfg, sns)
        return 0

    window = cfg.get("analysis_window", {})
    start, end = str(window.get("start", "")), str(window.get("end", ""))

    # Step 2: SN 查询(站位轨迹/组件/耗材)
    records: List[SnRecord] = []
    log(f"Step 2/5: 查询 {len(sns)} 个 SN 的全制程信息 ...")
    for i, sn in enumerate(sns, start=1):
        rec = mes.collect_sn(sn, cfg.get("column_keywords", {}))
        records.append(rec)
        st = "OK" if not rec.errors else f"WARN({'; '.join(rec.errors[:2])})"
        log(f"  [{i}/{len(sns)}] {sn}: 站位 {len(rec.stations)},组件 {len(rec.components)},状态 {st}")

    # Step 3: ReportPortal MC IMG(PR 图片)
    if not args.no_images:
        log("Step 3/5: 查询 MC IMG PR 图片 ...")
        from sn_report.lib.reportportal import ReportPortalClient

        portal = ReportPortalClient(mes, dl_dir)
        try:
            portal.open_portal("MC IMG UpLoadInfo")
            for i, rec in enumerate(records, start=1):
                log(f"  MCIMG [{i}/{len(records)}] {rec.sn} ...")
                portal.mc_img_query(
                    rec,
                    cfg.get("img_stations", []),
                    start,
                    end,
                    bool(cfg["report"].get("download_images", False)),
                )
                log(f"    图片 {len(rec.all_images())} 张")
        except Exception as exc:  # noqa: BLE001
            log(f"  MC IMG 查询失败(继续): {exc}")
    else:
        log("Step 3/5: 跳过 MC IMG(--no-images)")

    # Step 4: ACF 测试数据(sensorID / flexid)
    if not args.no_acf:
        log("Step 4/5: 查询 ACF 测试数据 ...")
        from sn_report.lib.reportportal import ReportPortalClient

        portal = ReportPortalClient(mes, dl_dir)
        try:
            for i, rec in enumerate(records, start=1):
                log(f"  ACF [{i}/{len(records)}] {rec.sn} ...")
                portal.acf_query(rec, cfg.get("acf_mc_types", []), start, end)
                log(f"    sensorID={rec.sensor_id or '-'} flexid={rec.flex_id or '-'}")
        except Exception as exc:  # noqa: BLE001
            log(f"  ACF 查询失败(继续): {exc}")
    else:
        log("Step 4/5: 跳过 ACF(--no-acf)")

    # Step 4.5: C4 批量接口(机台/载板/穴位)
    c4_cfg = cfg.get("c4", {})
    if args.c4 or c4_cfg.get("enabled"):
        log("Step 4.5/5: 调用战情中心 C4 批量接口 ...")
        from sn_report.lib.c4_client import C4Client

        if not c4_cfg.get("token"):
            log("  C4 token 为空,跳过(请先在 config.json 填入 c4.token)")
        else:
            try:
                client = C4Client(
                    url=c4_cfg.get("url", ""),
                    token=c4_cfg.get("token", ""),
                    plant_id=c4_cfg.get("plant_id", ""),
                    device=c4_cfg.get("device", ""),
                    type_=c4_cfg.get("type", "8S01"),
                    extra_params=c4_cfg.get("extra_params", {}),
                )
                client.apply_to_records(records, c4_cfg.get("columns", []))
                log("  C4 列已合并进站位记录")
            except Exception as exc:  # noqa: BLE001
                log(f"  C4 查询失败(继续): {exc}")
    else:
        log("Step 4.5/5: 跳过 C4(用 --c4 或在 config.json 启用)")

    # Step 5: 生成 PPT
    log("Step 5/5: 生成 PPT 报告 ...")
    out_path = Path(args.out) if args.out else out_dir / str(cfg["report"]["ppt_name"])
    if not out_path.is_absolute():
        out_path = PROJECT_DIR / out_path
    try:
        build_ppt(records, out_path, cfg)
        log(f"PPT 已生成: {out_path}")
    except Exception as exc:  # noqa: BLE001
        log(f"PPT 生成失败: {exc}")
        log("提示: 报告生成需要 python-pptx,Windows 上请先执行 install_windows_requirements.bat 或补充 lib/ 离线包")
        return 3

    # 中间结果落盘
    data_path = out_dir / "sn_records.json"
    data_path.write_text(
        json.dumps([r.to_dict() for r in records], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"中间结果已保存: {data_path}")
    save_log(out_dir / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

    fail_count = sum(1 for r in records if r.errors)
    log(f"完成: {len(records)} 个 SN,{fail_count} 个有告警(详见各 SN 页标题)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="SN 全制程追溯报告工具")
    parser.add_argument("--sns", help="SN 列表文件(txt/csv/xlsx)")
    parser.add_argument("--sn", help="单个 SN 快速查询")
    parser.add_argument("--out", help="PPT 输出路径")
    parser.add_argument("--discover", action="store_true", help="发现模式:dump 页面表格结构")
    parser.add_argument("--no-images", action="store_true", help="跳过 MC IMG 图片查询")
    parser.add_argument("--no-acf", action="store_true", help="跳过 ACF 测试数据查询")
    parser.add_argument("--c4", action="store_true", help="启用 C4 批量接口(机台/载板/穴位)")
    parser.add_argument("--init-config", action="store_true", help="生成默认配置后退出")
    args = parser.parse_args()

    ensure_windows_lib()
    if args.init_config:
        init_config()
        return 0
    try:
        return run(args)
    except FileNotFoundError as exc:
        log(f"错误: {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001
        log(f"未预期错误: {exc!r}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
