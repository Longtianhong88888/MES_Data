"""ReportPortal 客户端:MC IMG UpLoadInfo(PR 图片)+ ACF Test Data。

对应 login_test/login_test.ps1 的 Step 9~11:
- GetList 枚举 SearchType 选项;
- Search 用 multipart/form-data 提交(字段值需 HTML 解码);
- 结果页 EasyUI datagrid,数据在 <p> 标签,图片为签名 URL,Excel 导出在 href。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .mes_client import MesClient, _all_form_fields
from .models import ImageRecord, SnRecord, StationRecord


class PortalError(RuntimeError):
    pass


def _multipart_body(fields: Dict[str, str], boundary: str) -> Tuple[str, str]:
    parts = []
    for k, v in fields.items():
        parts.append(f"--{boundary}\r\n")
        parts.append(f'Content-Disposition: form-data; name="{k}"\r\n\r\n')
        parts.append(f"{v}\r\n")
    parts.append(f"--{boundary}--\r\n")
    body = "".join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


def _portal_time(value: str) -> str:
    """把 YYYY-MM-DD HH:MM 转成 ReportPortal 需要的 MM/DD/YYYY HH:MM。"""
    value = str(value).strip()
    if not value:
        return ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(value, fmt).strftime("%m/%d/%Y %H:%M")
        except ValueError:
            continue
    return value


def _norm_pocket(value: str) -> str:
    """pocket 归一化:"2_3" -> "0203","04_03" -> "0403","15" -> "15"。"""
    parts = re.findall(r"\d+", str(value))
    return "".join(p.zfill(2) for p in parts)


class ReportPortalClient:
    def __init__(self, mes: MesClient, out_dir: Path):
        self.mes = mes
        self.session = mes.session
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.portal_url = ""
        self.portal_origin = ""
        self.page_fields: Dict[str, str] = {}
        self.token = ""

    # ------------------------------------------------------------ open page
    def find_menu_page(self, label: str) -> Optional[Tuple[str, str, str, str, str]]:
        """在 frame 菜单里找 openPage(...) 链接到指定 label 的门户参数。"""
        for fc in self.mes.frame_html:
            m = re.search(
                r"openPage\(\s*\d+\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*\)[^>]*>\s*"
                + re.escape(label),
                fc,
                re.IGNORECASE,
            )
            if m:
                return tuple(m.groups())  # type: ignore[return-value]
        return None

    def open_portal(self, menu_label: str = "MC IMG UpLoadInfo") -> None:
        """打开门户页面,抓取 token 与默认表单字段。"""
        params = self.find_menu_page(menu_label)
        if not params:
            raise PortalError(f"菜单中未找到 {menu_label}")
        portal_url, device, dbname, plantid, userid = params
        self.portal_url = portal_url
        self.portal_origin = re.match(r"(https?://[^/]+)", portal_url).group(1)
        body = f"p={device}&p={dbname}&p={plantid}&userID={userid}"
        resp = self.session.post(
            portal_url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=60,
        )
        resp.raise_for_status()
        html = resp.text
        (self.out_dir / "raw").mkdir(parents=True, exist_ok=True)
        (self.out_dir / "raw" / "portal_page.html").write_text(html, encoding="utf-8")

        self.page_fields = _all_form_fields(html)
        m = re.search(
            r'<input\b[^>]*\bname="token"[^>]*>', html, re.IGNORECASE
        )
        if m:
            vm = re.search(r'value="([^"]*)"', m.group(0), re.IGNORECASE)
            if vm:
                self.token = vm.group(1)

    # ---------------------------------------------------------------- getlist
    def get_list(
        self,
        class_name: str,
        method_name: str,
        send_parameters: List[Dict[str, Any]],
        other_value: List[str],
    ) -> Dict[str, Any]:
        """GetList:枚举下拉/选项,返回 JSON 字典。"""
        import json

        payload = {
            "ClassName": class_name,
            "MethodName": method_name,
            "SendParameters": send_parameters,
            "Othervalue": other_value,
        }
        resp = self.session.post(
            self.portal_origin + "/ReportPortal/GetList",
            data={"Jsonstr": json.dumps(payload, ensure_ascii=False)},
            timeout=60,
        )
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError as exc:
            raise PortalError(f"GetList 返回非 JSON:{resp.text[:300]}") from exc

    def search(self, values: Dict[str, str]) -> str:
        """用页面默认字段 + 指定值做 multipart Search,返回结果 HTML。"""
        fields = {
            k: v for k, v in self.page_fields.items() if k != "token"
        }
        for k, v in values.items():
            fields[k] = v
        # 页面字段值需要 HTML 解码(&quot; -> ")
        from html import unescape

        fields = {k: unescape(str(v)) for k, v in fields.items()}
        boundary = "----CodexBoundary" + uuid.uuid4().hex
        body, ctype = _multipart_body(fields, boundary)
        headers = {}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        resp = self.session.post(
            self.portal_origin + "/ReportPortal/Search",
            data=body.encode("utf-8"),
            headers={"Content-Type": ctype, **headers},
            timeout=180,
        )
        resp.raise_for_status()
        return resp.text

    # ------------------------------------------------------------------- ACF
    def acf_query(self, rec: SnRecord, mc_types: List[Dict[str, str]],
                  start: str, end: str) -> None:
        """按三种 ACF 机型查询,提取 sensorID/flexid、Excel 导出与图片清单。"""
        params = self.find_menu_page("ACF Test Data")
        if not params:
            rec.errors.append("ACF: 菜单中未找到 ACF Test Data")
            return
        portal_url, device, dbname, plantid, userid = params
        origin = re.match(r"(https?://[^/]+)", portal_url).group(1)

        # 打开 ACF 页面取得 token/字段
        body = f"p={device}&p={dbname}&p={plantid}&userID={userid}"
        resp = self.session.post(
            portal_url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=60,
        )
        resp.raise_for_status()
        acf_html = resp.text
        fields = _all_form_fields(acf_html)
        m = re.search(r'<input\b[^>]*\bname="token"[^>]*>', acf_html, re.IGNORECASE)
        token = ""
        if m:
            vm = re.search(r'value="([^"]*)"', m.group(0), re.IGNORECASE)
            if vm:
                token = vm.group(1)

        from html import unescape

        for mc in mc_types:
            mc_id = mc.get("id", "")
            label = mc.get("label", mc_id)
            sf = {k: unescape(str(v)) for k, v in fields.items() if k != "token"}
            sf.update(
                {
                    "MCType": mc_id,
                    "SearchType": "SN",
                    "Condition": rec.sn,
                    "starttime": _portal_time(start),
                    "endtime": _portal_time(end),
                }
            )
            boundary = "----CodexBoundary" + uuid.uuid4().hex
            mbody, ctype = _multipart_body(sf, boundary)
            headers = {"Content-Type": ctype}
            if token:
                headers["Authorization"] = "Bearer " + token
            try:
                sresp = self.session.post(
                    origin + "/ReportPortal/Search",
                    data=mbody.encode("utf-8"),
                    headers=headers,
                    timeout=180,
                )
                sresp.raise_for_status()
                shtml = sresp.text
                (self.out_dir / "raw").mkdir(parents=True, exist_ok=True)
                (self.out_dir / "raw" / f"acf_{mc_id}.html").write_text(shtml, encoding="utf-8")

                if mc_id == "acfunloadbondnewdatabak":
                    rec.sensor_id = self._first_match(
                        shtml, r"(?i)<p>\s*((?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*[0-9])[A-Z0-9]{10,16})\s*</p>"
                    ) or rec.sensor_id
                    rec.flex_id = self._first_match(
                        shtml, r"(?i)<p>\s*((?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*[0-9])[A-Z0-9]{15,22})\s*</p>"
                    ) or rec.flex_id

                self._save_excel_and_images(shtml, f"acf_{mc_id}", label)
            except requests.RequestException as exc:
                rec.errors.append(f"ACF {label}: {exc}")

    # -------------------------------------------------------------- MC IMG
    def mc_img_query(self, rec: SnRecord, img_stations: List[Dict[str, str]],
                     start: str, end: str, download_images: bool,
                     key_map: Optional[Dict[str, Dict[str, Dict[str, str]]]] = None) -> None:
        """按站位查询 MC IMG,收集 PR 图片链接/元数据/Excel 导出。

        img_stations 支持两种条目:
        - 旧格式 {"id": station_id, "label": label}:沿用自动发现 SearchType + SN 条件;
        - 新格式(带 search_type / condition_from / filter):按 trace_key_resolver 解析出的
          key 构造查询条件,并可用 pocket(文件名 XY)过滤。
        """
        if not self.portal_origin:
            self.open_portal("MC IMG UpLoadInfo")
        for st in img_stations:
            station_id = st.get("id", "")
            label = st.get("label", station_id)
            keys = (key_map or {}).get(label) or (key_map or {}).get(station_id) or {}

            if st.get("search_type") and st.get("condition_from"):
                search_type = st["search_type"]
                condition = self._condition_value(rec, keys, st["condition_from"])
                if not condition:
                    condition = keys.get("lot") or rec.sn
            else:
                search_type, condition = self._discover_search_type(
                    station_id, rec.sn, rec.sensor_id, rec.flex_id
                )
            sf = {
                "Station": station_id,
                "SearchType": search_type,
                "Condition": condition,
                "IMGType": "",
                "starttime": _portal_time(start),
                "endtime": _portal_time(end),
            }
            try:
                shtml = self.search(sf)
                (self.out_dir / "raw").mkdir(parents=True, exist_ok=True)
                (self.out_dir / "raw" / f"mcimg_{station_id}.html").write_text(shtml, encoding="utf-8")

                imgs = self._extract_images(shtml)
                if st.get("filter") == "pocket" and keys.get("carrier") and keys.get("pocket"):
                    before = len(imgs)
                    imgs = self._filter_urls_by_pocket(imgs, keys["carrier"], keys["pocket"])
                    if before != len(imgs):
                        print(f"    [filter] {label}: pocket {keys['pocket']} 过滤 {before}->{len(imgs)} 张")
                station = self._find_or_add_station(rec, label)
                for url in imgs:
                    img = ImageRecord(station=label, url=url)
                    if download_images:
                        img.local_path = self._download_image(url, station_id)
                    station.images.append(img)
                if keys:
                    station.extra.setdefault("trace_key", {}).update(keys)

                meta = self._extract_metadata(shtml)
                if meta:
                    for k, v in meta.items():
                        station.extra[k] = v
                self._save_excel_and_images(shtml, f"mcimg_{station_id}", label)
            except requests.RequestException as exc:
                rec.errors.append(f"MCIMG {label}: {exc}")

    def _condition_value(self, rec: SnRecord, keys: Dict[str, str],
                         condition_from: str) -> str:
        """按 condition_from 取查询 Condition(优先解析出的 key)。"""
        if condition_from == "carrier":
            return keys.get("carrier", "")
        if condition_from == "lot":
            return keys.get("lot", "")
        if condition_from == "module_sn":
            return rec.sn
        if condition_from == "sensor_id":
            return rec.sensor_id or keys.get("sensor_id", "")
        if condition_from == "flex_id":
            return rec.flex_id or keys.get("flex_id", "")
        if condition_from == "vcm_id":
            for c in rec.components:
                if c.material and "vcm" in c.material.lower():
                    return c.id
            return keys.get("vcm_id", "")
        return ""

    @staticmethod
    def _filter_urls_by_pocket(urls: List[str], carrier: str, pocket: str) -> List[str]:
        """按照片文件名里的 载具ID_XY 段过滤(命名规则见追溯明细表)。"""
        if not urls or not carrier or not pocket:
            return urls
        target = _norm_pocket(pocket)
        if not target:
            return urls
        keep: List[str] = []
        for u in urls:
            fn = u.split("?")[0].rsplit("/", 1)[-1]
            pos = fn.find(carrier)
            if pos >= 0:
                digits = re.findall(r"\d{2,4}", fn[pos + len(carrier):])
                if digits and _norm_pocket(digits[0]) == target:
                    keep.append(u)
                    continue
                if digits:
                    continue  # 载具匹配但 XY 不符,过滤
            keep.append(u)  # 无法解析文件名时保留,避免误删
        return keep

    def _discover_search_type(
        self, station_id: str, sn: str, sensor_id: str, flex_id: str
    ) -> Tuple[str, str]:
        """用 GetList 找该站位可用的 SearchType(SN > sensor > flex)。"""
        try:
            params = self.find_menu_page("MC IMG UpLoadInfo")
            other = list(params[1:]) if params else []
            send = [
                {"Key": "Station", "Parametertype": 1, "Value": station_id},
                {"Key": "SearchType", "Parametertype": 1, "Value": [station_id]},
                {"Key": "Condition", "Parametertype": 3, "Value": None},
                {"Key": "IMGType", "Parametertype": 1, "Value": None},
                {"Key": "starttime", "Parametertype": 2, "Value": None},
                {"Key": "endtime", "Parametertype": 2, "Value": None},
            ]
            data = self.get_list(
                "MESReportTeamplate.TestReport.SMTAOIRepor",
                "SearchType",
                send,
                other,
            )
            opts: List[Dict[str, Any]] = []
            for o in data.get("Resultvalue") or []:
                if o.get("Value"):
                    opts.extend(o["Value"])
                elif o.get("Id"):
                    opts.append(o)
            for opt in opts:
                if str(opt.get("Id")) == "SN" or str(opt.get("Value")) == "SN":
                    return "SN", sn
            for opt in opts:
                if re.search(r"(?i)sensor", str(opt.get("Id")) + str(opt.get("Value"))):
                    return str(opt.get("Id")), sensor_id or sn
            for opt in opts:
                if re.search(r"(?i)flex", str(opt.get("Id")) + str(opt.get("Value"))):
                    return str(opt.get("Id")), flex_id or sn
        except requests.RequestException:
            pass
        return "SN", sn

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _first_match(html: str, pattern: str) -> str:
        m = re.search(pattern, html)
        return m.group(1) if m else ""

    def _extract_images(self, html: str) -> List[str]:
        urls = re.findall(
            r'href="(http://[^"]*\.(?:jpg|jpeg|png)[^"]*)"', html, re.IGNORECASE
        )
        from html import unescape

        return sorted(set(unescape(u) for u in urls))

    def _extract_metadata(self, html: str) -> Dict[str, str]:
        """EasyUI datagrid 结果页数据在 <p> 标签,尽力解析为键值。"""
        soup = BeautifulSoup(html, "lxml")
        items = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        items = [x for x in items if x]
        if not items:
            return {}
        # 前几项通常是表头,后续是数据;只做最保守的键值猜解
        meta: Dict[str, str] = {}
        head = items[0] if items else ""
        if "," in head:
            heads = [h.strip() for h in head.split(",")]
            if len(items) > 1:
                vals = [v.strip() for v in items[1].split(",")]
                for h, v in zip(heads, vals):
                    meta[h] = v
        return meta

    def _save_excel_and_images(self, html: str, prefix: str, label: str) -> None:
        from html import unescape

        dl = self.out_dir
        xlsm = re.search(r'href="([^"]*\.xlsx[^"]*)"', html, re.IGNORECASE)
        if xlsm:
            xls_url = unescape(xlsm.group(1)).replace("\\", "/")
            xls_url = urljoin(self.portal_origin, xls_url)
            try:
                resp = self.session.get(xls_url, timeout=180)
                resp.raise_for_status()
                (dl / f"{prefix}.xlsx").write_bytes(resp.content)
            except requests.RequestException as exc:
                print(f"    [warn] {label} Excel 下载失败: {exc}")

        img_urls = self._extract_images(html)
        if img_urls:
            (dl / f"{prefix}_images.txt").write_text("\n".join(img_urls), encoding="utf-8")

    def _download_image(self, url: str, station_id: str) -> str:
        dl = self.out_dir / "images"
        dl.mkdir(parents=True, exist_ok=True)
        name = url.split("?")[0].rsplit("/", 1)[-1] or f"{station_id}.jpg"
        target = dl / f"{station_id}_{name}"
        if target.exists():
            return str(target)
        # VM 无法直连图片服务器时,两个 host 都试一次
        candidates = [
            url,
            url.replace("http://cma1.fs.com:8081", "http://10.142.119.202:8081"),
        ]
        for cand in candidates:
            try:
                resp = self.session.get(cand, timeout=60)
                resp.raise_for_status()
                target.write_bytes(resp.content)
                return str(target)
            except requests.RequestException:
                continue
        return ""

    def _find_or_add_station(self, rec: SnRecord, label: str) -> StationRecord:
        for st in rec.stations:
            if st.station == label:
                return st
        st = StationRecord(station=label)
        rec.stations.append(st)
        return st
