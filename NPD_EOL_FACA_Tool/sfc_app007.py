#!/usr/bin/env python3
"""SFC 门户多专案 照片/追溯一键查询(2026-08-12 打通)。

链路(已实测):
1. SFC 登录(10.151.128.45:8081,一账通 F1679837)
2. ReportPortal SN Track(10.151.130.120:8091,classname=SNTrackInformation_MW)
   -> Serin 全制程追溯数据(SN/Sensor/VCMID/OISID/Lensid/批号/Tray 等 68 列)
3. ReportPortal MC IMG(classname=SMTAOIRepor,ODSAPP007CONN)
   -> 74 个站位按 key 级联查询(SN -> lotno -> Sensor-as-SN)收集图片链接
   -> 每站另存 IMG Info Excel 导出(全量元数据,可达)

图片文件在 10.142.119.201/202(台式机内网),本脚本只产出清单/元数据。

用法:
    python sfc_app007.py --project APP007 --sn DNMHVC003EB0001G7W+5001+8
    python sfc_app007.py --project Cali --sn <Cali SN>
    python sfc_app007.py --project ATW-N --sn ... --exports serin,mcimg,excel,download
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

requests.packages.urllib3.disable_warnings()

SFC = "http://10.151.128.45:8081"
RP = "http://10.151.130.120:8091"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
PLANT = "8S01"

MCIMG_CLASS = "MESReportTeamplate.TestReport.SMTAOIRepor"


def _norm_key(s: Any) -> str:
    """归一化:只留小写字母数字。"""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _split_tokens(s: Any) -> List[str]:
    """按非字母数字切分原始串,返回归一化 token(>=2 字符)。"""
    out = []
    for part in re.split(r"[^a-zA-Z0-9]+", str(s or "")):
        t = _norm_key(part)
        if len(t) >= 2:
            out.append(t)
    return out


def _leading_alpha(s: Any) -> str:
    """取一串字符开头的连续字母(如 CUDT6201Q -> cudt)。"""
    m = re.match(r"[a-z]+", _norm_key(s))
    return m.group(0) if m else ""


# GP 列名别名 -> SFC 站位关键字(方向/叫法差异),提升匹配覆盖
STATION_TOKEN_ALIASES = {
    "topfr": ("frtop",),
    "bottomfr": ("frbottom",),
    "toppdi": ("frtopaoi", "ppdi"),
    "bottompdi": ("frbottomaoi", "ppdi"),
}


def _score_tok(sn: str, tok: str) -> int:
    """SFC 站位 id 与 GP token 的匹配得分。"""
    if not tok:
        return 0
    if sn.startswith(tok) or tok.startswith(sn):
        return min(len(sn), len(tok)) + 2
    if tok in sn:
        return max(3, len(tok))
    return 0


def sfc_station_candidates(sfc_ids: List[str], column: str = "",
                           station_label: str = "", url: str = "") -> List[str]:
    """根据 GP 图片列名/站位标签/原 URL 找 SFC MC IMG 站位候选(按得分排序)。

    - column: GP 表列名(如 cudt_ppr1_path)
    - station_label: extract_images 的简写(如 CA)
    - url: 失效的原图 URL(用于从路径取站点段,如 CUDT6201Q)
    返回按匹配度降序的 SFC 站位 ID;无匹配返回空。
    """
    toks: List[str] = []
    for tok in _split_tokens(column):
        toks.append(tok)
        for alias in STATION_TOKEN_ALIASES.get(tok, ()):
            toks.append(alias)
    m = re.search(r"/([A-Za-z0-9]{2,20})/\d{8}/", str(url or ""))
    if m:
        lead = _leading_alpha(m.group(1))
        if len(lead) >= 2:
            toks.append(lead)
    label = _norm_key(station_label)
    if not toks:
        return []
    scored: List[Tuple[int, str]] = []
    for sid in sfc_ids:
        sn = _norm_key(sid)
        if not sn:
            continue
        best = 0
        for tok in toks:
            best = max(best, _score_tok(sn, tok))
        if best >= 2:
            scored.append((best, sid))
    # 列名/URL 无匹配时,才允许用站位标签兜底(排除 2 字符泛化标签)
    if not scored and label and len(label) >= 3:
        for sid in sfc_ids:
            sn = _norm_key(sid)
            s2 = _score_tok(sn, label)
            if s2 >= 3:
                scored.append((s2, sid))
    scored.sort(key=lambda x: (-x[0], x[1]))
    seen: List[str] = []
    for _, sid in scored:
        if sid not in seen:
            seen.append(sid)
    return seen


def _parse_uploadtime(v: Any) -> Optional[datetime]:
    """GP uploadtime 可能为 datetime 或多种字符串格式,统一转 datetime。"""
    if isinstance(v, datetime):
        return v
    s = str(v or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
                "%Y%m%d %H:%M:%S", "%Y%m%d%H%M%S",
                "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _time_window(uploadtime: Any) -> Tuple[str, str]:
    """uploadtime ±2 天 -> ("MM/dd/yyyy HH:mm", "MM/dd/yyyy HH:mm")。"""
    ts = _parse_uploadtime(uploadtime)
    if ts is None:
        return "01/01/2026 00:00", "12/31/2026 23:59"
    start = (ts - timedelta(days=2)).strftime("%m/%d/%Y %H:%M")
    end = (ts + timedelta(days=2)).strftime("%m/%d/%Y %H:%M")
    return start, end


def _url_matches_sn(url: str, sn: str) -> bool:
    """URL 文件名是否含该 SN(忽略 +/%2B 等编码差异)。"""
    try:
        from urllib.parse import unquote
        u = _norm_key(unquote(url))
    except Exception:  # noqa: BLE001
        u = _norm_key(url)
    s = _norm_key(sn)
    return len(s) >= 6 and s in u

# 专案配置从 sn_report/config.json -> c4.sfc_projects 加载(60 个,Fcam/Rcam),
# 缺失时用内置默认。sn_class/sn_type 运行时自动发现:
#   sn_type: multipart_keytype = KeyType/SN + 附件(multipart);
#            searchtype = SearchType/Condition + 时间窗(普通表单)
_BUILTIN_PROJECTS: Dict[str, Dict[str, Any]] = {
    "APP007": {
        "project_id": "19", "custom": "LH_Apple_APP007", "num": "KH304",
        "db": "ODSAPP007CONN", "label": "APP007",
    },
    "ANP001": {
        "project_id": "12", "custom": "LH_Apple_ANP001", "num": "KH294",
        "db": "ODSANP001CONN", "label": "Cali (ANP001)",
    },
    "APQ012": {
        "project_id": "19", "custom": "LH_Apple_APQ012", "num": "KH307",
        "db": "ODSAPQ012CONN", "label": "ATW-N (APQ012)",
    },
    "APP003": {
        "project_id": "19", "custom": "LH_Apple_APP003", "num": "KH297",
        "db": "ODSAPP003CONN", "label": "ATW-E (APP003)",
    },
}


def _load_projects() -> Dict[str, Dict[str, Any]]:
    """从 config.json(c4.sfc_projects)加载专案,失败回退内置。"""
    projs = dict(_BUILTIN_PROJECTS)
    try:
        base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
            else Path(__file__).resolve().parent
        cfg = json.loads((base / "config.json").read_text(encoding="utf-8-sig"))
        for p in cfg.get("c4", {}).get("sfc_projects", []):
            pid = p.get("id")
            if pid:
                projs[pid] = p
    except Exception:  # noqa: BLE001
        pass
    return projs


PROJECTS = _load_projects()


class SfcPortal:
    """SFC + ReportPortal 登录/查询客户端。"""

    def __init__(self, userid: str, password: str, project: str = "APP007"):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA
        self.userid = userid
        self.password = password
        if project not in PROJECTS:
            raise ValueError("未知专案: %s(可选 %s)" % (project, list(PROJECTS)))
        self.project = project
        self.cfg = PROJECTS[project]
        self._sn_class: Optional[str] = None
        self._sn_type: Optional[str] = None
        self._db: Optional[str] = self.cfg.get("db", "")
        self._login_debug: str = ""

    # ---------- 登录 ----------
    def login(self) -> bool:
        r = self.session.get(SFC + "/login.aspx", timeout=15)
        fv = self._formvals(r.text)
        data = dict(fv)
        data.update({
            "__LASTFOCUS": "", "__EVENTTARGET": "", "__EVENTARGUMENT": "",
            "Login1$useridtb": self.userid,
            "Login1$userpwdtb": self.password,
            "Login1$LoginImageButton": "登 入",
        })
        r = self.session.post(SFC + "/login.aspx", data=data,
                              timeout=20, allow_redirects=True)
        ok = "login.aspx" not in r.url and r.status_code == 200
        self._login_debug = "status=%s url=%s" % (r.status_code, r.url)
        if not ok:
            try:
                txt = re.sub(r"<[^>]+>", " ", r.text)
                txt = re.sub(r"\s+", " ", txt)
                for kw in ("密码错误", "密码不正确", "账号不存在", "帳號",
                           "账号", "无效", "错误", "失败"):
                    m = re.search(r"[^。；;]{0,30}" + kw + r"[^。；;]{0,40}", txt)
                    if m:
                        self._login_debug += " | 页面提示: " + m.group(0).strip()[:120]
                        break
            except Exception:  # noqa: BLE001
                pass
        if ok:
            # 打开 APP007 入口建立项目上下文
            self.session.get(
                SFC + "/index.aspx?project=%s&custom=%s&num=%s" % (
                    self.cfg["project_id"], self.cfg["custom"], self.cfg["num"]),
                timeout=20)
            self._discover()
        return ok

    def _discover(self):
        """从 left 菜单自动发现 Serin 类名/类型与数据库连接。"""
        try:
            html = self.session.get(SFC + "/skin/m1/left.aspx", timeout=20).text
            entries = []
            for m in re.finditer(
                    r"openPage\(\d+,'([^']+)','([^']+)','([^']+)','([^']+)','([^']+)'\)[^>]*>([^<]+)",
                    html):
                url, device, db, _plant, _user, label = m.groups()
                entries.append((url, db, label.strip()))
            for url, db, _label in entries:
                if "SMTAOI" in url and not self._db:
                    self._db = db
            # 优先: 类名含 SNTrackInformation / FOLSNTracker(最可靠)
            for url, _db, _label in entries:
                if "SNTrackInformation" in url or "FOLSNTracker" in url:
                    self._sn_class = url.split("classname=")[-1]
                    self._sn_type = (
                        "searchtype" if "FOLSNTrackerPackage" in url
                        else "multipart_keytype")
                    break
            # 其次: 标签为 "SN Track"(或含 SN Track)
            if self._sn_class is None:
                for url, _db, label in entries:
                    if re.search(r"(?i)^sn track$|sn track", label):
                        self._sn_class = url.split("classname=")[-1]
                        self._sn_type = "multipart_keytype"
                        break
            if self._sn_class is None:
                # 回退到通用默认
                self._sn_class = "MESReportTeamplate.Report.SNTrackInformation_MW"
                self._sn_type = "multipart_keytype"
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _formvals(html: str) -> Dict[str, str]:
        out = {}
        for m in re.finditer(r'<input\b[^>]*>', html, re.I):
            tag = m.group(0)
            nm = re.search(r'name="([^"]*)"', tag)
            if not nm:
                continue
            name = nm.group(1)
            if name in ("__EVENTTARGET", "__EVENTARGUMENT", "__LASTFOCUS"):
                continue
            tp = re.search(r'type="([^"]*)"', tag)
            typ = tp.group(1).lower() if tp else ""
            if typ in ("submit", "button", "image"):
                continue
            vl = re.search(r'value="([^"]*)"', tag)
            out[name] = vl.group(1) if vl else ""
        return out

    # ---------- ReportPortal 打开页面 ----------
    def open_report(self, classname: str) -> str:
        url = RP + "/ReportPortal?classname=" + classname
        db = self._db or self.cfg.get("db", "")
        r = self.session.post(
            url,
            data="p=%s&p=%s&p=%s&userID=%s" % (
                self.cfg["custom"].replace("LH_Apple_", ""),
                db, PLANT, self.userid),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        return r.text

    # ---------- Serin(SN Track,全制程追溯) ----------
    def sntrack(self, sn: str) -> Dict[str, Any]:
        if self._sn_class is None:
            self._discover()
        sn_class = self._sn_class or "MESReportTeamplate.Report.SNTrackInformation_MW"
        page = self.open_report(sn_class)
        # 表单自适应: 页面有哪些字段就按哪种方式提交
        has_keytype = re.search(r'name="KeyType"', page)
        has_searchtype = re.search(r'name="SearchType"', page)
        has_sn_only = re.search(r'name="SN"', page) and not has_keytype
        other = json.dumps([self.cfg["custom"].replace("LH_Apple_", ""),
                            self._db or self.cfg.get("db", ""), PLANT, self.userid])
        if has_keytype:
            data = {
                "KeyType": "SN", "SN": sn,
                "classname": sn_class, "onhandlername": "",
                "OtherValue": other, "viewname": "",
                "userID": self.userid, "token": "",
            }
            files = {"UploadFile": ("", b"", "application/octet-stream")}
            r = self.session.post(RP + "/ReportPortal/Search",
                                  data=data, files=files, timeout=120)
        elif has_searchtype:
            data = {
                "SearchType": "SN", "Condition": sn,
                "starttime": "01/01/2026 00:00", "endtime": "12/31/2026 23:59",
                "classname": sn_class, "onhandlername": "",
                "OtherValue": other, "viewname": "",
                "userID": self.userid, "token": "",
            }
            r = self.session.post(RP + "/ReportPortal/Search",
                                  data=data, timeout=120)
            if r.status_code != 200:
                # 部分页面强制 multipart(FormData),失败时回退
                r = self.session.post(
                    RP + "/ReportPortal/Search", data=data,
                    files={"UploadFile": ("", b"", "application/octet-stream")},
                    timeout=120)
        elif has_sn_only:
            data = {
                "SN": sn,
                "classname": sn_class, "onhandlername": "",
                "OtherValue": other, "viewname": "",
                "userID": self.userid, "token": "",
            }
            files = {"UploadFile": ("", b"", "application/octet-stream")}
            r = self.session.post(RP + "/ReportPortal/Search",
                                  data=data, files=files, timeout=120)
        else:
            return {"headers": [], "records": [], "record": {},
                    "error": "未知 Serin 表单结构"}
        html = r.text
        th = [re.sub(r"<[^>]+>", "", t).strip()
              for t in re.findall(r'<th\b[^>]*>(.*?)</th>', html, re.I | re.S)]
        rows = []
        for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', html, re.I | re.S):
            tds = [re.sub(r"<[^>]+>", "", td).strip()
                   for td in re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.I | re.S)]
            if len(tds) >= 4 and any(tds):
                rows.append(tds)
        record = {}
        if rows and th:
            record = dict(zip(th, rows[0]))
        return {"headers": th, "records": rows, "record": record}

    # ---------- MC IMG ----------
    def mcimg_stations(self) -> List[str]:
        html = self.open_report(MCIMG_CLASS)
        m = re.search(r'id="Station"[^>]*data-options="[^"]*data:(\[.*?\])',
                      html, re.S)
        if not m:
            return []
        arr = json.loads(m.group(1).replace("&quot;", '"'))
        return [x.get("Id") for x in arr if x.get("Id")]

    def mcimg_search(self, station: str, stype: str, cond: str,
                     start: str = "01/01/2026 00:00",
                     end: str = "12/31/2026 23:59") -> Tuple[int, str]:
        fields = {
            "Station": station,
            "SearchType": stype,
            "Condition": cond,
            "IMGType": "",
            "starttime": start,
            "endtime": end,
            "classname": MCIMG_CLASS,
            "onhandlername": "",
            "OtherValue": json.dumps([self.cfg["custom"].replace("LH_Apple_", ""),
                                      self._db or self.cfg.get("db", ""),
                                      PLANT, self.userid]),
            "viewname": "",
            "userID": self.userid,
            "token": "",
        }
        r = self.session.post(RP + "/ReportPortal/Search",
                              data=fields, timeout=120)
        return r.status_code, r.text

    @staticmethod
    def _extract_links(html: str) -> Tuple[List[str], List[str], List[str]]:
        imgs = sorted(set(re.findall(
            r'href="(http[^"]*\.(?:jpg|jpeg|png)[^"]*)"', html, re.I)))
        zips = sorted(set(re.findall(
            r'href="(http[^"]*\.zip[^"]*)"', html, re.I)))
        xlsx = sorted(set(re.findall(
            r'href="(http[^"]*\.xlsx[^"]*)"', html, re.I)))
        return imgs, zips, xlsx


def collect_sn(client: SfcPortal, sn: str, out_dir: Path,
               exports: Optional[List[str]] = None,
               log: Optional[Any] = None) -> Dict[str, Any]:
    """SN -> Serin -> 74 站位图片清单。

    exports: 勾选项,可取 serin/mcimg/excel/download(默认全开)。
    log: 可选回调函数(str) 输出进度。
    """
    exports = exports or ["serin", "mcimg", "excel"]
    if log is None:
        log = print
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) Serin(SN Track)
    serin: Dict[str, Any] = {"headers": [], "records": [], "record": {}}
    if "serin" in exports:
        serin = client.sntrack(sn)
        (out_dir / "serin_sn_track.json").write_text(
            json.dumps(serin, ensure_ascii=False, indent=2), encoding="utf-8")
    rec = serin.get("record", {})
    lotno = rec.get("LaserLotno") or rec.get("FOL Lotno") or ""
    sensor = rec.get("Sensor", "")
    log("Serin: Sensor=%s VCMID=%s lotno=%s" % (
        sensor, rec.get("VCMID", "")[:30], lotno))

    # 2) MC IMG 站位
    stations = client.mcimg_stations() if "mcimg" in exports else []
    log("MC IMG stations: %d" % len(stations))

    keys = [("SN", sn)]
    if lotno:
        keys.append(("lotno", lotno))
    if sensor:
        keys.append(("Sensor-as-SN", sensor))

    manifest = {"sn": sn, "serin": rec, "stations": {}}
    total = 0
    for i, st in enumerate(stations, 1):
        entry = {"station": st, "key": "", "cond": "",
                 "status": 0, "rows": 0, "imgs": 0, "zips": 0,
                 "xlsx": "", "links": []}
        for ktype, kcond in keys:
            try:
                status, html = client.mcimg_search(st, ktype if ktype != "Sensor-as-SN" else "SN", kcond)
            except Exception as exc:  # noqa: BLE001
                entry["status"] = "timeout"
                break
            imgs, zips, xlsx = client._extract_links(html)
            rows = len(re.findall(r'<tr\b', html, re.I))
            if status == 200 and (imgs or zips or rows >= 3 or sn in html or kcond in html):
                entry.update({
                    "key": ktype, "cond": kcond, "status": status,
                    "rows": rows, "imgs": len(imgs), "zips": len(zips),
                    "xlsx": xlsx[0] if xlsx else "",
                    "links": imgs + zips,
                })
                total += len(imgs) + len(zips)
                break
        manifest["stations"][st] = entry
        mark = "***" if (entry["imgs"] or entry["zips"]) else ""
        log("  %-26s key=%-12s rows=%-4d imgs=%-3d zips=%-3d %s" % (
            st, entry["key"], entry["rows"], entry["imgs"], entry["zips"], mark))
        if entry["links"]:
            with open(out_dir / "image_links.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "station": st, "key": entry["key"], "cond": entry["cond"],
                    "urls": entry["links"], "xlsx": entry["xlsx"],
                }, ensure_ascii=False) + "\n")
        time.sleep(0.15)

    manifest["total_links"] = total
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # 3) 可选:下载图片/压缩包(需图片服务器可达的机器,台式机)
    if "download" in exports:
        dl_root = out_dir / "downloads"
        dl_root.mkdir(parents=True, exist_ok=True)
        n_ok = n_fail = 0
        for line in (out_dir / "image_links.jsonl").read_text(
                encoding="utf-8").splitlines():
            item = json.loads(line)
            st_dir = dl_root / item["station"]
            st_dir.mkdir(parents=True, exist_ok=True)
            for url in item["urls"]:
                name = url.split("/")[-1].split("?")[0]
                try:
                    rr = requests.get(url.replace("&amp;", "&"), timeout=120)
                    if rr.status_code == 200:
                        (st_dir / name).write_bytes(rr.content)
                        n_ok += 1
                    else:
                        n_fail += 1
                        log("下载失败 %s -> HTTP %d" % (name, rr.status_code))
                except Exception as exc:  # noqa: BLE001
                    n_fail += 1
                    log("下载失败 %s -> %r" % (name, exc))
        manifest["downloaded"] = n_ok
        manifest["download_failed"] = n_fail
        log("下载完成: 成功 %d, 失败 %d" % (n_ok, n_fail))
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def sfc_fallback_urls(client: SfcPortal, column: str = "",
                      station_label: str = "", key: str = "",
                      uploadtime: Any = "", sn_hint: str = "",
                      url: str = "", max_stations: int = 4,
                      max_urls: int = 24,
                      cache: Optional[Dict[str, List[str]]] = None
                      ) -> List[str]:
    """失效图片走 SFC MC IMG 补齐:返回候选图片 URL 列表(按相关度排序)。

    column/station_label/url 用于定位 SFC 站位;key 为查询条件
    (EOL 传 SN,FOL 传 sensorid);sn_hint 用于过滤非本 SN 的图。
    cache: {station_id: urls} 跨图片复用同一站的搜索结果。
    """
    if not key or client is None:
        return []
    try:
        sfc_ids = client.mcimg_stations()
    except Exception:  # noqa: BLE001
        return []
    candidates = sfc_station_candidates(
        sfc_ids, column=column, station_label=station_label, url=url)
    if not candidates:
        return []
    start, end = _time_window(uploadtime)
    out: List[str] = []
    seen: set = set()
    if cache is None:
        cache = {}
    for st in candidates[:max_stations]:
        ckey = f"{st}|{start}|{end}"
        if ckey in cache:
            urls = cache[ckey]
        else:
            try:
                _status, html = client.mcimg_search(st, "SN", key, start, end)
            except Exception:  # noqa: BLE001
                continue
            urls, _zips, _xlsx = client._extract_links(html)
            cache[ckey] = urls
        for u in urls:
            if u in seen:
                continue
            if sn_hint and not _url_matches_sn(u, sn_hint):
                continue
            seen.add(u)
            out.append(u)
            if len(out) >= max_urls:
                return out
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sn", required=True)
    ap.add_argument("--project", default="APP007",
                    choices=list(PROJECTS))
    ap.add_argument("--exports", default="serin,mcimg,excel")
    ap.add_argument("--user", default="F1679837")
    ap.add_argument("--password", default="Szlh202607")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else (
        Path(__file__).resolve().parent / "output" / "app007_sfc" /
        datetime.now().strftime("%Y%m%d_%H%M%S"))

    client = SfcPortal(args.user, args.password, project=args.project)
    if not client.login():
        print("SFC 登录失败")
        return 1
    print("SFC 登录成功(专案: %s)" % args.project)
    collect_sn(client, args.sn, out_dir,
               exports=[x.strip() for x in args.exports.split(",") if x.strip()])
    print("输出目录:", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
