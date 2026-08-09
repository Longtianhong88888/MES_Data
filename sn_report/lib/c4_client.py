"""战情中心/C4+ 批量数据接口客户端(参考 BOI-T 共性分析工具)。

接口:
    POST http://10.151.128.35:8095/api/MachineParameter/GetInformationDT
    Authorization: Bearer <JWT>
    Body(JSON): type=8S01 / plantID / Device / ColumnSelect=[列ID]
                + snlist=[...] 或 start_time / end_time
响应:
    resultvalue.columns[] -> {name, columnID, ...}
    resultvalue.rows[]    -> {time/Serial_No..., columnID: value}

用于一次性批量拉取每个 SN 在各站位的 机台号/载板号/穴位号/进站时间 等列,
列清单在 sn_report/config.json 的 c4.columns 里配置(每行:station/mc/carrier/pocket/start_time)。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from .models import SnRecord, StationRecord


class C4Client:
    def __init__(
        self,
        url: str,
        token: str,
        plant_id: str,
        device: str,
        type_: str = "8S01",
        extra_params: Optional[Dict[str, Any]] = None,
    ):
        self.url = url
        self.token = token
        self.plant_id = plant_id
        self.device = device
        self.type = type_
        self.extra_params = extra_params or {}
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            }
        )

    def fetch(
        self,
        columns: List[str],
        sns: Optional[List[str]] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """拉取指定列。按 SN 列表查(snlist)或按时间窗查(start_time/end_time)。"""
        if not columns:
            return []
        payload: Dict[str, Any] = {
            "type": self.type,
            "plantID": self.plant_id,
            "Device": self.device,
            "ColumnSelect": columns,
        }
        if sns:
            payload["snlist"] = sns
        if start and end:
            payload["start_time"] = start
            payload["end_time"] = end
        payload.update(self.extra_params)

        resp = self.session.post(self.url, data=json.dumps(payload), timeout=180)
        resp.raise_for_status()
        return self._parse(resp.json())

    @staticmethod
    def _parse(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """把 resultvalue 展开为按 SN 的字典列表。"""
        result = data.get("resultvalue") or data
        columns = result.get("columns") or []
        col_id_to_name = {
            str(c.get("columnID")): str(c.get("name")) for c in columns if c.get("columnID")
        }
        rows = result.get("rows") or []
        records: List[Dict[str, Any]] = []
        for row in rows:
            record: Dict[str, Any] = {}
            for k, v in row.items():
                if k == "columnID":
                    continue
                if k == "value":
                    continue
                record[str(k)] = v
            # 若行内是 columnID->value 的平铺结构,还原列名
            cid = row.get("columnID")
            if cid and "value" in row:
                record[col_id_to_name.get(str(cid), str(cid))] = row["value"]
            records.append(record)
        return records

    def apply_to_records(
        self, records: List[SnRecord], columns_cfg: List[Dict[str, str]]
    ) -> None:
        """把配置的 机台/载板/穴位/时间 列合并进 SN 记录的站位里。"""
        # 收集所有需要下载的列
        col_map: Dict[str, str] = {}  # 原始列名 -> 用途(站的字段)
        for item in columns_cfg:
            station = item.get("station", "")
            for key in ("mc", "carrier", "pocket", "start_time"):
                col = item.get(key, "")
                if col:
                    col_map[col] = key
        if not col_map:
            return

        sns = [r.sn for r in records]
        data = self.fetch(list(col_map.keys()), sns=sns)

        # 按 SN 索引
        by_sn: Dict[str, Dict[str, Any]] = {}
        for row in data:
            sn = row.get("sn") or row.get("Serial_No") or row.get("serial_no")
            if sn:
                by_sn.setdefault(str(sn), {}).update(row)

        for rec in records:
            row = by_sn.get(rec.sn)
            if not row:
                continue
            for item in columns_cfg:
                station_name = item.get("station", "")
                st = self._find_station(rec, station_name)
                for key, col in (
                    ("mc", item.get("mc", "")),
                    ("carrier", item.get("carrier", "")),
                    ("pocket", item.get("pocket", "")),
                    ("time", item.get("start_time", "")),
                ):
                    if col and row.get(col):
                        setattr(st, key, str(row[col]))

    @staticmethod
    def _find_station(rec: SnRecord, name: str) -> StationRecord:
        for st in rec.stations:
            if st.station == name:
                return st
        st = StationRecord(station=name)
        rec.stations.append(st)
        return st

    def save_csv(self, records: List[Dict[str, Any]], path: Path) -> None:
        if not records:
            return
        keys = sorted({k for r in records for k in r.keys()})
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(records)
