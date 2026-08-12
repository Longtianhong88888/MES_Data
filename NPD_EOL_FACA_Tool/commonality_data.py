#!/usr/bin/env python3
"""Load_DataCenterData 数据加载:输入 Fail SN 列表 → 全量共性 DataFrame。

按专案(project→device/code 映射)用 ID 模式批量(≤50)下载 8 个 queryGroup
(ID_ALL/mcid_1/01_material/02_wafer_item/01_carrierxy/starttime_1/
vendorlot_1/headid_5),按 Serial_No 合并成一张表,供 commonality_analysis 使用。

用法:
    python commonality_data.py --project BOI-T --sns fail_sns.txt
        --out output/BOI_commonality_data.csv
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import pandas as pd
import requests

requests.packages.urllib3.disable_warnings()

LDC_URL = "http://10.151.128.35:8095/api/MachineTestHandle/Load_DataCenterData"
PLANT = "8S01"

# project(UI 名) -> (device, code) 映射(来自线上版 SN.xlsx project 表)
PROJECT_MAP: Dict[str, Tuple[str, str]] = {
    "BOI-T": ("BOI", "APO006"),
    "ATW-D": ("ATW", "APO007"),
    "ATW-E": ("ATW", "APP003"),
    "CHS-T": ("CHS26", "APO009"),
    "CHS-V": ("CHS26", "APP001"),
    "CHS-E": ("CHS26", "APP002"),
    "CHS-Y": ("CHS26", "APP005"),
    "CHS-S": ("CHS", "APN004"),
    "CHS-K": ("CHS", "APO003"),
    "CHS-W": ("CHS", "APO004"),
}

GROUPS = ["ID_ALL", "mcid_1", "01_material", "02_wafer_item",
          "01_carrierxy", "starttime_1", "starttime_2",
          "vendorlot_1", "headid_5"]


class LdcClient:
    """Load_DataCenterData 客户端(ID 模式,≤50 SN/次)。"""

    def __init__(self, token: str, project: str):
        if project not in PROJECT_MAP:
            raise ValueError("项目未配置映射: %s(可用 %s)"
                             % (project, list(PROJECT_MAP)))
        self.token = token
        self.project = project
        self.device, self.code = PROJECT_MAP[project]

    def download_group(self, group: str, sns: List[str],
                       batch: int = 50) -> pd.DataFrame:
        """按组下载,返回 DataFrame(列=接口返回列名)。"""
        frames = []
        for i in range(0, len(sns), batch):
            chunk = sns[i:i + batch]
            params = {
                "plant": PLANT, "project": self.device, "deviceno": self.code,
                "queryType": "ID", "queryGroup": group, "queryKey": "SN",
                "snList": ",".join(chunk),
            }
            qs = "&".join(
                f"{quote(str(k))}={quote(str(v), safe=':-')}"
                for k, v in params.items())
            qs = (qs.replace("%2C", ",").replace("%2B", "+")
                  .replace("%3A", ":").replace("%20", " "))
            r = requests.post(
                LDC_URL + "?" + qs,
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + self.token},
                timeout=120)
            r.raise_for_status()
            d = r.json()
            rv = d.get("resultvalue") or {}
            cols = [c.get("name") for c in (rv.get("columns") or [])]
            rows = []
            for row in rv.get("rows") or []:
                rows.append([c.get("value") for c in row])
            frames.append(pd.DataFrame(rows, columns=cols))
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def download_all(self, sns: List[str],
                     groups: Optional[List[str]] = None) -> pd.DataFrame:
        """下载 8 组并按 Serial_No 合并成一张表。"""
        sns = [s for s in dict.fromkeys(sns) if s]
        groups = groups or GROUPS
        merged: Optional[pd.DataFrame] = None
        for g in groups:
            df = self.download_group(g, sns)
            if df.empty:
                continue
            if merged is None:
                merged = df
            else:
                # 以 Serial_No 外连接;共享列(Part_SN 等)保留首个
                merge_cols = [c for c in merged.columns if c == "Serial_No"]
                merged = merged.merge(
                    df, on=merge_cols, how="outer",
                    suffixes=("", "_dup"))
                dup = [c for c in merged.columns if c.endswith("_dup")]
                merged = merged.drop(columns=dup)
        if merged is None:
            return pd.DataFrame()
        return merged

    # ---------- Time 模式(全量人口,共性分析推荐) ----------
    def download_group_time(self, group: str, date: str) -> pd.DataFrame:
        """按天导出(≤1 天),返回 DataFrame(从 CSV URL 下载)。"""
        params = {
            "plant": PLANT, "project": self.device, "deviceno": self.code,
            "queryType": "Time", "queryGroup": group,
            "startTime": date + " 00:00:00", "endTime": date + " 23:59:59",
        }
        qs = "&".join(
            f"{quote(str(k))}={quote(str(v), safe=':-')}"
            for k, v in params.items())
        qs = (qs.replace("%2C", ",").replace("%2B", "+")
              .replace("%3A", ":").replace("%20", " "))
        r = requests.post(
            LDC_URL + "?" + qs,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.token},
            timeout=60)
        rv = r.json().get("resultvalue") or {}
        rows = rv.get("rows") or []
        if not rows:
            return pd.DataFrame()
        url = rows[0][0]["value"]
        if not url or str(url).strip() in ("{}", "") \
                or not str(url).startswith("http"):
            # 服务端未生成导出文件(或返回占位),跳过该天
            return pd.DataFrame()
        rr = requests.get(url, timeout=180)
        return pd.read_csv(
            __import__("io").StringIO(
                rr.content.decode("utf-8-sig", "replace")),
            low_memory=False, dtype=str)

    def fail_dates(self, sns: List[str]) -> List[str]:
        """查 Fail SN 的 STB 日期(升序)。"""
        df = self.download_group("ID_ALL", sns)
        if df.empty or "STB_Start_Time" not in df.columns:
            return []
        dates = sorted({str(t)[:10] for t in df["STB_Start_Time"] if t})
        return dates

    def load_population_for_analyze(
        self, sns: List[str], dates: Optional[List[str]] = None,
        groups: Optional[List[str]] = None, pass_sample: int = 3000,
        seed: int = 42, progress: Optional[Any] = None
    ) -> pd.DataFrame:
        """构建共性分析表:Fail 走 ID 模式(保证完整),Pass 从 Time 导出采样。

        注意:Time 导出会漏掉部分 SN(时标不同),不能用来取 Fail 因子;
        ID 模式保证 Fail 因子完整。Pass 从 Time 导出采样(本来就在导出里)。
        返回 DataFrame(含 pass_fail 列)。
        """
        groups = groups or ["mcid_1", "01_material", "01_carrierxy",
                            "headid_5", "starttime_1", "starttime_2",
                            "vendorlot_1", "02_wafer_item"]
        if dates is None:
            dates = self.fail_dates(sns)
        if not dates:
            raise ValueError("无法确定 Fail 日期")
        fails = set(sns)
        n_dates = len(dates)
        # 进度单位:起始1 + Fail组9 + Pass采样n + Pass组9n + 合并1
        total_units = 11 + 10 * n_dates
        done_units = 0

        def tick(msg: str) -> None:
            nonlocal done_units
            done_units += 1
            if progress:
                progress(min(done_units, total_units), total_units, msg)

        # 1) Fail 因子:ID 模式(8 组,保证完整)
        tick("Fail 因子(ID 模式)下载开始")
        fail_parts: List[pd.DataFrame] = []
        for g in ["ID_ALL"] + groups:
            df = self.download_group(g, sorted(fails))
            tick("Fail 组 %s 完成" % g)
            if not df.empty:
                fail_parts.append(df)
        fail_df = fail_parts[0]
        for df in fail_parts[1:]:
            fail_df = fail_df.merge(
                df, on=[c for c in fail_df.columns if c == "Serial_No"],
                how="outer", suffixes=("", "_dup"))
            fail_df = fail_df.drop(
                columns=[c for c in fail_df.columns if c.endswith("_dup")])

        # 2) Pass 采样:Time 导出按日采样
        rnd = random.Random(seed)
        pass_sns: List[str] = []
        for date in dates:
            df = self.download_group_time("ID_ALL", date)
            tick("Pass 采样 %s 完成" % date)
            if "Serial_No" in df.columns:
                cand = [s for s in df["Serial_No"].tolist()
                        if s not in fails]
                n = min(pass_sample, len(cand))
                pass_sns.extend(rnd.sample(cand, n))
        pass_sns = list(dict.fromkeys(pass_sns))
        if not pass_sns:
            raise ValueError("Pass 采样为空")

        # 3) Pass 因子:Time 导出过滤到采样集合
        parts: List[pd.DataFrame] = []
        for date in dates:
            for g in ["ID_ALL"] + groups:
                df = self.download_group_time(g, date)
                tick("Pass 组 %s @ %s 完成" % (g, date))
                if df.empty or "Serial_No" not in df.columns:
                    continue
                df = df[df["Serial_No"].isin(pass_sns)].set_index("Serial_No")
                df = df.loc[~df.index.duplicated(keep="first")]
                parts.append(df)

        pass_df = pd.concat(parts, axis=1)
        pass_df = pass_df.loc[~pass_df.index.duplicated(keep="first")].reset_index()

        # 4) 合并 Fail + Pass,统一列,打标签
        fail_df = fail_df.loc[:, ~fail_df.columns.duplicated(keep="first")]
        pass_df = pass_df.loc[:, ~pass_df.columns.duplicated(keep="first")]
        merged = pd.concat([fail_df, pass_df], ignore_index=True, sort=False)
        # 去重列名(跨组同名列如 STB_Start_Time/Part_SN,保留首个)
        merged = merged.loc[:, ~merged.columns.duplicated(keep="first")]
        if "Serial_No" not in merged.columns:
            raise ValueError("合并后缺少 Serial_No 列")
        tick("合并 Fail+Pass 完成")
        merged["pass_fail"] = merged["Serial_No"].map(
            lambda s: "fail" if str(s) in fails else "pass")
        return merged


def load_fail_sns(path: Path) -> List[str]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    return [ln.strip() for ln in lines if ln.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, choices=list(PROJECT_MAP))
    ap.add_argument("--sns", required=True, help="Fail SN 文件(每行一个)")
    ap.add_argument("--out", default="output/commonality_data.csv")
    ap.add_argument("--token", default="")
    ap.add_argument("--analyze", action="store_true",
                    help="下载后直接跑共性分析 Top20")
    ap.add_argument("--pass-sample", type=int, default=3000,
                    help="每个 Fail 日期采样的 Pass 数量(默认 3000)")
    ap.add_argument("--dates", default="",
                    help="指定日期(逗号分隔 yyyy-mm-dd);缺省按 Fail SN 自动推断")
    ap.add_argument("--coverage-penalty", type=float, default=1.0,
                    help="覆盖率降权指数(默认 1.0,越大越压制 100% 覆盖项)")
    ap.add_argument("--coverage-threshold", type=float, default=0.8,
                    help="覆盖率降权阈值(默认 0.8,超过才惩罚)")
    ap.add_argument("--rules", action="store_true", help="输出第二层组合规则")
    ap.add_argument("--min-support", type=float, default=0.15)
    ap.add_argument("--min-lift", type=float, default=1.5)
    ap.add_argument("--mode", default="mp", choices=["mp", "npi", "auto"],
                    help="mp=量产(默认);npi=试产小样本;auto=按Fail数自动")
    args = ap.parse_args()

    token = args.token
    if not token:
        base = Path(sys.executable).resolve().parent if getattr(
            sys, "frozen", False) else Path(__file__).resolve().parent
        cfg = json.loads((base / "config.json").read_text(encoding="utf-8-sig"))
        token = cfg.get("c4", {}).get("token", "")
    sns = load_fail_sns(Path(args.sns))
    print("项目 %s(device=%s,code=%s),Fail SN %d 个" % (
        args.project, PROJECT_MAP[args.project][0],
        PROJECT_MAP[args.project][1], len(sns)), flush=True)
    client = LdcClient(token, args.project)
    out = Path(args.out)
    csv_path = out.with_suffix(".csv") if out.suffix.lower() == ".xlsx" else out
    xlsx = out.with_suffix(".xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.analyze:
        dates = [d.strip() for d in args.dates.split(",") if d.strip()] or None
        df = client.load_population_for_analyze(
            sns, dates=dates, pass_sample=args.pass_sample)
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print("合并表: %d 行 x %d 列 -> %s" % (len(df), len(df.columns), csv_path),
              flush=True)
        print("Fail: %d  Pass: %d" % (
            (df["pass_fail"].str.lower() == "fail").sum(),
            (df["pass_fail"].str.lower() == "pass").sum()), flush=True)
        from commonality_analysis import (analyze_commonality, apriori_rules,
                                          write_styled_excel)
        rows, _ = analyze_commonality(
            df, min_fail=3, fail_values=("fail", "Fail"),
            coverage_penalty=args.coverage_penalty,
            coverage_threshold=args.coverage_threshold,
            mode=args.mode)
        if rows:
            top = pd.DataFrame(rows).head(20)
            print("\n=== 共性 Top 20 ===\n")
            print(top[["dimension", "value", "fail_count", "unit_count",
                      "fail_rate", "lift", "fail_ratio", "p_adj", "score"]]
                  .to_string(index=False))
            rules = pd.DataFrame()
            if args.rules:
                rules = apriori_rules(
                    df, fail_col="pass_fail",
                    min_support=args.min_support, min_lift=args.min_lift)
            write_styled_excel(xlsx, top,
                               rules if not rules.empty else None,
                               mode=args.mode)
            print("\n保存: %s(重点红/次重点橙,栏宽自适应)" % xlsx)
            if args.rules:
                if not rules.empty:
                    print("\n=== 组合规则(第二层) ===\n")
                    print(rules.to_string(index=False))
                else:
                    print("\n无满足条件的组合规则")
    else:
        df = client.download_all(sns)
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print("合并表: %d 行 x %d 列 -> %s" % (len(df), len(df.columns), csv_path),
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
