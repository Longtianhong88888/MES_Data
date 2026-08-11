#!/usr/bin/env python3
"""Greenplum 直连一键下载(C4 Serin 数据源,替代 Oracle cma6db)。

原理(逆向自 CimTool.exe DownSerinData/Get_Serin_data):
- C4 的 Serin 追溯/照片数据实际在 Greenplum wwwgpdw(10.151.130.202:5432)
- 表:datacenterdev.t_boi_eolpicturedata(按 SN 查,EOL 站照片)
      datacenterdev.t_boi_folpicturedata(按 sensorid 查,FOL 站照片)
- 每行一个 SN,列名 = {站位}_{类型}_path + _uploadtime,非空即该站有照片

用法:
    python run_gp_download.py --sn DNMHTV000F50000Y2N+2001+Q
    python run_gp_download.py --sns sns.txt
输出: output/gp_verify/<时间戳>/verify.json + downloads/<sn>/...
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pg8000.native


if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


BASE_DIR = Path(__file__).resolve().parent
_LOG_LINES: List[str] = []


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    _LOG_LINES.append(line)


def esc(value: str) -> str:
    """SQL 字符串转义(内部 SN,简单清洗)。"""
    return str(value).replace("'", "''")


def load_sn_list(path: Path) -> List[str]:
    sns = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            sns.append(line)
    seen, out = set(), []
    for s in sns:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


class GreenplumSerin:
    def __init__(self, host: str = "10.151.130.202", port: int = 5432,
                 database: str = "wwwgpdw", user: str = "gpdwdev",
                 password: str = "Altus2014", timeout: int = 15):
        self.host, self.port = host, port
        self.database, self.user = database, user
        self.password, self.timeout = password, timeout
        self._conn: Optional[pg8000.native.Connection] = None

    def connect(self):
        if self._conn is None:
            self._conn = pg8000.native.Connection(
                user=self.user, password=self.password,
                host=self.host, port=self.port,
                database=self.database, timeout=self.timeout,
            )
        return self._conn

    def q(self, sql: str) -> List[Any]:
        return self.connect().run(sql)

    def columns(self, table: str) -> List[str]:
        rows = self.q(
            "select column_name from information_schema.columns "
            f"where table_schema='datacenterdev' and table_name='{esc(table)}' "
            "order by ordinal_position"
        )
        return [r[0] for r in rows]

    def eol_by_sn(self, sn: str) -> Optional[Dict[str, Any]]:
        rows = self.q(
            f"select * from datacenterdev.t_boi_eolpicturedata where sn='{esc(sn)}'"
        )
        if not rows:
            return None
        return dict(zip(self.columns("t_boi_eolpicturedata"), rows[0]))

    def fol_by_sensor(self, sensorid: str) -> Optional[Dict[str, Any]]:
        rows = self.q(
            f"select * from datacenterdev.t_boi_folpicturedata "
            f"where sensorid='{esc(sensorid)}'"
        )
        if not rows:
            return None
        return dict(zip(self.columns("t_boi_folpicturedata"), rows[0]))

    def sensor_by_sn(self, sn: str) -> Optional[str]:
        """从 EOL 行取 sensorid(也尝试从 SN 前缀表反查)。"""
        rec = self.eol_by_sn(sn)
        if rec and rec.get("sensorid"):
            return str(rec["sensorid"])
        return None


STATION_KEYWORDS = [
    ("CA", "cover attach"), ("FC", "flex"), ("UF", "underfill"),
    ("UFA", "uf ai"), ("SSA", "ssa"), ("PP", "particle"), ("GA", "ga"),
    ("DT", "dt"), ("VCMPNP", "vcm pnp"), ("VA", "va"), ("TA", "ta"),
    ("VS", "vs"), ("JSTS", "js"), ("EA", "ea"), ("TD", "td"),
    ("IRPP", "irpp"), ("AA", "aa"), ("SF", "sf"), ("HFS", "hfs"),
    ("LM", "laser mark"), ("CUDT", "cube"), ("CAPS", "caps"),
    ("ACFFLIP", "acf flip"), ("ACFL", "acf load"), ("ACFU", "acf unload"),
    ("ACF", "acf"), ("TOPPDI", "top pdi"), ("TOPFR", "top fr"),
    ("BOTTOMFR", "bottom fr"), ("BOTTOMPDI", "bottom pdi"),
    ("MODULEFORD", "module ford"), ("MUDT", "module up"), ("MAPS", "aps"),
    ("AVI", "avi"), ("ACA", "aca"), ("CAW", "caw"), ("CF", "cf"),
]

# 图片域名 -> S3 代理 IP(来自 T_FTPSETITEM.PROXYADDRESS,VM/台式机可直连)
DOMAIN_IP_MAP = {
    "cma1.fs.com": "10.142.117.100",
    "cma2.fs.com": "10.142.118.200",
    "cma3.fs.local": "10.142.118.210",
    "cma5.fs.local": "10.142.119.201",
    "cma6.fs.local": "10.142.119.202",
    "cma7.fs.local": "10.142.119.203",
}


def try_download(url: str, dest: Path, timeout: int = 90) -> Tuple[bool, str]:
    """先试原 URL,域名解析失败则用代理 IP 替换重试。"""
    candidates = [url]
    for dom, ip in DOMAIN_IP_MAP.items():
        if dom in url:
            candidates.append(url.replace(dom, ip))
            break
    last_err = ""
    for u in candidates:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return True, u
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
    return False, last_err


def extract_images(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 Serin 宽表行提取所有照片 URL。"""
    imgs = []
    seen = set()
    for key, val in rec.items():
        if not key.endswith("_path"):
            continue
        if val in (None, ""):
            continue
        station = key[:-5]
        # 推断站位简称
        label = station
        upper = station.upper()
        for abbr, _ in STATION_KEYWORDS:
            if upper.startswith(abbr) or abbr in upper:
                label = abbr
                break
        url = str(val)
        # 归一化 URL:ftp//xxx -> ftp://xxx; 去掉尾部 ?
        if url.startswith("ftp//"):
            url = "ftp://" + url[5:]
        item = {
            "station": label,
            "column": key,
            "url": url,
            "uploadtime": str(rec.get(station + "_uploadtime") or ""),
        }
        dedup = f"{label}|{url}"
        if dedup not in seen:
            seen.add(dedup)
            imgs.append(item)
    return imgs


def download(url: str, dest: Path, timeout: int = 90) -> bool:
    ok, used = try_download(url, dest, timeout)
    if ok:
        return True
    log(f"    下载失败 {url[:80]} -> {used[:60]}")
    return False


def run(args: argparse.Namespace) -> int:
    log(f"脚本目录: {BASE_DIR}")
    try:
        import pg8000  # noqa: F401
    except ImportError:
        log("缺少 pg8000,请先安装依赖:")
        log("  python\\python.exe -m pip install --no-index --find-links=wheels -r requirements.txt")
        return 2
    gp = GreenplumSerin(
        host=args.host, port=args.port, database=args.database,
        user=args.user, password=args.password,
    )
    try:
        gp.connect()
        log(f"Greenplum 连接成功: {args.host}:{args.port}/{args.database}")
    except Exception as exc:  # noqa: BLE001
        log(f"Greenplum 连接失败: {exc}")
        return 1

    if args.sn:
        sns = [args.sn]
    elif args.sns:
        p = Path(args.sns)
        if not p.is_absolute():
            p = BASE_DIR / p
        sns = load_sn_list(p)
    else:
        sns = load_sn_list(BASE_DIR / "sns.txt")
    log(f"SN 数量: {len(sns)}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = BASE_DIR / "output" / "gp_verify" / ts
    out_root.mkdir(parents=True, exist_ok=True)
    dl_root = Path(args.download_dir) if args.download_dir else BASE_DIR / "downloads" / ts

    verify: Dict[str, Any] = {"ts": ts, "sns": sns, "results": {}}
    for i, sn in enumerate(sns, start=1):
        log(f"[{i}/{len(sns)}] === SN: {sn} ===")
        per_sn: Dict[str, Any] = {"sn": sn, "eol": {}, "fol": {}, "total": 0,
                                   "downloaded": 0, "failed": 0}
        try:
            eol = gp.eol_by_sn(sn)
        except Exception as exc:  # noqa: BLE001
            log(f"  EOL 查询失败: {str(exc)[:100]}")
            eol = None
        if eol:
            imgs = extract_images(eol)
            log(f"  EOL 照片: {len(imgs)} 张")
            per_sn["eol"]["sensorid"] = str(eol.get("sensorid") or "")
            per_sn["eol"]["lotno"] = str(eol.get("eol_lotno") or "")
            for img in imgs:
                item = dict(img)
                if not args.no_download:
                    fname = f"{img['station']}_{i}_{len(per_sn['eol'])}.jpg"
                    dest = dl_root / sn / "EOL" / fname
                    ok = download(img["url"], dest)
                    item["downloaded"] = ok
                    item["dest"] = str(dest)
                    if ok:
                        per_sn["downloaded"] += 1
                    else:
                        per_sn["failed"] += 1
                per_sn["eol"].setdefault("images", []).append(item)
            per_sn["total"] += len(imgs)

            sensor = str(eol.get("sensorid") or "")
            if sensor:
                try:
                    fol = gp.fol_by_sensor(sensor)
                except Exception as exc:  # noqa: BLE001
                    fol = None
                    log(f"  FOL 查询失败: {str(exc)[:100]}")
                if fol:
                    imgs = extract_images(fol)
                    log(f"  FOL 照片: {len(imgs)} 张 (sensorid={sensor})")
                    per_sn["fol"]["sensorid"] = sensor
                    per_sn["fol"]["lotno"] = str(fol.get("fol_lotno") or "")
                    per_sn["fol"]["carrierkey"] = str(fol.get("fol_carrierkey") or "")
                    for img in imgs:
                        item = dict(img)
                        if not args.no_download:
                            fname = f"{img['station']}_{len(per_sn['fol'])}.jpg"
                            dest = dl_root / sn / "FOL" / fname
                            ok = download(img["url"], dest)
                            item["downloaded"] = ok
                            item["dest"] = str(dest)
                            if ok:
                                per_sn["downloaded"] += 1
                            else:
                                per_sn["failed"] += 1
                        per_sn["fol"].setdefault("images", []).append(item)
                    per_sn["total"] += len(imgs)
        else:
            log(f"  EOL 无数据(SN 不存在或非 BOI 机种)")
        verify["results"][sn] = per_sn
        time.sleep(0.2)

    (out_root / "verify.json").write_text(
        json.dumps(verify, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_root / "run.log").write_text("\n".join(_LOG_LINES) + "\n", encoding="utf-8")
    total = sum(v["total"] for v in verify["results"].values())
    dl = sum(v["downloaded"] for v in verify["results"].values())
    log(f"完成: {len(sns)} SN,照片 {total} 张,下载 {dl} 张")
    log(f"验证记录: {out_root}")
    log(f"图片目录: {dl_root}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Greenplum Serin 照片一键下载(BOI)")
    parser.add_argument("--sn", help="单个 Module SN")
    parser.add_argument("--sns", help="SN 列表文件")
    parser.add_argument("--host", default="10.151.130.202")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--database", default="wwwgpdw")
    parser.add_argument("--user", default="gpdwdev")
    parser.add_argument("--password", default="Altus2014")
    parser.add_argument("--download-dir", default="")
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()
    try:
        return run(args)
    except Exception as exc:  # noqa: BLE001
        log(f"未预期错误: {exc!r}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
