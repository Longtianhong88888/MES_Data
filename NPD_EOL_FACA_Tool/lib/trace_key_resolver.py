"""Module SN → 每站照片查询 key 解析器。

原理:一次 C4 GetInformationDT(snlist + 各站 carrier/pocket/lot/mc/时间列)
即可返回每个 SN 在每个站位的载具/穴位/批号/机台/进站时间,
照片查询按站的 Condition 就从这里取(见 config.json 的 c4.columns 与 img_stations_all)。

用法:
    client = C4Client(url, token, plant_id, device)
    resolver = TraceKeyResolver(client, cfg["c4"]["columns"])
    key_map = resolver.resolve(sns)      # {sn: {station: {carrier,pocket,lot,...}}}
"""

from __future__ import annotations

from typing import Any, Dict, List

from .models import SnRecord


class TraceKeyResolver:
    """把 C4 全制程追溯列解析成"每 SN × 每站"的照片查询 key。"""

    def __init__(self, client: Any, columns_cfg: List[Dict[str, str]]) -> None:
        self.client = client
        self.columns_cfg = columns_cfg

    def _collect_columns(self) -> List[str]:
        cols: List[str] = []
        for item in self.columns_cfg:
            for k in ("mc", "carrier", "pocket", "lot", "start_time", "end_time"):
                c = str(item.get(k, "") or "").strip()
                if c and c not in cols:
                    cols.append(c)
        return cols

    @staticmethod
    def _row_sn(row: Dict[str, Any]) -> str:
        for k in ("sn", "Serial_No", "serial_no", "Serial_No_18"):
            v = row.get(k)
            if v not in (None, ""):
                return str(v)
        return ""

    def resolve(self, sns: List[str]) -> Dict[str, Dict[str, Dict[str, str]]]:
        """返回 {sn: {station: {mc, carrier, pocket, lot, start_time, end_time}}}。"""
        cols = self._collect_columns()
        if not cols:
            return {}
        rows = self.client.fetch(cols, sns=sns) if cols else []

        by_sn: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            sn = self._row_sn(row)
            if sn:
                by_sn.setdefault(sn, {}).update(row)

        result: Dict[str, Dict[str, Dict[str, str]]] = {}
        for sn in sns:
            rec = by_sn.get(str(sn), {})
            per_station: Dict[str, Dict[str, str]] = {}
            for item in self.columns_cfg:
                st = str(item.get("station", "") or "").strip()
                if not st:
                    continue
                per_station[st] = {
                    "mc": str(rec.get(str(item.get("mc", "") or ""), "") or ""),
                    "carrier": str(rec.get(str(item.get("carrier", "") or ""), "") or ""),
                    "pocket": str(rec.get(str(item.get("pocket", "") or ""), "") or ""),
                    "lot": str(rec.get(str(item.get("lot", "") or ""), "") or ""),
                    "start_time": str(rec.get(str(item.get("start_time", "") or ""), "") or ""),
                    "end_time": str(rec.get(str(item.get("end_time", "") or ""), "") or ""),
                }
            result[sn] = per_station
        return result

    def resolve_to_records(self, records: List[SnRecord]) -> Dict[str, Dict[str, Dict[str, str]]]:
        """解析并写回每条 SnRecord.trace_keys。"""
        sns = [r.sn for r in records]
        key_map = self.resolve(sns)
        for rec in records:
            rec.trace_keys = key_map.get(rec.sn, {})
        return key_map
