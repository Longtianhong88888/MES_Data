#!/usr/bin/env python3
"""Oracle 直连一键下载:输入 Module SN,追溯各站 key,按 T_DOWNIMGSET 表映射
查询全部站位图片并下载,同时生成验证记录(供台式机跑完拿回来分析)。

用法(台式机,内网):
    python run_oracle_download.py --sns sns.txt
    python run_oracle_download.py --sn DNMHTV000F50000Y2N+2001+Q
    python run_oracle_download.py --sns sns.txt --download-dir D:\\imgs --no-download

输出:
    output/oracle_verify/<时间戳>/verify.json   每 SN × 每站查询/下载明细
    output/oracle_verify/<时间戳>/run.log       运行日志
    downloads/<sn>/<station>/...                下载的图片
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from lib.config import load_sn_list  # noqa: E402
from lib.oracle_client import C4Oracle, load_conns_from_decrypted_json  # noqa: E402


# ---------- 工具 ----------
def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    _LOG_LINES.append(line)


_LOG_LINES: List[str] = []


def norm_sn(value: Any) -> str:
    return str(value or "").strip()


def norm_pocket(value: Any) -> str:
    """穴位归一化:2_3 -> 0203;3 -> 0300(与 C4/文件名规则一致)。"""
    v = str(value or "").strip()
    if not v:
        return ""
    if "_" in v:
        parts = v.split("_")
        return "".join(p.zfill(2) for p in parts[:2])
    if v.isdigit():
        return v.zfill(4)
    return v


# ---------- 追溯 ----------
TRACE_SQL = [
    # key, sql, 列
    (
        "lot",
        "select lotno from EQLASERMARKINGBAK where sn=:1 and rownum<=1",
        ["lotno"],
    ),
    (
        "sensor_id",
        "select senserid from SNBINDSENSERIDBAK where sn=:1 and rownum<=1",
        ["senserid"],
    ),
    (
        "vcm_id",
        "select vcmid from TESTFOLAAIMAGEBAK a "
        "inner join TESTSNCURRENTBAK c on a.sn=c.att2 "
        "where c.sn=:1 and rownum<=1",
        ["vcmid"],
    ),
    (
        "var_sn",
        "select var_sn from TESTFOLAAIMAGEBAK a "
        "inner join TESTSNCURRENTBAK c on a.sn=c.att2 "
        "where c.sn=:1 and rownum<=1",
        ["var_sn"],
    ),
    (
        "carrier",
        "select carrierkey, carrierid, carrier_col, carrier_row from FOLSENSERIDINFOBAK "
        "where sn in (select att2 from TESTSNCURRENTBAK where sn=:1) and rownum<=1",
        ["carrierkey", "carrierid", "carrier_col", "carrier_row"],
    ),
]


def trace_sn(client: C4Oracle, data_conn: str, sn: str) -> Dict[str, Any]:
    """一次 SN 追溯,返回所有 key。"""
    keys: Dict[str, Any] = {"sn": sn}
    for key, sql, cols in TRACE_SQL:
        try:
            rows = client.query(data_conn, sql, [sn])
            if rows:
                for col, val in zip(cols, rows[0]):
                    keys[col] = val
                keys[key] = rows[0][0]
        except Exception as exc:  # noqa: BLE001
            log(f"  追溯 {key} 失败: {str(exc)[:80]}")
    if keys.get("carrier_col") is not None and keys.get("carrier_row") is not None:
        keys["carrier_xy"] = (
            f"{keys['carrier_col']}_{keys['carrier_row']}"
        )
    return keys


# ---------- 图片表查询 ----------
_TABLE_COLS_CACHE: Dict[str, List[str]] = {}


def get_table_columns(client: C4Oracle, data_conn: str, table: str) -> List[str]:
    """读取表列名(带缓存)。"""
    if table in _TABLE_COLS_CACHE:
        return _TABLE_COLS_CACHE[table]
    try:
        with client.connect(data_conn) as conn:
            cur = conn.cursor()
            cur.execute(f"select * from {table} where 1=0")
            cols = [d[0] for d in cur.description]
    except Exception:
        cols = []
    _TABLE_COLS_CACHE[table] = cols
    return cols


def query_station_images(client: C4Oracle, data_conn: str, table: str, keys: Dict[str, Any],
                         limit: int = 200, time_range: Optional[Tuple[str, str]] = None,
                         ) -> List[Dict[str, Any]]:
    """自适应列名查询一张图片表。

    优先级:SN > VCMID > CARRIERKEY(+SUBSTRATE XY) > LOTNO > SENSERID。
    返回统一字段(ftppath/url/localpath/filename/carrierxy...)。
    """
    cols = get_table_columns(client, data_conn, table)
    if not cols:
        log(f"  {table} 表不存在或不可读")
        return []
    colset = {c.upper() for c in cols}

    def has(*names: str) -> bool:
        return any(n in colset for n in names)

    sel = [
        c for c in cols
        if c.upper() in {
            "FILETYPE", "LOTNO", "SN", "CARRIERID", "CARRIERXY", "FILENUMBER",
            "FILETIME", "FILESIZE", "LOCALPATH", "FTPPATH", "FTPIP", "UPLOADTIME",
            "MACHINENO", "FILENAME", "CARRIERX", "CARRIERY", "RESULT", "CARRIERKEY",
            "URL", "TYPENO", "SUBSTARTECOL", "SUBSTARTEROW", "VCMID", "SENSERID",
        }
    ]
    if not sel:
        sel = cols[:18]
    sel_sql = ", ".join(sel)

    conds: List[Tuple[str, str]] = []
    if has("SN") and keys.get("sn"):
        conds.append(("SN", str(keys["sn"])))
    elif has("VCMID") and keys.get("vcm_id"):
        conds.append(("VCMID", str(keys["vcm_id"])))
    elif has("CARRIERKEY") and keys.get("carrierkey"):
        conds.append(("CARRIERKEY", str(keys["carrierkey"])))
    elif has("LOTNO") and keys.get("lot"):
        conds.append(("LOTNO", str(keys["lot"])))
    elif has("SENSERID") and keys.get("sensor_id"):
        conds.append(("SENSERID", str(keys["sensor_id"])))
    if not conds:
        return []

    col, val = conds[0]
    where = f"{col}=:1"
    params: List[Any] = [val]
    if time_range and has("UPLOADTIME") and (time_range[0] or time_range[1]):
        if time_range[0]:
            where += " and UPLOADTIME>=to_date(:2,'YYYY-MM-DD HH24:MI')"
            params.append(time_range[0])
        if time_range[1]:
            where += f" and UPLOADTIME<=to_date(:{len(params)+1},'YYYY-MM-DD HH24:MI')"
            params.append(time_range[1])
    params.append(limit)
    where += f" and rownum<=:{len(params)}"
    sql = f"select {sel_sql} from {table} where {where}"
    try:
        rows = client.query(data_conn, sql, params)
    except Exception as exc:  # noqa: BLE001
        # 某些表列大小写/命名不同,退回宽松查询
        try:
            rows = client.query(
                f"select * from {table} where rownum<=:1", [limit]
            )
            cols2 = [d[0] for d in _describe(client, data_conn, table)]
        except Exception as exc2:  # noqa: BLE001
            log(f"  {table} 查询失败: {str(exc2)[:100]}")
            return []
        return [_row_to_dict(r, cols2) for r in rows]

    out = []
    for r in rows:
        d = {k.lower(): v for k, v in zip(sel, r)}
        d["pocket"] = norm_pocket(d.get("carrierxy"))
        out.append(d)
    return out


def _describe(client: C4Oracle, data_conn: str, table: str):
    with client.connect(data_conn) as conn:
        cur = conn.cursor()
        cur.execute(f"select * from {table} where 1=0")
        return cur.description


def _row_to_dict(row: tuple, desc) -> Dict[str, Any]:
    return {d[0]: v for d, v in zip(desc, row)}


# ---------- 下载 ----------
def download_url(url: str, dest: Path, timeout: int = 60) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        dest.write_bytes(data)
        return True
    except Exception as exc:  # noqa: BLE001
        log(f"  下载失败 {url[:90]}... -> {str(exc)[:80]}")
        return False


def build_download_urls(rec: Dict[str, Any]) -> List[Tuple[str, str]]:
    """从一条图片记录生成可下载 URL 列表 (url, kind)。"""
    urls: List[Tuple[str, str]] = []
    ftp = str(rec.get("ftppath") or "").strip()
    if ftp and ftp != "None" and ftp.startswith("http"):
        urls.append((ftp, "ftppath"))
    url = str(rec.get("url") or "").strip()
    if url and url != "None" and url.startswith("http"):
        urls.append((url, "url"))
    local = str(rec.get("localpath") or "").strip()
    if local and local not in ("None", "-") and ":" in local:
        # LOCALPATH 是上传机本地盘符,台式机不可达;仅记录,不下载
        pass
    return urls


def station_file_prefix(station: str, rec: Dict[str, Any]) -> str:
    return f"{station}_{rec.get('sn') or rec.get('lotno') or 'na'}"


# ---------- 主流程 ----------
def run(args: argparse.Namespace) -> int:
    # 登录验证:Rayprush 一账通通过后才允许继续
    if not args.no_login:
        if not _try_auto_login() and not args.login:
            log("未检测到可用账号,弹出登录验证 ...")
        if args.login or not _verified:
            if not _require_login():
                log("未通过一账通验证,退出。")
                return 0
        log("一账通验证通过,继续。")

    cfg_path = BASE_DIR / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig")) if cfg_path.exists() else {}
    oracle_cfg = cfg.get("oracle", {})

    conns_file = args.conns or oracle_cfg.get(
        "conns_file",
        str(BASE_DIR / "conns.json"),
    )
    if not Path(conns_file).exists():
        log(f"解密连接文件不存在: {conns_file}")
        return 2

    init_client = args.instant_client or oracle_cfg.get("instant_client", "")
    client = C4Oracle(
        conns=load_conns_from_decrypted_json(conns_file),
        init_client=init_client,
    )
    cfg_conn = args.cfg_conn or oracle_cfg.get("cfg_conn", "MESSETCONN")
    data_conn = args.data_conn or oracle_cfg.get("data_conn", "APO006CONN")

    log(f"连接: 配置库={cfg_conn} 数据库={data_conn}")

    # 站点表映射
    try:
        stations = client.load_station_tables(cfg_conn)
        log(f"加载 T_DOWNIMGSET: {len(stations)} 站")
    except Exception as exc:  # noqa: BLE001
        log(f"加载站位映射失败: {exc}")
        return 1

    # SN 列表
    if args.sn:
        sns = [args.sn]
    elif args.sns:
        p = Path(args.sns)
        if not p.is_absolute():
            p = BASE_DIR / p
        sns = load_sn_list(p)
    else:
        sns = load_sn_list(BASE_DIR / "sns.txt")
    if not sns:
        log("SN 列表为空")
        return 2
    log(f"SN 数量: {len(sns)}")

    # 时间窗(可选,加速大表查询)
    win = cfg.get("analysis_window", {})
    time_range: Optional[Tuple[str, str]] = (
        (str(win.get("start", "")).strip() or None,
         str(win.get("end", "")).strip() or None)
    ) if win else None

    # 输出目录
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = BASE_DIR / "output" / "oracle_verify" / ts
    out_root.mkdir(parents=True, exist_ok=True)
    dl_root = Path(args.download_dir) if args.download_dir else (
        BASE_DIR / "downloads" / ts
    )

    verify: Dict[str, Any] = {
        "ts": ts,
        "data_conn": data_conn,
        "cfg_conn": cfg_conn,
        "sns": sns,
        "results": {},
    }

    for i, sn in enumerate(sns, start=1):
        log(f"[{i}/{len(sns)}] === SN: {sn} ===")
        keys = trace_sn(client, data_conn, sn)
        log(f"  追溯 keys: { {k: v for k, v in keys.items() if v not in (None, '')} }")
        per_sn: Dict[str, Any] = {
            "sn": sn,
            "keys": {k: str(v) for k, v in keys.items() if v not in (None, "")},
            "stations": {},
            "total_images": 0,
            "downloaded": 0,
            "failed": 0,
        }
        for st in stations:
            station_id = st["station"]
            table = st["table"]
            imgs = query_station_images(client, data_conn, table, keys,
                                        time_range=time_range)
            per_st: Dict[str, Any] = {
                "table": table,
                "filetypes": st["filetype"],
                "columns": st["columns"],
                "images": [],
                "count": len(imgs),
                "downloaded": 0,
                "failed": 0,
            }
            for rec in imgs:
                item: Dict[str, Any] = {
                    "filename": rec.get("filename"),
                    "filetype": rec.get("filetype"),
                    "lotno": rec.get("lotno"),
                    "carrierid": rec.get("carrierid"),
                    "carrierxy": rec.get("carrierxy"),
                    "pocket": rec.get("pocket"),
                    "machineno": rec.get("machineno"),
                    "uploadtime": str(rec.get("uploadtime")),
                    "localpath": rec.get("localpath"),
                    "ftppath": rec.get("ftppath"),
                    "downloaded": False,
                    "dest": "",
                    "error": "",
                }
                if not args.no_download:
                    for url, kind in build_download_urls(rec):
                        fname = rec.get("filename") or url.rsplit("/", 1)[-1].split("?")[0]
                        if not fname:
                            fname = f"{station_id}_{len(per_st['images']):03d}.zip"
                        dest = dl_root / sn / station_id / fname
                        ok = download_url(url, dest)
                        item["downloaded"] = ok
                        item["dest"] = str(dest)
                        item["kind"] = kind
                        if ok:
                            per_st["downloaded"] += 1
                            per_sn["downloaded"] += 1
                        else:
                            per_st["failed"] += 1
                            per_sn["failed"] += 1
                        break
                per_st["images"].append(item)
            per_sn["stations"][station_id] = per_st
            per_sn["total_images"] += len(imgs)
            log(
                f"  {station_id:10s} {table:30s} 图片 {len(imgs):3d} "
                f"下载 {per_st['downloaded']}/{len(imgs)}"
            )
        verify["results"][sn] = per_sn
        time.sleep(0.5)

    # 落盘验证记录
    (out_root / "verify.json").write_text(
        json.dumps(verify, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_root / "run.log").write_text("\n".join(_LOG_LINES) + "\n", encoding="utf-8")
    log(f"验证记录已保存: {out_root}")
    log(f"图片目录: {dl_root}")

    total = sum(v["total_images"] for v in verify["results"].values())
    dl = sum(v["downloaded"] for v in verify["results"].values())
    log(f"汇总: {len(sns)} 个 SN,图片 {total} 张,下载成功 {dl} 张")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Oracle 直连一键下载(BUF/Cali 全部站位照片)")
    parser.add_argument("--sn", help="单个 Module SN")
    parser.add_argument("--sns", help="SN 列表文件")
    parser.add_argument("--conns", help="解密连接 JSON 路径")
    parser.add_argument("--cfg-conn", default="MESSETCONN", help="配置库连接名")
    parser.add_argument("--data-conn", default="APO006CONN", help="数据/机种库连接名")
    parser.add_argument("--instant-client", default="", help="Oracle Instant Client 目录(thick)")
    parser.add_argument("--download-dir", default="", help="图片下载根目录")
    parser.add_argument("--no-download", action="store_true", help="只查询不下载")
    parser.add_argument("--login", action="store_true",
                        help="弹出 Rayprush 一账通登录验证(通过后继续)")
    parser.add_argument("--no-login", action="store_true",
                        help="跳过登录验证(仅限自动化/测试)")
    args = parser.parse_args()
    try:
        return run(args)
    except Exception as exc:  # noqa: BLE001
        log(f"未预期错误: {exc!r}")
        return 1


if __name__ == "__main__":
    sys.exit(main())


_verified = False


def _root_config() -> Optional[Dict[str, Any]]:
    """向上查找项目根 config.json。"""
    import json as _json

    cur = Path(__file__).resolve().parent
    root = None
    for _ in range(4):
        cand = cur / "config.json"
        if cand.exists():
            root = cand
            break
        cur = cur.parent
    if root is None:
        return False
    try:
        cfg = _json.loads(root.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return cfg


def _try_auto_login() -> bool:
    """用根配置保存的账号自动验证;成功返回 True。"""
    global _verified
    cfg = _root_config()
    if not cfg or not cfg.get("username") or not cfg.get("password"):
        return False
    try:
        from lib.rayprush_auth import RayprushAuth

        auth = RayprushAuth(login_url=cfg.get("login_url"))
        ok, msg = auth.login(cfg.get("username", ""), cfg.get("password", ""))
        if ok:
            _verified = True
            log("自动验证通过(使用已保存账号)。")
            return True
        log(f"自动验证失败: {msg}")
    except Exception as exc:  # noqa: BLE001
        log(f"自动验证异常: {exc}")
    return False


def _require_login() -> bool:
    """弹出登录窗口,返回是否验证通过。"""
    global _verified
    try:
        from PyQt5.QtWidgets import QApplication
    except ImportError:
        log("登录验证需要 PyQt5,请先安装(打包 exe 已内置)。")
        return False

    from lib.login_dialog import LoginDialog

    app = QApplication.instance() or QApplication([])
    dlg = LoginDialog()
    if dlg.exec_() == LoginDialog.Accepted:
        _verified = True
        return True
    return False
