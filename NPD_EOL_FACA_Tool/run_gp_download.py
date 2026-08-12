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
import traceback

import pg8000.native


if getattr(sys, "frozen", False):
    # PyInstaller: exe 所在目录为根,输出/日志放 exe 旁边,避免写到 _internal
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
_LOG_LINES: List[str] = []


if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _dump_crash(exc_type, exc, tb) -> None:
    """全局异常处理:错误写入 exe 旁 crash.log,防止无提示闪退。"""
    try:
        msg = "".join(traceback.format_exception(exc_type, exc, tb))
        (BASE_DIR / "crash.log").write_text(msg, encoding="utf-8")
        print("\n[FATAL] 程序异常,详情见: " + str(BASE_DIR / "crash.log"))
        print(msg)
    except Exception:
        pass
    try:
        input("按回车键退出...")
    except Exception:
        pass


sys.excepthook = _dump_crash


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    _LOG_LINES.append(line)
    try:
        (BASE_DIR / "run_gp.log").write_text(
            "\n".join(_LOG_LINES) + "\n", encoding="utf-8"
        )
    except Exception:
        pass


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
        if "." in table:
            schema, tname = table.split(".", 1)
        else:
            schema, tname = "datacenterdev", table
        rows = self.q(
            "select column_name from information_schema.columns "
            f"where table_schema='{esc(schema)}' and table_name='{esc(tname)}' "
            "order by ordinal_position"
        )
        return [r[0] for r in rows]

    def list_projects(self) -> List[str]:
        """列出 datacenterdev 下所有专案(有 EOL 图片表的)。"""
        rows = self.q(
            "select tablename from pg_tables "
            "where schemaname='datacenterdev' and tablename like '%eolpicturedata' "
            "order by tablename"
        )
        projs = sorted({
            r[0].replace("t_", "").replace("_eolpicturedata", "")
            for r in rows
        })
        return projs

    def eol_by_sn(self, sn: str, project: str = "boi") -> Optional[Dict[str, Any]]:
        table = f"datacenterdev.t_{esc(project)}_eolpicturedata"
        rows = self.q(
            f"select * from {table} where sn='{esc(sn)}'"
        )
        if not rows:
            return None
        return dict(zip(self.columns(table), rows[0]))

    def fol_by_sensor(self, sensorid: str, project: str = "boi") -> Optional[Dict[str, Any]]:
        table = f"datacenterdev.t_{esc(project)}_folpicturedata"
        rows = self.q(
            f"select * from {table} "
            f"where sensorid='{esc(sensorid)}'"
        )
        if not rows:
            return None
        return dict(zip(self.columns(table), rows[0]))

    def resolve_project(self, sn: str) -> str:
        """SN 所属专案:先查图片表,再查 eoldata 测试表,默认 boi。"""
        for proj in self.list_projects():
            try:
                rec = self.eol_by_sn(sn, proj)
                if rec:
                    return proj
            except Exception:
                continue
        # 图片表没有,查 eoldata 定位专案(有测试数据但无图片)
        for proj in self.list_projects():
            try:
                rows = self.q(
                    f"select count(*) from datacenterdev.t_{esc(proj)}_eoldata "
                    f"where sn='{esc(sn)}'"
                )
                if rows and rows[0][0] > 0:
                    return proj
            except Exception:
                continue
        return "boi"

    def has_eol_pictures(self, sn: str, project: str) -> bool:
        """该专案图片表是否有此 SN 的图片记录。"""
        try:
            return self.eol_by_sn(sn, project) is not None
        except Exception:
            return False

    def has_eoldata(self, sn: str, project: str) -> bool:
        """该专案 eoldata 是否有此 SN 的测试/生产记录。"""
        try:
            rows = self.q(
                f"select count(*) from datacenterdev.t_{esc(project)}_eoldata "
                f"where sn='{esc(sn)}'"
            )
            return bool(rows and rows[0][0] > 0)
        except Exception:
            return False

    def match_projects(self, sn: str) -> Dict[str, Dict[str, Any]]:
        """列出 SN 在所有专案中的匹配情况。

        返回 {专案: {"pictures": bool(图片表有记录), "eoldata": bool(测试/生产表有记录)}}。
        """
        result: Dict[str, Dict[str, Any]] = {}
        for proj in self.list_projects():
            has_pic = self.has_eol_pictures(sn, proj)
            has_eol = self.has_eoldata(sn, proj)
            if has_pic or has_eol:
                result[proj] = {"pictures": has_pic, "eoldata": has_eol}
        return result


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
    "cma8.fs.local": "10.142.119.204",
    "dp2.fs.local": "10.143.17.70",
    # dp4.fs.local(Krios/P4)非本 BU 项目,不维护
}

# GP 专案(表前缀) -> SFC 门户专案 ID(失效链接走 SFC 补齐用)
GP_TO_SFC = {
    "boi": "APO006",
    "atw": "APQ012",    # ATW-N;ATW-E=APP003,可按需改 config
    "chs": "APN004",
    "chs26": "APO009",
}


def _load_gp_sfc_map() -> Dict[str, str]:
    """config.json -> c4.gp_sfc_map 可覆盖/扩展专案映射。"""
    m = dict(GP_TO_SFC)
    try:
        base = (Path(sys.executable).resolve().parent
                if getattr(sys, "frozen", False)
                else Path(__file__).resolve().parent)
        cfg = json.loads((base / "config.json").read_text(encoding="utf-8-sig"))
        m.update({str(k).lower(): str(v).upper()
                  for k, v in (cfg.get("c4", {}).get("gp_sfc_map", {}) or {}).items()})
    except Exception:  # noqa: BLE001
        pass
    return m


def try_download(url: str, dest: Path, timeout: int = 90) -> Tuple[bool, str]:
    """先试原 URL,域名解析失败则用代理 IP 替换重试;下载后验证图片有效性。"""
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
            # 验证是有效图片(Pillow 能识别);否则视为下载失败
            try:
                from PIL import Image as _PilImage
                with _PilImage.open(dest) as p:
                    p.verify()
            except Exception as exc:  # noqa: BLE001
                dest.unlink(missing_ok=True)
                last_err = f"非有效图片: {str(exc)[:50]}"
                continue
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


def download_with_sfc_fallback(img: Dict[str, Any], dest: Path,
                               key: str, sn_hint: str,
                               sfc_client: Optional[Any] = None,
                               sfc_cache: Optional[Dict[str, List[str]]] = None,
                               log: Optional[Any] = None,
                               timeout: int = 90) -> Tuple[bool, str]:
    """先直连原 URL;失败则走 SFC MC IMG 补齐,返回 (是否成功, 使用的 URL)。

    img 需含 station/column/url/uploadtime;key 为 SFC 查询条件
    (EOL 传 SN,FOL 传 sensorid);sn_hint 用于过滤非本 SN 的图。
    """
    orig_url = img.get("url") or ""
    ok, used = try_download(orig_url, dest, timeout=timeout)
    if ok:
        # 直连成功:保留原始 URL(与之前行为一致,链接列不变)
        return True, orig_url
    if sfc_client is None:
        return False, orig_url
    if log:
        log(f"    原链接失效 {img.get('station')}: {str(orig_url)[:70]}")
    try:
        from sfc_app007 import sfc_fallback_urls
        urls = sfc_fallback_urls(
            sfc_client,
            column=img.get("column", ""),
            station_label=img.get("station", ""),
            key=key, uploadtime=img.get("uploadtime", ""),
            sn_hint=sn_hint, url=orig_url,
            cache=sfc_cache)
    except Exception as exc:  # noqa: BLE001
        if log:
            log(f"    SFC 查询异常: {str(exc)[:80]}")
        return False, orig_url
    if not urls:
        if log:
            log(f"    SFC 无此站图片: {img.get('station')}")
        return False, orig_url
    for u in urls[:12]:
        ok2, used2 = try_download(u, dest, timeout=timeout)
        if ok2:
            if log:
                log(f"    SFC 补齐成功 {img.get('station')} <- {str(u)[:90]}")
            return True, u
    if log:
        log(f"    SFC 补齐失败(候选 {len(urls)} 个URL): {img.get('station')}")
    # 原链接失效但 SFC 有候选:链接列给候选 URL,方便浏览器打开原图
    return False, urls[0]


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
        if not p.exists():
            log(f"SN 文件不存在: {p}")
            log("请用 --sns 指定正确路径,或双击 exe 后直接输入 SN。")
            return 2
        sns = load_sn_list(p)
    else:
        sns_txt = BASE_DIR / "sns.txt"
        if sns_txt.exists():
            sns = load_sn_list(sns_txt)
        else:
            # 双击 exe 无参数:交互输入 SN
            try:
                raw = input("输入 Module SN(可多个,逗号分隔): ").strip()
            except EOFError:
                raw = ""
            sns = [s.strip() for s in raw.replace("，", ",").split(",") if s.strip()]
            if not sns:
                log("未输入 SN,退出。")
                return 0
    log(f"SN 数量: {len(sns)}")

    project = (args.project or "").strip().lower()
    if project in ("", "auto", "全部", "all"):
        project = ""
    if project:
        log(f"专案: {project}")
    else:
        log("专案: 自动识别(在全部专案中查找)")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = BASE_DIR / "output" / "gp_verify" / ts
    out_root.mkdir(parents=True, exist_ok=True)
    dl_root = Path(args.download_dir) if args.download_dir else BASE_DIR / "downloads" / ts

    verify: Dict[str, Any] = {"ts": ts, "sns": sns, "results": {}}
    for i, sn in enumerate(sns, start=1):
        log(f"[{i}/{len(sns)}] === SN: {sn} ===")
        per_sn: Dict[str, Any] = {"sn": sn, "eol": {}, "fol": {}, "total": 0,
                                   "downloaded": 0, "failed": 0}
        eol = None
        used_project = project
        if project:
            try:
                eol = gp.eol_by_sn(sn, project)
            except Exception as exc:  # noqa: BLE001
                log(f"  EOL 查询失败: {str(exc)[:100]}")
        else:
            # 自动:先图片表,再 eoldata 定位专案
            matches = gp.match_projects(sn)
            if matches:
                log(f"  匹配到 {len(matches)} 个专案:")
                for proj, info in sorted(matches.items()):
                    tag = []
                    if info["pictures"]:
                        tag.append("有图片")
                    if info["eoldata"]:
                        tag.append("有测试/生产数据")
                    log(f"    {proj.upper():8s} {'+'.join(tag)}")
            for proj in gp.list_projects():
                try:
                    eol = gp.eol_by_sn(sn, proj)
                    if eol:
                        used_project = proj
                        break
                except Exception:
                    continue
            if eol:
                log(f"  专案识别: {used_project}")
            else:
                # 图片表都没有:查 eoldata 看是否有测试数据
                for proj in gp.list_projects():
                    if gp.has_eoldata(sn, proj):
                        log(f"  该 SN 属于 {proj} 专案,但有测试数据无图片记录")
                        break
        # SFC 兜底(失效链接补齐):按专案懒加载客户端,一次登录复用于本 SN
        sfc_client = None
        sfc_cache: Dict[str, List[str]] = {}
        if getattr(args, "sfc_enabled", False) and getattr(args, "sfc_user", ""):
            sfc_project = (getattr(args, "sfc_project", "") or "").upper()
            if not sfc_project and used_project:
                sfc_project = _load_gp_sfc_map().get(used_project.lower(), "")
            if sfc_project:
                try:
                    from sfc_app007 import SfcPortal
                    sfc_client = SfcPortal(
                        args.sfc_user, args.sfc_password, project=sfc_project)
                    if not sfc_client.login():
                        log(f"  SFC 登录失败({sfc_project}),跳过 SFC 补齐")
                        sfc_client = None
                    else:
                        log(f"  SFC 就绪: {sfc_project}(失效链接将自动补齐)")
                except Exception as exc:  # noqa: BLE001
                    log(f"  SFC 初始化失败: {str(exc)[:90]}")
                    sfc_client = None
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
                    ok, used_url = download_with_sfc_fallback(
                        img, dest, key=sn, sn_hint=sn,
                        sfc_client=sfc_client, sfc_cache=sfc_cache, log=log,
                        timeout=args.timeout)
                    img["url"] = used_url
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
                    fol = gp.fol_by_sensor(sensor, used_project)
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
                            ok, used_url = download_with_sfc_fallback(
                                img, dest, key=sensor, sn_hint=sensor,
                                sfc_client=sfc_client, sfc_cache=sfc_cache,
                                log=log, timeout=args.timeout)
                            img["url"] = used_url
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
    parser.add_argument("--project", default="",
                        help="专案(如 boi/akc/chs);留空自动识别全部专案")
    parser.add_argument("--download-dir", default="")
    parser.add_argument("--timeout", type=int, default=90,
                        help="单张图片下载超时秒数(默认 90)")
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--sfc-user", default="",
                        help="SFC 登录账号(失效链接补齐用,如 F1679837)")
    parser.add_argument("--sfc-password", default="",
                        help="SFC 登录密码")
    parser.add_argument("--sfc-project", default="",
                        help="SFC 专案 ID(如 APO006);留空按专案映射自动取")
    parser.add_argument("--no-sfc", action="store_true",
                        help="关闭 SFC 失效链接补齐")
    args = parser.parse_args()
    args.sfc_enabled = not args.no_sfc
    try:
        code = run(args)
    except Exception as exc:  # noqa: BLE001
        log(f"未预期错误: {exc!r}")
        try:
            (BASE_DIR / "crash.log").write_text(
                traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        code = 1
    try:
        input("按回车键退出...")
    except Exception:
        pass
    return code


if __name__ == "__main__":
    sys.exit(main())
