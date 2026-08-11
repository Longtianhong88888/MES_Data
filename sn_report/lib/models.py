"""数据模型:一个 SN 的全部追溯信息。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ImageRecord:
    """一张 PR/MC 图片的记录(签名 URL + 本地路径)。"""

    station: str = ""
    img_type: str = ""
    url: str = ""
    local_path: str = ""

    @property
    def filename(self) -> str:
        if self.local_path:
            return self.local_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        return ""


@dataclass
class StationRecord:
    """单个站位:进站时间 / 机台号 / 载板号 / 穴位号 / 图片。"""

    station: str = ""
    time: str = ""
    mc_id: str = ""
    carrier: str = ""
    pocket: str = ""
    head_id: str = ""
    extra: Dict[str, str] = field(default_factory=dict)
    images: List[ImageRecord] = field(default_factory=list)

    def image_count(self) -> int:
        return len(self.images)


@dataclass
class ComponentRecord:
    """组件绑定(sensor / VCM / lens / stiffener / tape 等)。"""

    material: str = ""
    id: str = ""
    name: str = ""
    station: str = ""


@dataclass
class ConsumableRecord:
    """耗材记录。"""

    material: str = ""
    lot: str = ""
    name: str = ""
    station: str = ""


@dataclass
class SnRecord:
    """一个 SN 的全部追溯信息。"""

    sn: str
    summary: Dict[str, str] = field(default_factory=dict)
    stations: List[StationRecord] = field(default_factory=list)
    components: List[ComponentRecord] = field(default_factory=list)
    consumables: List[ConsumableRecord] = field(default_factory=list)
    sensor_id: str = ""
    flex_id: str = ""
    trace_keys: Dict[str, Dict[str, str]] = field(default_factory=dict)
    acf_excels: List[str] = field(default_factory=list)
    raw_tables: List[Dict[str, Any]] = field(default_factory=list)
    raw_files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def all_images(self) -> List[ImageRecord]:
        imgs: List[ImageRecord] = []
        for st in self.stations:
            imgs.extend(st.images)
        return imgs

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sn": self.sn,
            "summary": self.summary,
            "stations": [st.__dict__ for st in self.stations],
            "components": [c.__dict__ for c in self.components],
            "consumables": [c.__dict__ for c in self.consumables],
            "sensor_id": self.sensor_id,
            "flex_id": self.flex_id,
            "errors": self.errors,
        }
