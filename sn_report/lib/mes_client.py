"""MES 客户端:ASP.NET 表单登录 + SN 全制程查询与通用表格解析。

对应 login_test/login_test.ps1 的 Step 1~8,用 Python 重写并增强:
- 登录/会话验证逻辑保持一致;
- SN search 结果用"表头驱动"的通用解析,不再依赖固定列数;
- 任何页面都会保留原始 HTML,方便 --discover 模式排查字段。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .models import ComponentRecord, ConsumableRecord, SnRecord, StationRecord


class MesLoginError(RuntimeError):
    pass


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    )
    return session


def _form_value(html: str, field: str) -> str:
    m = re.search(
        r'<input\b[^>]*\bname="' + re.escape(field) + r'"[^>]*>',
        html,
        re.IGNORECASE,
    )
    if not m:
        return ""
    vm = re.search(r'value="([^"]*)"', m.group(0), re.IGNORECASE)
    return vm.group(1) if vm else ""


def _all_form_fields(html: str) -> Dict[str, str]:
    """解析页面里所有 input/select 的默认值(不含 submit/button/image)。"""
    fields: Dict[str, str] = {}
    for m in re.finditer(r"<input\b[^>]*>", html, re.IGNORECASE):
        tag = m.group(0)
        nm = re.search(r'\bname\s*=\s*["\']([^"\']+)["\']', tag, re.IGNORECASE)
        if not nm:
            continue
        name = nm.group(1)
        if name in ("__EVENTTARGET", "__EVENTARGUMENT"):
            continue
        tp = re.search(r'\btype\s*=\s*["\']([^"\']+)["\']', tag, re.IGNORECASE)
        type_ = tp.group(1).lower() if tp else ""
        if type_ in ("submit", "button", "image"):
            continue
        vl = re.search(r'\bvalue\s*=\s*["\']([^"\']*)["\']', tag, re.IGNORECASE)
        value = vl.group(1) if vl else ""
        if type_ in ("radio", "checkbox") and "checked" not in tag.lower():
            continue
        fields[name] = value

    for m in re.finditer(
        r"<select\b[^>]*>(.*?)</select>", html, re.IGNORECASE | re.DOTALL
    ):
        tag = m.group(0)
        nm = re.search(r'\bname\s*=\s*["\']([^"\']+)["\']', tag, re.IGNORECASE)
        if not nm:
            continue
        name = nm.group(1)
        opt = re.search(
            r"<option\b[^>]*\bselected(?:=[^ >]*)?[^>]*\bvalue=\"([^\"]*)\"",
            tag,
            re.IGNORECASE,
        )
        if not opt:
            opt = re.search(r"<option\b[^>]*\bvalue=\"([^\"]*)\"", tag, re.IGNORECASE)
        if opt:
            fields[name] = opt.group(1)
    return fields


class MesClient:
    def __init__(self, root_config: Dict[str, Any], out_dir: Path):
        self.session = create_session()
        self.root = root_config
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

        self.login_url: str = str(root_config.get("login_url", "")).rstrip("/")
        self.app_url: str = str(root_config.get("resource_url", ""))
        self.username = str(root_config.get("username", ""))
        self.password = str(root_config.get("password", ""))
        form = root_config.get("login_form", {})
        self.username_field = form.get("username_field", "Login1$useridtb")
        self.password_field = form.get("password_field", "Login1$userpwdtb")
        self.button_name = form.get("button_field", "Login1$LoginImageButton")
        self.extra_fields = form.get("extra_fields", {}) or {}

        base = self.login_url
        if not self.app_url:
            base = self.login_url
        self.origin = re.match(r"(https?://[^/]+)", base).group(1) if base else ""

    # ---------------------------------------------------------------- login
    def login(self) -> None:
        if not self.login_url or not self.username:
            raise MesLoginError("config.json 缺少 login_url / username / password")

        # 配置里的 login_url 可能是 "http://host/login"(路径),登录页是域名根下的 login.aspx
        if self.login_url.endswith("login.aspx"):
            login_page_url = self.login_url
        else:
            m = re.match(r"(https?://[^/]+)", self.login_url)
            if not m:
                raise MesLoginError(f"login_url 格式不正确: {self.login_url}")
            login_page_url = m.group(1) + "/login.aspx"
        r = self.session.get(login_page_url, timeout=30)
        r.raise_for_status()
        html = r.text

        vs = _form_value(html, "__VIEWSTATE")
        vsg = _form_value(html, "__VIEWSTATEGENERATOR")
        ev = _form_value(html, "__EVENTVALIDATION")
        if not vs or not ev:
            raise MesLoginError("登录页缺少 __VIEWSTATE/__EVENTVALIDATION,登录流程可能已变化")

        btn_value = _form_value(html, self.button_name)
        body = {
            "__LASTFOCUS": "",
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": vs,
            "__VIEWSTATEGENERATOR": vsg,
            "__EVENTVALIDATION": ev,
            self.username_field: self.username,
            self.password_field: self.password,
            self.button_name: btn_value,
        }
        body.update(self.extra_fields)

        resp = self.session.post(
            login_page_url, data=body, timeout=60, allow_redirects=True
        )
        resp.raise_for_status()
        final_url = resp.url
        if "login.aspx" in final_url or self.password_field in resp.text:
            raise MesLoginError("登录失败:服务器返回登录页(请检查账号密码)")

        # 打开应用入口,确认 frameset 并验证会话
        app_resp = self.session.get(self.app_url, timeout=60)
        app_resp.raise_for_status()
        if "<frameset" not in app_resp.text.lower():
            raise MesLoginError(f"应用入口未返回 frameset:{self.app_url}")

        frames = re.findall(
            r'<frame\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']', app_resp.text, re.IGNORECASE
        )
        self.frames: List[str] = []
        self.frame_html: List[str] = []
        for src in frames[:3]:
            frame_url = urljoin(self.app_url, src)
            try:
                fr = self.session.get(frame_url, timeout=60)
                fr.raise_for_status()
                if re.search(r"login\.aspx|window\.top\.location", fr.text, re.IGNORECASE):
                    continue
                self.frames.append(frame_url)
                self.frame_html.append(fr.text)
            except requests.RequestException:
                continue
        if not self.frame_html:
            raise MesLoginError("登录后无法取得有效 frame,会话可能无效")

    # --------------------------------------------------------------- helpers
    def _post_page(
        self,
        page_url: str,
        html: str,
        values: Dict[str, str],
        trigger: str = "",
    ) -> str:
        """用页面上所有表单字段 + 指定值做一次 ASP.NET 回发。"""
        fields = _all_form_fields(html)
        for k, v in values.items():
            fields[k] = v
        fields["__EVENTTARGET"] = trigger
        fields["__EVENTARGUMENT"] = ""
        resp = self.session.post(page_url, data=fields, timeout=120)
        resp.raise_for_status()
        return resp.text

    def _find_text_field(self, html: str, keywords: Tuple[str, ...]) -> Optional[str]:
        fields = _all_form_fields(html)
        for k in fields:
            if any(w in k.lower() for w in keywords):
                return k
        for k in fields:
            if "txt" in k.lower() or "text" in k.lower() or "sn" in k.lower():
                return k
        return None

    def _find_trigger(self, html: str) -> str:
        m = re.search(
            r'<input\b[^>]*\btype\s*=\s*["\']submit["\'][^>]*>', html, re.IGNORECASE
        )
        if m:
            nm = re.search(r'\bname\s*=\s*["\']([^"\']+)["\']', m.group(0), re.IGNORECASE)
            if nm:
                return nm.group(1)
        m = re.search(
            r"__doPostBack\(\s*['\"]([^'\"]*(?:search|query|btn)[^'\"]*)['\"]",
            html,
            re.IGNORECASE,
        )
        if m:
            return m.group(1)
        m = re.search(
            r'<input\b[^>]*\bname\s*=\s*["\']([^"\']*Button[^"\']*)["\']', html, re.IGNORECASE
        )
        return m.group(1) if m else ""

    # ------------------------------------------------------------- SN query
    def sn_search(
        self,
        sn: str,
        page_rel: str = "report/snsearch.aspx",
        field_name: str = "sntextbox",
        button_name: str = "Button1",
    ) -> str:
        """查询 SN search 页面并返回结果 HTML。"""
        page_url = self.origin + "/" + page_rel.lstrip("/")
        r = self.session.get(page_url, timeout=60)
        r.raise_for_status()
        html = r.text

        fields = _all_form_fields(html)
        if field_name not in fields:
            found = self._find_text_field(html, ("sn", "serial", "barcode"))
            if not found:
                raise RuntimeError(f"SN search 页面未找到输入框({list(fields)[:10]})")
            field_name = found
        trigger = button_name if button_name in html else self._find_trigger(html)
        result = self._post_page(page_url, html, {field_name: sn}, trigger=trigger)

        (self.out_dir / "raw").mkdir(parents=True, exist_ok=True)
        raw = self.out_dir / "raw" / f"snsearch_{sn}.html"
        raw.write_text(result, encoding="utf-8")
        return result

    def sntotalinfo(self, sn: str, page_rel: str = "Tracking/sntotalinfo.aspx") -> str:
        """查询 sntotalinfo 页面并返回结果 HTML(内容按页面结构而定)。"""
        page_url = self.origin + "/" + page_rel.lstrip("/")
        r = self.session.get(page_url, timeout=60)
        r.raise_for_status()
        html = r.text
        field = self._find_text_field(html, ("sn", "serial", "barcode"))
        if not field:
            return ""
        trigger = self._find_trigger(html)
        result = self._post_page(page_url, html, {field: sn}, trigger=trigger)
        (self.out_dir / "raw").mkdir(parents=True, exist_ok=True)
        raw = self.out_dir / "raw" / f"sntotalinfo_{sn}.html"
        raw.write_text(result, encoding="utf-8")
        return result

    # ------------------------------------------------------------ parsing
    def parse_tables(self, html: str) -> List[Dict[str, Any]]:
        """把页面里所有 <table> 解析为 {headers: [...], rows: [[...]], caption}。"""
        soup = BeautifulSoup(html, "lxml")
        tables: List[Dict[str, Any]] = []
        for tbl in soup.find_all("table"):
            rows: List[List[str]] = []
            for tr in tbl.find_all("tr"):
                cells = [
                    " ".join(td.get_text(" ", strip=True).split())
                    for td in tr.find_all(["td", "th"])
                ]
                if cells:
                    rows.append(cells)
            if not rows:
                continue
            headers = rows[0]
            caption = ""
            cap = tbl.find("caption")
            if cap:
                caption = cap.get_text(" ", strip=True)
            tables.append({"caption": caption, "headers": headers, "rows": rows})
        return tables

    def interpret_tables(
        self,
        sn: str,
        tables: List[Dict[str, Any]],
        keywords: Dict[str, List[str]],
    ) -> SnRecord:
        """按列名关键词把通用表格解释为 SN 追溯记录。"""
        rec = SnRecord(sn=sn)

        def has(col: str, group: str) -> bool:
            return any(k in col.lower() for k in keywords.get(group, []))

        # 1) 汇总行:列数 >= 10 且第一列等于 SN
        for tbl in tables:
            for row in tbl["rows"]:
                if len(row) >= 10 and row[0].strip() == sn:
                    headers = tbl["headers"]
                    for i, cell in enumerate(row):
                        if i < len(headers) and headers[i]:
                            rec.summary[headers[i]] = cell
                        else:
                            rec.summary[f"列{i + 1}"] = cell
                    break

        # 2) 站位轨迹 / 组件 / 耗材:按表头关键词归类
        for tbl in tables:
            headers = tbl["headers"]
            has_station = any(has(h, "station") for h in headers)
            has_time = any(has(h, "time") for h in headers)
            has_mc = any(has(h, "mc") for h in headers)
            has_carrier = any(has(h, "carrier") for h in headers)
            has_pocket = any(has(h, "pocket") for h in headers)
            has_head = any(has(h, "head") for h in headers)
            has_material = any(has(h, "material") for h in headers)

            for row in tbl["rows"][1:]:
                if not row:
                    continue
                if has_station:
                    st = StationRecord()
                    for i, cell in enumerate(row):
                        col = headers[i] if i < len(headers) else ""
                        if i == 0 and not col:
                            st.station = cell
                        elif has(col, "station"):
                            st.station = cell
                        elif has(col, "time"):
                            st.time = cell
                        elif has(col, "mc"):
                            st.mc_id = cell
                        elif has(col, "carrier"):
                            st.carrier = cell
                        elif has(col, "pocket"):
                            st.pocket = cell
                        elif has(col, "head"):
                            st.head_id = cell
                        elif col:
                            st.extra[col] = cell
                    if st.station:
                        rec.stations.append(st)
                    continue

                if has_material:
                    comp = ComponentRecord()
                    cons = ConsumableRecord()
                    for i, cell in enumerate(row):
                        col = headers[i] if i < len(headers) else ""
                        lc = col.lower()
                        if i == 0 and not col:
                            comp.material = cons.material = cell
                        elif any(k in lc for k in ("材料", "物料", "耗材", "名称", "名稱")):
                            comp.material = cons.material = cell
                        elif any(k in lc for k in ("批号", "批號", "lot", "id")):
                            comp.id = cons.lot = cell
                        elif any(k in lc for k in ("站位", "站點", "使用站位")):
                            comp.station = cons.station = cell
                        elif col:
                            comp.name = cons.name = cell
                    if comp.material or comp.id:
                        if any(k in (comp.material + comp.name).lower() for k in
                               ("sensor", "lens", "vcm", "stiffener", "tape", "flex", "ircf", "ois")):
                            rec.components.append(comp)
                        rec.consumables.append(cons)

        # 3) 兜底:2 列且第二列是时间的行视为站位轨迹(兼容老页面)
        if not rec.stations:
            for tbl in tables:
                for row in tbl["rows"]:
                    if len(row) == 2 and row[0] != "站位" and re.match(r"^\d{4}-\d{2}-\d{2}", row[1]):
                        rec.stations.append(StationRecord(station=row[0], time=row[1]))

        rec.raw_tables = tables
        return rec

    def collect_sn(self, sn: str, keywords: Dict[str, List[str]]) -> SnRecord:
        """查询单个 SN:snsearch + sntotalinfo,返回追溯记录。"""
        rec = SnRecord(sn=sn)
        try:
            html = self.sn_search(sn)
            rec.raw_files.append(str(self.out_dir / "raw" / f"snsearch_{sn}.html"))
            tables = self.parse_tables(html)
            rec = self.interpret_tables(sn, tables, keywords)
            rec.raw_files = rec.raw_files or []
            rec.raw_files.append(str(self.out_dir / "raw" / f"snsearch_{sn}.html"))
        except Exception as exc:  # noqa: BLE001 - 单 SN 失败不中断批量
            rec.errors.append(f"snsearch: {exc}")

        try:
            html2 = self.sntotalinfo(sn)
            if html2:
                extra = self.parse_tables(html2)
                rec.raw_tables.extend(extra)
                rec.raw_files.append(str(self.out_dir / "raw" / f"sntotalinfo_{sn}.html"))
                # 若 sntotalinfo 有站位/机台信息且 snsearch 没有,合并
                if not rec.stations:
                    rec2 = self.interpret_tables(sn, extra, keywords)
                    if rec2.stations:
                        rec.stations = rec2.stations
        except Exception as exc:  # noqa: BLE001
            rec.errors.append(f"sntotalinfo: {exc}")
        return rec
