#!/usr/bin/env python3
"""SN 信息查询:输入 SN,自动带出所有站位信息(进/出站时间/机台/头/Tray/穴位)。

数据源(C4 优先,SFC 补齐):
1. C4 直连 = Greenplum datacenterdev.t_<专案>_eoldata(SN) + foldata(sensorid)
   —— 机台/头/Tray ID/穴位/进出站时间全字段
2. SFC 门户补齐:snsearch 站位轨迹 + SN Track 基本信息
"""

from __future__ import annotations

import re
import sys
from typing import Dict, List, Optional, Tuple
from datetime import datetime

import pandas as pd

from commonality_data import LdcClient, PROJECT_MAP as LDC_PROJECTS

try:
    import pg8000.native as _pg
except ImportError:  # pragma: no cover
    _pg = None

GP_CFG = dict(host="10.151.130.202", port=5432, database="wwwgpdw",
              user="gpdwdev", password="Altus2014")

# Greenplum 站位列: 站名前缀_字段(按长度降序匹配,避免 time 吞掉 carrierin_time)
_GP_ITEMS = [
    "carrierin_time", "carrierout_time", "trayin_time", "trayout_time",
    "lot_start_time", "lot_end_time", "checkin_time", "checkout_time",
    "intrayposition", "outtrayposition", "incarrierid", "outcarrierid",
    "intrayid", "outtrayid", "carrierid", "trayid", "carrierxy", "trayxy",
    "incarrierxy", "outcarrierxy", "glue_platform", "moldcavity",
    "carrierkey", "toolnum", "updatetime", "defectcode", "presstime",
    "pressvalue", "result", "head", "mc", "time", "lotno", "ip",
]
_GP_FIELD = {
    "carrierin_time": "进站时间", "trayin_time": "进站时间",
    "checkin_time": "进站时间", "lot_start_time": "进站时间",
    "carrierout_time": "出站时间", "trayout_time": "出站时间",
    "checkout_time": "出站时间", "lot_end_time": "出站时间",
    "time": "时间", "mc": "机台号", "head": "头", "toolnum": "头",
    "carrierid": "Tray ID", "trayid": "Tray ID", "incarrierid": "Tray ID(进)",
    "outcarrierid": "Tray ID(出)", "intrayid": "Tray ID(进)",
    "outtrayid": "Tray ID(出)", "carrierxy": "穴位", "trayxy": "穴位",
    "incarrierxy": "穴位(进)", "outcarrierxy": "穴位(出)",
    "intrayposition": "穴位(进)", "outtrayposition": "穴位(出)",
    "moldcavity": "模具穴", "carrierkey": "CarrierKey",
    "lotno": "批号", "result": "结果", "defectcode": "缺陷码",
    "pressvalue": "压力", "presstime": "保压时间", "ip": "IP",
}


def _gp_table_base(project: str) -> Optional[str]:
    """专案 → Greenplum 表基名(t_<base>_eoldata)。"""
    if project in LDC_PROJECTS:
        return LDC_PROJECTS[project][0]
    return project.split("-")[0] if "-" in project else project


def _gp_query_sn(project: str, sn: str) -> Optional[Dict[str, object]]:
    """C4 直连:Greenplum t_<专案>_eoldata(SN)+ foldata(sensorid)。
    返回合并 wide;项目无表或查无数据返回 None。"""
    if _pg is None:
        return None
    base = _gp_table_base(project)
    if not base:
        return None
    eol_t = "t_%s_eoldata" % base.lower()
    fol_t = "t_%s_foldata" % base.lower()
    conn = _pg.Connection(**GP_CFG, timeout=15)
    try:
        has = conn.run(
            "select count(*) from information_schema.tables "
            "where table_schema='datacenterdev' and lower(table_name)='%s'"
            % eol_t)
        if int(has[0][0]) == 0:
            return None
        ecols = [r[0] for r in conn.run(
            "select column_name from information_schema.columns "
            "where table_schema='datacenterdev' and table_name='%s'"
            % eol_t)]
        erows = conn.run("select * from datacenterdev.%s where sn='%s'"
                         % (eol_t, sn))
        if not erows:
            return None
        wide = dict(zip(ecols, erows[0]))
        sid = wide.get("sensorid")
        if sid:
            try:
                fcols = [r[0] for r in conn.run(
                    "select column_name from information_schema.columns "
                    "where table_schema='datacenterdev' and table_name='%s'"
                    % fol_t)]
                frows = conn.run(
                    "select * from datacenterdev.%s where sensorid='%s' limit 1"
                    % (fol_t, sid))
                if frows:
                    fwide = dict(zip(fcols, frows[0]))
                    for k, v in fwide.items():
                        wide.setdefault(k, v)
            except Exception:
                pass
        return wide
    finally:
        conn.close()


def _gp_process_table(wide: Dict[str, object]) -> pd.DataFrame:
    """Greenplum 宽表 → 制程表(站位/进出站/机台/头/Tray/穴位)。"""
    stations: Dict[str, Dict[str, str]] = {}
    for col, v in wide.items():
        if v is None or str(v) in ("None", ""):
            continue
        c = str(col)
        for item in sorted(_GP_ITEMS, key=len, reverse=True):
            if c.endswith("_" + item):
                station = c[: -len(item) - 1]
                field = _GP_FIELD.get(item)
                if field:
                    stations.setdefault(station.upper(), {})[field] = str(v)
                break
    rows = []
    for st, items in stations.items():
        in_t = items.get("进站时间") or items.get("时间", "")
        out_t = items.get("出站时间", "")
        prod = ""
        try:
            if in_t and out_t:
                t1 = datetime.strptime(in_t[:19], "%Y-%m-%d %H:%M:%S")
                t2 = datetime.strptime(out_t[:19], "%Y-%m-%d %H:%M:%S")
                prod = "%.1f 分钟" % ((t2 - t1).total_seconds() / 60)
        except ValueError:
            prod = ""
        rows.append({
            "站位": st, "进站时间": in_t, "出站时间": out_t,
            "生产时间": prod, "机台号": items.get("机台号", ""),
            "头": items.get("头", ""),
            "Tray ID": items.get("Tray ID", "") or items.get("Tray ID(进)", ""),
            "穴位": items.get("穴位", "") or items.get("穴位(进)", ""),
        })
    rows.sort(key=lambda r: r["进站时间"] or "9999")
    return pd.DataFrame(rows, columns=[
        "站位", "进站时间", "出站时间", "生产时间", "机台号", "头",
        "Tray ID", "穴位"])


_ITEM_RE = re.compile(
    r"^(?P<station>.+?)_(?P<item>MC_Head_ID|MC_ID|Carrier_ID|Carrier_Pocket|"
    r"Carrier_Start_Time|Carrier_End_Time|Lot_ID_1|Lot_Start_Time|Lot_End_Time|"
    r"Start_Time|End_Time|Head_ID|Vendor|Tool_ID|Cavity_ID|Glue_Platform|"
    r"Platform|Shuttleno|Shuttlepos_X|Shuttlepos_Y|SNAP_MC_ID|SNAP_Carrier_ID|"
    r"SNAP_Lot_ID_1|Oven_MC_ID|Oven_Lot_ID_1|MC_Platform)$")


def _clean(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s in ("{}", "nan", "None", "") else s


def wide_to_stations(wide: Dict[str, object]) -> Tuple[Dict, List]:
    """宽表 dict → (基本信息, [(站位, 字段, 值), ...])。"""
    basic: Dict[str, str] = {}
    rows: List[Tuple[str, str, str]] = []
    for col, v in wide.items():
        col = str(col).strip()
        v = _clean(v)
        if not v:
            continue
        c = col[3:] if col.startswith("MI_") else col
        m = _ITEM_RE.match(c)
        if m:
            rows.append((m.group("station"), m.group("item"), v))
        else:
            if col in ("Serial_No", "pass_fail"):
                basic[col] = v
            else:
                basic[col] = v
    return basic, rows


def _first_nonempty(items) -> str:
    for v in items:
        v = _clean(v)
        if v:
            return v
    return ""


def process_table(wide: Dict[str, object],
                  station_trace: Optional[List[Tuple[str, str, str]]] = None
                  ) -> pd.DataFrame:
    """按制程顺序汇总各站:进站/出站/生产时间/机台号/头/Tray ID/穴位。

    只保留真正的制程站位(有 MC_ID/时间/Carrier/头 的站),材料组(FLEX/OIS/
    SENSOR…仅有 lot/Vendor)归基本信息,不进制程表。
    """
    stations: Dict[str, Dict[str, str]] = {}
    for col, v in wide.items():
        c = col[3:] if str(col).startswith("MI_") else str(col)
        m = _ITEM_RE.match(c)
        if not m:
            continue
        st, item = m.group("station"), m.group("item")
        stations.setdefault(st, {})[item] = _clean(v)

    rows = []
    for st, items in stations.items():
        in_t = _first_nonempty(items.get(k) for k in (
            "Start_Time", "Carrier_Start_Time", "Lot_Start_Time"))
        out_t = _first_nonempty(items.get(k) for k in (
            "End_Time", "Carrier_End_Time", "Lot_End_Time"))
        mc = _first_nonempty(items.get(k) for k in (
            "MC_ID", "SNAP_MC_ID", "Oven_MC_ID"))
        head = _first_nonempty(items.get(k) for k in (
            "MC_Head_ID", "Head_ID", "head", "HEAD_NUMBER", "Platform"))
        tray = _first_nonempty(items.get(k) for k in (
            "Carrier_ID", "Transit_Tray_ID"))
        pocket = _first_nonempty(items.get(k) for k in (
            "Carrier_Pocket", "Transit_Tray_Pocket"))
        # 只保留真正的制程站位
        if not (mc or in_t or out_t or head or tray or pocket):
            continue
        prod = ""
        try:
            if in_t and out_t:
                t1 = datetime.strptime(in_t[:19], "%Y-%m-%d %H:%M:%S")
                t2 = datetime.strptime(out_t[:19], "%Y-%m-%d %H:%M:%S")
                prod = "%.1f 分钟" % ((t2 - t1).total_seconds() / 60)
        except ValueError:
            prod = ""
        rows.append({"站位": st, "进站时间": in_t, "出站时间": out_t,
                     "生产时间": prod, "机台号": mc, "头": head,
                     "Tray ID": tray, "穴位": pocket})

    # SFC 站位轨迹补充进站时间(组件绑定保留到基本信息)
    if station_trace:
        tr = {st: t for st, f, t in station_trace if f == "进站时间"}
        seen = {r["站位"] for r in rows}
        for st, t in tr.items():
            if st not in seen:
                rows.append({"站位": st, "进站时间": t, "出站时间": "",
                             "生产时间": "", "机台号": "", "头": "",
                             "Tray ID": "", "穴位": ""})
        for r in rows:
            if r["站位"] in tr and not r["进站时间"]:
                r["进站时间"] = tr[r["站位"]]

    rows.sort(key=lambda r: r["进站时间"] or "9999")
    return pd.DataFrame(rows, columns=[
        "站位", "进站时间", "出站时间", "生产时间", "机台号", "头",
        "Tray ID", "穴位"])


def query_sn_info(project: str, sn: str, token: str = "",
                  userid: str = "", password: str = "") -> Optional[Dict]:
    """查询单个 SN 的站位信息(C4 优先,SFC 补齐)。返回 {basic, rows, process}。

    1. C4 直连 Greenplum(t_<专案>_eoldata/foldata)→ 宽表 → 制程表
    1b. 数据中心 API(Load_DataCenterData)兜底
    2. SFC 补齐:snsearch 站位轨迹(进站时间/组件)合并进制程表;
       SN Track 基本信息(传感器/批号/供应商/Tray…)补入 basic
    """
    wide: Dict[str, object] = {}
    basic: Dict[str, str] = {}
    rows: List[Tuple[str, str, str]] = []
    try:
        gp_wide = _gp_query_sn(project, sn)
        if gp_wide:
            wide = gp_wide
            basic, rows = wide_to_stations(wide)
    except Exception:
        gp_wide = None
    if project in LDC_PROJECTS:
        if not wide and token:
            # 数据中心 API 兜底(Load_DataCenterData 覆盖的项目)
            client = LdcClient(token, project)
            try:
                df = client.download_all([sn])
                if not df.empty and "Serial_No" in df.columns \
                        and (df["Serial_No"] == sn).any():
                    wide = df[df["Serial_No"] == sn].iloc[0].to_dict()
                    basic, rows = wide_to_stations(wide)
            except Exception:
                pass

    # SFC 补齐(项目在 SFC 门户且有账号)
    sfc_client = None
    if userid:
        from sfc_app007 import SfcPortal
        from sfc_app007 import PROJECTS as SFC_PROJECTS
        # LDC 显示名(ATW-E/BOI-T/CHS-T)映射到 SFC 项目 id(APP003/APO006/APO009)
        sfc_project = project
        if project in LDC_PROJECTS:
            sfc_project = LDC_PROJECTS[project][1]
        if sfc_project not in SFC_PROJECTS:
            sfc_client = None
        else:
            try:
                sfc_client = SfcPortal(userid, password, project=sfc_project)
                if not sfc_client.login():
                    sfc_client = None
            except Exception:
                sfc_client = None

    trace: List[Tuple[str, str, str]] = []
    if sfc_client is not None:
        try:
            serin = sfc_client.sntrack(sn)
            srec = serin.get("record", {})
            if srec:
                sbasic, _srows = wide_to_stations(srec)
                for k, v in sbasic.items():
                    if k not in basic:
                        basic[k] = v
        except Exception:
            pass
        trace = _sfc_station_trace(sfc_client, sn)
        rows = trace + rows

    if not wide and not basic and not trace:
        return None
    proc = _gp_process_table(wide) if gp_wide else \
        process_table(wide, trace if sfc_client is not None else None)
    return {"basic": basic, "rows": rows, "process": proc}


def query_sn_info_from_csv(csv_path: str, sn: str) -> Optional[Dict]:
    """从 C4 导出的 Serin CSV(527列,全字段)读取单个 SN 的制程信息。

    C4 直连导出包含进/出站时间、生产时间、机台号、头、Tray ID、穴位,
    比数据中心接口更全(数据中心无 Tray ID、出站时间不全)。
    """
    import csv as _csv
    with open(csv_path, encoding="utf-8-sig") as f:
        rd = _csv.reader(f)
        hdr = next(rd)
        sn_col = "Serial_No"
        if sn_col not in hdr:
            for c in hdr:
                if c.strip().lower() in ("sn", "serial_no", "serial no"):
                    sn_col = c
                    break
        for row in rd:
            if len(row) < len(hdr):
                row = row + [""] * (len(hdr) - len(row))
            if row[hdr.index(sn_col)].strip() == sn:
                wide = dict(zip(hdr, row))
                basic, rows = wide_to_stations(wide)
                proc = process_table(wide)
                return {"basic": basic, "rows": rows, "process": proc}
    return None


def _sfc_station_trace(client, sn: str) -> List[Tuple[str, str, str]]:
    """从 SFC report/snsearch.aspx 解析站位轨迹与组件绑定。"""
    import requests as _req
    url = "http://10.151.128.45:8081/report/snsearch.aspx"
    try:
        r = client.session.get(url, timeout=20)
        fv = {}
        for m in re.finditer(r'<input\b[^>]*>', r.text, re.I):
            nm = re.search(r'name="([^"]*)"', m.group(0))
            if not nm:
                continue
            name = nm.group(1)
            if name in ("__EVENTTARGET", "__EVENTARGUMENT", "__LASTFOCUS"):
                continue
            tp = re.search(r'type="([^"]*)"', m.group(0))
            typ = tp.group(1).lower() if tp else ""
            if typ in ("submit", "button", "image"):
                continue
            vl = re.search(r'value="([^"]*)"', m.group(0))
            fv[name] = vl.group(1) if vl else ""
        body = dict(fv)
        body.update({"selectradio": "1", "sntextbox": sn,
                     "__EVENTTARGET": "", "Button1": "Search"})
        r = client.session.post(url, data=body, timeout=60)
        html = r.text
    except Exception:
        return []
    out: List[Tuple[str, str, str]] = []
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', html, re.I | re.S):
        tds = [re.sub(r"<[^>]+>", "", td).strip()
               for td in re.findall(r'<td\b[^>]*>(.*?)</td>',
                                    row, re.I | re.S)]
        if len(tds) == 2 and tds[1] and re.match(
                r"^\d{4}-\d{2}-\d{2}", tds[1]):
            out.append((tds[0], "进站时间", tds[1]))
        elif len(tds) == 4 and tds[1] and tds[2]:
            out.append((tds[3] or "绑定", tds[2], tds[1]))
    return out


def rows_to_df(basic: Dict[str, str], rows: List[Tuple[str, str, str]]
               ) -> pd.DataFrame:
    """组装展示 DataFrame:基本信息在前,站位明细在后。"""
    out = []
    for k, v in basic.items():
        out.append(["基本信息", k, v])
    for st, it, v in rows:
        out.append([st, it, v])
    return pd.DataFrame(out, columns=["站位", "字段", "值"])


if __name__ == "__main__":
    import json
    ap = __import__("argparse").ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--sn", required=True)
    ap.add_argument("--token", default="")
    ap.add_argument("--user", default="F1679837")
    ap.add_argument("--password", default="Szlh202607")
    args = ap.parse_args()
    token = args.token
    if not token:
        base = __import__("pathlib").Path(sys.executable).resolve().parent \
            if getattr(sys, "frozen", False) \
            else __import__("pathlib").Path(__file__).resolve().parent
        cfg = json.loads((base / "config.json").read_text(encoding="utf-8-sig"))
        token = cfg.get("c4", {}).get("token", "")
    r = query_sn_info(args.project, args.sn, token,
                      args.user, args.password)
    if r is None:
        print("查无数据")
    else:
        proc = r["process"]
        print("=== 制程信息(按进站顺序) ===")
        print(proc.to_string(index=False) if not proc.empty else "(无)")
        print("\n=== 基本信息 ===")
        for k, v in r["basic"].items():
            print("  %-24s %s" % (k, str(v)[:60]))
