#!/usr/bin/env python3
"""SN_Report 图形界面(Greenplum Serin 照片一键下载)。

功能:
- 文本框输入 SN(可多个,逗号/换行分隔)
- 选择 SN 文件(.txt/.csv/.xlsx 第一列)
- 一键查询 EOL+FOL 全部站位照片并下载
- 实时日志 + 下载进度
"""
from __future__ import annotations

import json
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(BASE_DIR))


def _load_db_config() -> dict:
    """从 exe 同目录 config.json 读数据库连接(不显示在 UI);默认内置。"""
    cfg_path = BASE_DIR / "config.json"
    defaults = {
        "host": "10.151.130.202",
        "port": 5432,
        "database": "wwwgpdw",
        "user": "gpdwdev",
        "password": "Altus2014",
    }
    cfg = dict(defaults)
    if cfg_path.exists():
        try:
            user_cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            cfg.update({k: user_cfg[k] for k in defaults if k in user_cfg})
        except Exception:
            pass
    return cfg


DB_CFG = _load_db_config()

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtCore import Qt
from PyQt5.QtCore import QUrl
from PyQt5.QtCore import QDate
from PyQt5.QtGui import QIcon
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QTextEdit, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QProgressBar, QMainWindow, QStatusBar, QInputDialog, QDialog, QCheckBox,
    QComboBox, QTabWidget, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QDateEdit, QSpinBox, QListWidget, QListWidgetItem, QScrollArea, QFrame,
)

from run_gp_download import (
    GreenplumSerin, extract_images, try_download,
    DOMAIN_IP_MAP, load_sn_list, download_with_sfc_fallback,
    _load_gp_sfc_map,
)
from excel_report import build_excel
from apple_style import APPLE_QSS, build_qss, C_BG, C_SUB, card, hint
from c4_auth import C4Auth
from sfc_app007 import SfcPortal, PROJECTS as SFC_PROJECTS
from sfc_app007 import collect_sn as sfc_collect_sn
from commonality_data import LdcClient, PROJECT_MAP as LDC_PROJECTS
from commonality_analysis import analyze_commonality


def window_target_size(ratio: float = 0.8) -> tuple:
    """主窗口占屏幕可用区域 80%(与 MC_LogAnalysis 一致)。"""
    screen = QApplication.primaryScreen()
    if screen is None:
        return 980, 720
    geo = screen.availableGeometry()
    w = max(860, int(geo.width() * ratio))
    h = max(640, int(geo.height() * ratio))
    return w, h


class DownloadWorker(QThread):
    """后台线程执行下载,避免界面卡死。"""
    log_line = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    status = pyqtSignal(str)
    ask_sfc = pyqtSignal(int)  # 直连失效数量,询问是否从 SFC 补齐
    done = pyqtSignal(dict, str)  # (result, excel_path)

    def __init__(self, sns: List[str], download_dir: Path,
                 host: str, port: int, database: str, user: str, password: str,
                 project: str = "", sfc_user: str = "",
                 sfc_password: str = ""):
        super().__init__()
        self.sns = sns
        self.download_dir = download_dir
        self.project = project
        self.sfc_user = sfc_user
        self.sfc_password = sfc_password
        self.gp = GreenplumSerin(host=host, port=port, database=database,
                                 user=user, password=password)
        self._stop = False
        self._sfc_choice = False
        self._sfc_event = threading.Event()

    def stop(self):
        self._stop = True
        self._sfc_event.set()  # 若正等待用户选择,直接放行(视为不补齐)

    def set_sfc_choice(self, yes: bool):
        self._sfc_choice = bool(yes)
        self._sfc_event.set()

    def emit(self, msg: str):
        self.log_line.emit(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def run(self):
        result = {"sn_count": len(self.sns), "total": 0, "downloaded": 0,
                  "failed": 0, "sns": {}}
        excel_path = ""
        # 阶段A: C4(Greenplum)直连查询 + 下载,记录失效链接
        failed_items: List[tuple] = []  # (sn, used_project, part, key, sn_hint, img, dest)
        try:
            self.status.emit("正在连接 Greenplum 数据库...")
            self.gp.connect()
            self.emit(f"Greenplum 连接成功: {self.gp.host}:{self.gp.port}/{self.gp.database}")
            self.status.emit("数据库已连接,正在识别专案...")
            self.projects = self.gp.list_projects()
            if not self.sfc_user:
                self.emit("提示: 未登录 SFC,失效链接将无法补齐"
                          "(可在 文件→重新登录 后重试)")
            if self.project:
                self.emit(f"专案: {self.project}")
            else:
                self.emit(f"专案: 自动识别(共 {len(self.projects)} 个专案)")
        except Exception as exc:  # noqa: BLE001
            self.emit(f"Greenplum 连接失败: {exc}")
            self.status.emit("连接失败")
            self.done.emit(result, "")
            return

        for i, sn in enumerate(self.sns, start=1):
            if self._stop:
                break
            self.status.emit(f"处理 SN {i}/{len(self.sns)}: {sn}")
            self.emit(f"[{i}/{len(self.sns)}] === SN: {sn} ===")
            per_sn = {"sn": sn, "eol": [], "fol": [], "count": 0,
                      "downloaded": 0, "failed": 0}
            eol = None
            used_project = self.project
            if self.project:
                try:
                    eol = self.gp.eol_by_sn(sn, self.project)
                except Exception as exc:  # noqa: BLE001
                    self.emit(f"  EOL 查询失败: {str(exc)[:100]}")
            else:
                for proj in self.projects:
                    if self._stop:
                        break
                    try:
                        eol = self.gp.eol_by_sn(sn, proj)
                        if eol:
                            used_project = proj
                            break
                    except Exception:
                        continue
                if eol:
                    self.emit(f"  专案识别: {used_project}")
            if eol:
                imgs = extract_images(eol)
                self.emit(f"  EOL 照片: {len(imgs)} 张")
                self.status.emit(f"SN {i}/{len(self.sns)}: EOL 照片 {len(imgs)} 张,开始下载")
                for idx, img in enumerate(imgs, start=1):
                    if self._stop:
                        break
                    self.status.emit(f"下载图片 {idx}/{len(imgs)}: {img['station']}")
                    dest = self.download_dir / sn / "EOL" / f"{img['station']}_{len(per_sn['eol'])}.jpg"
                    ok, _used = try_download(img["url"], dest)
                    img["downloaded"] = ok
                    img["dest"] = str(dest)
                    per_sn["eol"].append(img)
                    per_sn["count"] += 1
                    if ok:
                        per_sn["downloaded"] += 1
                    else:
                        per_sn["failed"] += 1
                        failed_items.append(
                            (sn, used_project, "eol", sn, sn, img, dest))

                sensor = str(eol.get("sensorid") or "")
                if sensor:
                    try:
                        fol = self.gp.fol_by_sensor(sensor, used_project)
                    except Exception as exc:  # noqa: BLE001
                        fol = None
                        self.emit(f"  FOL 查询失败: {str(exc)[:100]}")
                    if fol:
                        imgs = extract_images(fol)
                        self.emit(f"  FOL 照片: {len(imgs)} 张 (sensorid={sensor})")
                        self.status.emit(f"SN {i}/{len(self.sns)}: FOL 照片 {len(imgs)} 张,开始下载")
                        for idx, img in enumerate(imgs, start=1):
                            if self._stop:
                                break
                            self.status.emit(f"下载图片 {idx}/{len(imgs)}: {img['station']}")
                            dest = self.download_dir / sn / "FOL" / f"{img['station']}_{len(per_sn['fol'])}.jpg"
                            ok, _used = try_download(img["url"], dest)
                            img["downloaded"] = ok
                            img["dest"] = str(dest)
                            per_sn["fol"].append(img)
                            per_sn["count"] += 1
                            if ok:
                                per_sn["downloaded"] += 1
                            else:
                                per_sn["failed"] += 1
                                failed_items.append(
                                    (sn, used_project, "fol", sensor, sensor,
                                     img, dest))
            else:
                self.emit("  EOL 无数据(SN 不存在或非 BOI 机种)")
            result["sns"][sn] = per_sn
            result["total"] += per_sn["count"]
            result["downloaded"] += per_sn["downloaded"]
            result["failed"] += per_sn["failed"]
            self.progress.emit(i, len(self.sns))
            self.emit(f"  本 SN: 照片 {per_sn['count']} 张,下载 {per_sn['downloaded']} 张")

        # 阶段B: 判定失效链接,询问用户是否从 SFC 补齐
        sfc_fixed = 0
        if failed_items and not self._stop:
            if not self.sfc_user:
                self.emit(f"直连失败 {len(failed_items)} 个链接"
                          f"(未登录 SFC,无法补齐,将以链接形式输出)")
            else:
                self.ask_sfc.emit(len(failed_items))
                self._sfc_event.wait()
                if self._sfc_choice and not self._stop:
                    self.emit(f"用户选择 SFC 补齐,开始处理 "
                              f"{len(failed_items)} 个失效链接 ...")
                    clients: Dict[str, Optional[Any]] = {}
                    caches: Dict[str, Dict[str, List[str]]] = {}
                    for sn, used_project, part, key, sn_hint, img, dest \
                            in failed_items:
                        if self._stop:
                            break
                        sfc_project = _load_gp_sfc_map().get(
                            (used_project or "").lower(), "")
                        if not sfc_project:
                            continue
                        if sfc_project not in clients:
                            try:
                                client = SfcPortal(
                                    self.sfc_user, self.sfc_password,
                                    project=sfc_project)
                                if not client.login():
                                    self.emit(f"  SFC 登录失败({sfc_project})")
                                    client = None
                                else:
                                    self.emit(f"  SFC 就绪: {sfc_project}")
                            except Exception as exc:  # noqa: BLE001
                                self.emit(f"  SFC 初始化失败: {str(exc)[:80]}")
                                client = None
                            clients[sfc_project] = client
                            caches[sfc_project] = {}
                        client = clients.get(sfc_project)
                        if client is None:
                            continue
                        ok, used_url = download_with_sfc_fallback(
                            img, dest, key=key, sn_hint=sn_hint,
                            sfc_client=client,
                            sfc_cache=caches[sfc_project],
                            log=self.emit)
                        img["url"] = used_url
                        img["downloaded"] = ok
                        img["dest"] = str(dest)
                        if ok:
                            sfc_fixed += 1
                            per_sn = result["sns"].get(sn)
                            if per_sn is not None:
                                per_sn["downloaded"] += 1
                                per_sn["failed"] = max(0, per_sn["failed"] - 1)
                            result["downloaded"] += 1
                            result["failed"] = max(0, result["failed"] - 1)
                else:
                    self.emit(f"用户选择不补齐,直接输出结果"
                              f"(失效 {len(failed_items)} 个链接将在 "
                              f"Excel 中以链接形式展示)")
        if sfc_fixed:
            self.emit(f"SFC 补齐成功 {sfc_fixed} 个")

        stopped = self._stop
        self.status.emit("已停止,正在生成部分结果 Excel..." if stopped
                         else "正在生成 Excel...")
        self.emit(f"完成: {len(self.sns)} SN,照片 {result['total']} 张,"
                  f"下载成功 {result['downloaded']} 张")
        # 生成 Excel(专案_日期.xlsx)
        try:
            project_tag = (self.project or "ALL").upper()
            date_str = datetime.now().strftime("%Y%m%d")
            excel_path = str(self.download_dir / f"{project_tag}_{date_str}.xlsx")
            build_excel(result["sns"], project_tag, excel_path, date_str)
            self.emit(f"Excel 已生成: {excel_path}")
        except Exception as exc:  # noqa: BLE001
            self.emit(f"Excel 生成失败: {exc}")
        self.status.emit("已停止" if stopped else "完成")
        self.done.emit(result, excel_path)


class AuthWorker(QThread):
    """后台执行 C4 登录(token 获取或粘贴验证)+ IIOT 验证。"""
    log_line = pyqtSignal(str)
    done = pyqtSignal(bool, str, str)  # (success, token, message)

    def __init__(self, userid: str = "", password: str = "", token: str = ""):
        super().__init__()
        self.userid = userid
        self.password = password
        self.token = token

    def run(self):
        auth = C4Auth()
        if self.token:
            # 用户手动验证(MFA 后)粘贴 token
            auth.token = self.token.strip()
            self.log_line.emit("验证手动获取的 token ...")
        else:
            # 账号密码登录(仅在不要求 MFA 的场景可用)
            ok, msg = auth.login(self.userid, self.password)
            if not ok:
                self.log_line.emit(f"账号密码登录失败: {msg}")
                self.log_line.emit("提示: 系统可能要求邮件验证码/APP 扫码,"
                                   "请在 tokenbylogin 页面手动登录后粘贴 Token。")
                self.done.emit(False, "", msg)
                return
            self.log_line.emit("一账通登录成功,已获取 JWT")
        # IIOT 验证
        ok2, msg2 = auth.verify()
        if ok2:
            self.log_line.emit("IIOT 鉴权通过,获得访问权限")
        else:
            self.log_line.emit(f"IIOT 鉴权提示: {msg2}")
            self.done.emit(False, "", f"鉴权失败: {msg2}")
            return
        # 保存 token
        try:
            import json as _json
            from pathlib import Path as _P
            base = _P(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
                else _P(__file__).resolve().parent
            cfg_path = base / "config.json"
            cfg = _json.loads(cfg_path.read_text(encoding="utf-8-sig")) if cfg_path.exists() else {}
            cfg.setdefault("c4", {})["token"] = auth.token
            cfg_path.write_text(_json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            self.log_line.emit(f"token 已保存: {cfg_path}")
        except Exception as exc:  # noqa: BLE001
            self.log_line.emit(f"token 保存失败: {exc}")
        self.done.emit(True, auth.token, "登录成功")


class MailCodeWorker(QThread):
    """邮箱验证码一键登录:SSO 全流程(AuthorizeEndpoint -> MFA -> 验证码 -> 换 JWT)。

    两阶段:
    1) 不带验证码:发送验证码到邮箱,发出 code_required 信号(等待用户输入);
    2) 带验证码:提交验证码并立即换 token,IIOT 实测通过后保存。
    """
    log_line = pyqtSignal(str)
    code_required = pyqtSignal(str)
    done = pyqtSignal(bool, str, str)
    user_info = pyqtSignal(str)  # 登录用户显示文本,如 "邓振宇 (F1679837)"

    def __init__(self, userid: str = "", password: str = "", code: str = ""):
        super().__init__()
        self.userid = userid
        self.password = password
        self.code = code

    def run(self):
        auth = C4Auth()
        if not self.code:
            # 阶段 1:发码
            ok, msg = auth.sso_get_token(self.userid, self.password, verify_code="")
            if msg.startswith("VERIFY_CODE_REQUIRED|"):
                self.log_line.emit("[权限] " + msg.split("|", 1)[1])
                self.code_required.emit("验证码已发送到你的邮箱,请输入 6 位验证码:")
                self.done.emit(False, "", "NEED_CODE")
                return
            self.log_line.emit(f"[权限] 发码失败: {msg}")
            self.done.emit(False, "", msg)
            return

        # 阶段 2:提交验证码 -> 换 token(必须在 state 有效期内一口气完成)
        self.log_line.emit("[权限] 提交验证码并换取 token ...")
        ok, msg = auth.sso_get_token(self.userid, self.password, verify_code=self.code)
        if not ok:
            self.log_line.emit(f"[权限] 登录失败: {msg}")
            self.done.emit(False, "", msg)
            return
        self.log_line.emit("[权限] JWT 获取成功,正在 IIOT 实测 ...")
        ok2, payload = auth.get_information_dt(
            device="BOI-T", sn="DNMHTV000F50000Y2N+2001+Q", columns=["sn"])
        if not ok2:
            msg2 = str(payload.get("message") or "鉴权失败")
            self.log_line.emit(f"[权限] IIOT 鉴权未通过: {msg2}")
            self.done.emit(False, "", f"鉴权失败: {msg2}")
            return
        # 保存 token
        try:
            import json as _json
            from pathlib import Path as _P
            base = _P(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
                else _P(__file__).resolve().parent
            cfg_path = base / "config.json"
            cfg = _json.loads(cfg_path.read_text(encoding="utf-8-sig")) if cfg_path.exists() else {}
            cfg.setdefault("c4", {})["token"] = auth.token
            cfg_path.write_text(_json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            self.log_line.emit(f"[权限] token 已保存: {cfg_path}")
        except Exception as exc:  # noqa: BLE001
            self.log_line.emit(f"[权限] token 保存失败: {exc}")
        self.log_line.emit(f"[权限] 登录成功(用户: {auth.user_info.get('username', '')})")
        self.user_info.emit(
            "{} ({})".format(
                auth.user_info.get("username", ""),
                auth.user_info.get("userid", ""),
            ).strip()
        )
        self.done.emit(True, auth.token, "登录成功")


class SfcLoginWorker(QThread):
    """SFC 一账通登录验证(10.151.128.45:8081,无需邮箱验证码)。"""
    log_line = pyqtSignal(str)
    done = pyqtSignal(bool, str, str, str)  # (ok, userid, password, msg)

    def __init__(self, userid: str = "", password: str = ""):
        super().__init__()
        self.userid = userid
        self.password = password

    def run(self):
        client = SfcPortal(self.userid, self.password)
        try:
            ok = client.login()
        except Exception as exc:  # noqa: BLE001
            self.log_line.emit(f"[登录] SFC 登录请求失败: {exc}")
            self.done.emit(False, self.userid, self.password, str(exc))
            return
        if ok:
            self.log_line.emit("[登录] SFC 登录验证通过")
            self.done.emit(True, self.userid, self.password, "SFC 登录成功")
        else:
            self.log_line.emit("[登录] SFC 登录失败(账号/密码错误?)")
            self.done.emit(False, self.userid, self.password, "SFC 登录失败")


class SfcWorker(QThread):
    """SFC 门户多专案查询(Serin + MC IMG + Excel 导出)。"""
    log_line = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    status = pyqtSignal(str)
    done = pyqtSignal(dict, str)

    def __init__(self, sns: List[str], project: str, exports: List[str],
                 userid: str, password: str, out_root: Path):
        super().__init__()
        self.sns = sns
        self.project = project
        self.exports = exports
        self.userid = userid
        self.password = password
        self.out_root = out_root

    def emit(self, msg: str):
        self.log_line.emit(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def run(self):
        result = {"sn_count": len(self.sns), "total": 0, "stations": {},
                  "out_dir": str(self.out_root)}
        try:
            self.status.emit("正在登录 SFC 门户...")
            client = SfcPortal(self.userid, self.password, project=self.project)
            if not client.login():
                self.emit("SFC 登录失败,请检查账号密码")
                self.status.emit("SFC 登录失败")
                self.done.emit(result, "")
                return
            self.emit(f"SFC 登录成功(专案: {self.project})")
            self.status.emit(f"SFC 查询中,共 {len(self.sns)} 个 SN")
            for i, sn in enumerate(self.sns, 1):
                self.emit(f"[{i}/{len(self.sns)}] === SN: {sn} ===")
                self.status.emit(f"处理 SN {i}/{len(self.sns)}: {sn}")
                safe = re.sub(r"[^0-9A-Za-z+_-]", "_", sn)[:60]
                out_dir = self.out_root / safe
                manifest = sfc_collect_sn(
                    client, sn, out_dir, exports=self.exports, log=self.emit)
                result["stations"][sn] = manifest
                result["total"] += int(manifest.get("total_links", 0))
                self.progress.emit(i, len(self.sns))
            self.status.emit("完成")
        except Exception as exc:  # noqa: BLE001
            self.emit(f"未预期错误: {exc}")
            import traceback
            self.emit(traceback.format_exc()[-600:])
            self.status.emit("执行失败")
        self.done.emit(result, "")


class CommonalityWorker(QThread):
    """共性分析:Load_DataCenterData 全量下载 + 单因素评分排行。"""
    log_line = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)  # (value, total, text)
    done = pyqtSignal(object, str, str, int)  # (top, excel, merged, fail_count)

    def __init__(self, token: str, project: str, sns: List[str],
                 dates: List[str], pass_sample: int, out_dir: Path,
                 mode: str = "mp"):
        super().__init__()
        self.token = token
        self.project = project
        self.sns = sns
        self.dates = dates
        self.pass_sample = pass_sample
        self.out_dir = out_dir
        self.mode = mode

    def emit(self, msg: str):
        self.log_line.emit(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def run(self):
        try:
            import base64 as _b64
            import time as _time
            payload = json.loads(_b64.urlsafe_b64decode(
                self.token.split(".")[1] + "===").decode())
            if int(payload.get("exp", 0)) < _time.time():
                self.emit("C4 token 已过期,请用[邮箱验证码登录]重新获取权限")
                self.done.emit(None, "", "", 0)
                return
            client = LdcClient(self.token, self.project)
            self.emit("项目 %s(device=%s, code=%s),Fail SN %d 个" % (
                self.project, client.device, client.code, len(self.sns)))
            dates = self.dates or client.fail_dates(self.sns)
            if not dates:
                self.emit("无法确定 Fail SN 的日期")
                self.done.emit(None, "", "", 0)
                return
            self.emit("按日期 Time 模式下载全量并采样 Pass ...")
            df = client.load_population_for_analyze(
                self.sns, dates=dates, pass_sample=self.pass_sample,
                progress=lambda v, t, m: self.progress.emit(v, t, m))
            self.progress.emit(100, 100, "数据分析完成,正在生成报告 ...")
            n_fail = int((df["pass_fail"].str.lower() == "fail").sum())
            n_pass = int((df["pass_fail"].str.lower() == "pass").sum())
            self.emit("合并表 %d 行 x %d 列(Fail %d / Pass %d)" % (
                len(df), len(df.columns), n_fail, n_pass))
            rows, _ = analyze_commonality(
                df, min_fail=3, fail_values=("fail", "Fail"), mode=self.mode)
            if not rows:
                self.emit("未发现显著性共性点(min_fail=3)")
                self.done.emit(None, "", "", n_fail)
                return
            from commonality_analysis import apriori_rules, write_styled_excel
            rules = apriori_rules(df, fail_col="pass_fail")
            import pandas as pd
            top = pd.DataFrame(rows).head(20)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.out_dir.mkdir(parents=True, exist_ok=True)
            merged_csv = self.out_dir / f"commonality_{self.project}_{ts}.csv"
            excel = self.out_dir / f"commonality_{self.project}_{ts}.xlsx"
            df.to_csv(merged_csv, index=False, encoding="utf-8-sig")
            write_styled_excel(excel, top,
                               rules if not rules.empty else None,
                               mode=self.mode)
            self.emit("Top 20 已保存(模式=%s,重点红/次重点橙): %s"
                      % (self.mode, excel))
            if not rules.empty:
                self.emit("组合规则 %d 条(已过滤同线结构性共现)" % len(rules))
            self.done.emit(top, str(excel), str(merged_csv), n_fail)
        except Exception as exc:  # noqa: BLE001
            self.emit(f"共性分析失败: {exc}")
            import traceback
            self.emit(traceback.format_exc()[-500:])
            self.done.emit(None, "", "", 0)


class CommonalityPptWorker(QThread):
    """生成共性分析 PPT(含可选维度桑基图)。"""
    log_line = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)  # (value, total, text),0/0=忙碌
    done = pyqtSignal(str, str)  # (pptx_path, err)

    def __init__(self, data_csv: str, project: str, mode: str,
                 fail_count: int, sankey_dims: List[str], out_dir: Path):
        super().__init__()
        self.data_csv = data_csv
        self.project = project
        self.mode = mode
        self.fail_count = fail_count
        self.sankey_dims = sankey_dims
        self.out_dir = out_dir

    def emit(self, msg: str):
        self.log_line.emit(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def run(self):
        try:
            self.progress.emit(0, 0, "正在生成 PPT(含桑基图)...")
            from commonality_ppt import build_ppt
            from commonality_analysis import analyze_commonality, apriori_rules
            import pandas as pd
            df = pd.read_csv(self.data_csv, low_memory=False, dtype=str)
            rows, _ = analyze_commonality(
                df, min_fail=1 if self.mode == "npi" else 3,
                fail_values=("fail", "Fail"), mode=self.mode)
            top = pd.DataFrame(rows).head(20)
            rules = apriori_rules(df, fail_col="pass_fail")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.out_dir.mkdir(parents=True, exist_ok=True)
            out = self.out_dir / f"共性分析报告_{self.project}_{ts}.pptx"
            self.emit("正在生成 PPT(桑基图维度: %s) ..." %
                      (", ".join(self.sankey_dims)
                       if self.sankey_dims else "未勾选,自动取前3"))
            build_ppt(self.project, self.mode, self.fail_count, top, rules,
                      df, out, sankey_dims=self.sankey_dims or None)
            self.emit("PPT 已生成: %s" % out)
            self.progress.emit(100, 100, "PPT 生成完成")
            self.done.emit(str(out), "")
        except Exception as exc:  # noqa: BLE001
            self.emit(f"PPT 生成失败: {exc}")
            self.done.emit("", str(exc))


class SnInfoWorker(QThread):
    """SN 信息查询:输入 SN 自动带出所有站位信息。"""
    log_line = pyqtSignal(str)
    done = pyqtSignal(object, str)  # (df 或 None, err)

    def __init__(self, project: str, sn: str, token: str,
                 userid: str, password: str):
        super().__init__()
        self.project = project
        self.sn = sn
        self.token = token
        self.userid = userid
        self.password = password

    def emit(self, msg: str):
        self.log_line.emit(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def run(self):
        try:
            from sn_info import query_sn_info
            r = query_sn_info(self.project, self.sn, self.token,
                              self.userid, self.password)
            if r is None:
                self.emit("查无数据(SN 不在该专案)")
                self.done.emit(None, "")
                return
            self.emit("查询完成: %d 个制程站位" % len(r["process"]))
            self.done.emit(r, "")
        except Exception as exc:  # noqa: BLE001
            self.emit(f"查询失败: {exc}")
            self.done.emit(None, str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SN_Report - 多专案追溯/照片一键查询")
        icon_path = BASE_DIR / "favicon.ico"
        if not icon_path.exists() and getattr(sys, "_MEIPASS", None):
            icon_path = Path(sys._MEIPASS) / "favicon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        w, h = window_target_size()
        self.resize(w, h)
        self.setMinimumSize(660, 480)
        self.worker: Optional[DownloadWorker] = None
        self.auth_worker: Optional[AuthWorker] = None
        self.sfc_worker: Optional[SfcWorker] = None
        self.common_worker: Optional[CommonalityWorker] = None
        self._login_userid = ""
        self._login_password = ""
        self._qss_scale: Optional[float] = None
        self.setStyleSheet(APPLE_QSS)
        self._create_menu()
        self._build_ui()

    def resizeEvent(self, event):
        """窗口变窄时按档位缩放字号,配合滚动区让内容不被裁切。"""
        super().resizeEvent(event)
        width = event.size().width()
        if width >= 1150:
            scale = 1.0
        elif width >= 950:
            scale = 0.92
        elif width >= 800:
            scale = 0.85
        else:
            scale = 0.78
        if scale != self._qss_scale:
            self._qss_scale = scale
            self.setStyleSheet(build_qss(scale))

    def _scroll_wrap(self, widget: QWidget) -> QScrollArea:
        """把标签页内容包进滚动区:窗口缩小时用滚动条代替裁切。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(widget)
        return scroll

    def _create_menu(self):
        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction("选择 SN 文件", self._pick_file)
        file_menu.addAction("选择保存目录", self._pick_dir)
        file_menu.addAction("重新登录", self._re_login)
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close)

        help_menu = self.menuBar().addMenu("帮助")
        help_menu.addAction("关于", self._show_about)

    def set_login_user(self, user_text: str, userid: str = "",
                       password: str = ""):
        """主界面显示当前登录用户。"""
        self._login_user = user_text or ""
        self._login_userid = userid or self._login_userid
        self._login_password = password or self._login_password
        text = f"已登录: {self._login_user}" if self._login_user else "未登录"
        self.statusBar().showMessage(text)

    def _re_login(self):
        """重新弹出登录窗口,登录成功后刷新用户显示。"""
        login = LoginWindow(self)
        if login.exec_() == QDialog.Accepted and login.last_user_text:
            self.set_login_user(login.last_user_text, login.last_userid,
                                login.last_password)

    def _build_ui(self):
        self.tabs = QTabWidget(self)
        self.setCentralWidget(self.tabs)
        tab_photo = QWidget()
        root = QVBoxLayout(tab_photo)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(14)

        # ─── 连接信息卡片 ───
        conn_grid = QGridLayout()
        conn_grid.setVerticalSpacing(6)
        conn_grid.setHorizontalSpacing(8)
        conn_grid.addWidget(QLabel("专案"), 0, 0)
        self.project_combo = QComboBox()
        self.project_combo.addItem("全部(自动识别)", "")
        self.project_combo.setMinimumWidth(220)
        conn_grid.addWidget(self.project_combo, 0, 1)
        conn_grid.setColumnStretch(1, 1)
        self.project_hint = hint("自动识别专案;或手动指定")
        conn_grid.addWidget(self.project_hint, 0, 2)
        root.addWidget(card("查询设置", conn_grid))

        # ─── SN 输入卡片 ───
        sn_layout = QVBoxLayout()
        sn_layout.setSpacing(6)
        sn_layout.addWidget(hint("多个 SN 用逗号或换行分隔,或直接选择 SN 文件"))
        self.sn_edit = QTextEdit()
        self.sn_edit.setPlaceholderText("例:\nDNMHTV000F50000Y2N+2001+Q\nDNMHTV000F50000Y2N+2001+R")
        self.sn_edit.setMinimumHeight(70)
        sn_layout.addWidget(self.sn_edit)
        file_row = QHBoxLayout()
        file_row.setSpacing(6)
        self.file_btn = QPushButton("选择 SN 文件(.txt/.csv/.xlsx)")
        self.file_btn.setProperty("secondary", True)
        self.file_btn.clicked.connect(self._pick_file)
        self.file_label = QLabel("未选择文件")
        self.file_label.setProperty("subtitle", True)
        file_row.addWidget(self.file_btn)
        file_row.addWidget(self.file_label, 1)
        sn_layout.addLayout(file_row)
        root.addWidget(card("Module SN", sn_layout))

        # ─── 导出内容勾选卡片 ───
        exp_box = QVBoxLayout()
        exp_box.setSpacing(6)
        exp_grid = QGridLayout()
        exp_grid.setHorizontalSpacing(20)
        exp_grid.setVerticalSpacing(4)
        self.exp_serin = QCheckBox("Serin 追溯数据")
        self.exp_serin.setChecked(True)
        self.exp_mcimg = QCheckBox("MC IMG 图片清单")
        self.exp_mcimg.setChecked(True)
        self.exp_excel = QCheckBox("IMG Info Excel 元数据")
        self.exp_excel.setChecked(True)
        self.exp_download = QCheckBox("下载图片")
        self.exp_download.setChecked(False)
        exp_grid.addWidget(self.exp_serin, 0, 0)
        exp_grid.addWidget(self.exp_mcimg, 0, 1)
        exp_grid.addWidget(self.exp_excel, 1, 0)
        exp_grid.addWidget(self.exp_download, 1, 1)
        exp_box.addLayout(exp_grid)
        exp_box.addWidget(hint("下载图片需台式机/图片服务器可达"))
        root.addWidget(card("导出内容(勾选)", exp_box))

        # ─── 保存目录卡片 ───
        dir_grid = QGridLayout()
        dir_grid.setVerticalSpacing(6)
        dir_grid.setHorizontalSpacing(8)
        dir_grid.addWidget(QLabel("保存目录"), 0, 0)
        self.dir_edit = QLineEdit(str(BASE_DIR / "downloads"))
        self.dir_edit.setMinimumHeight(32)
        dir_grid.addWidget(self.dir_edit, 0, 1)
        self.dir_btn = QPushButton("浏览")
        self.dir_btn.setProperty("secondary", True)
        self.dir_btn.setMinimumWidth(84)
        self.dir_btn.setMinimumHeight(32)
        self.dir_btn.clicked.connect(self._pick_dir)
        dir_grid.addWidget(self.dir_btn, 0, 2)
        dir_grid.setColumnStretch(1, 1)
        root.addWidget(card("输出设置", dir_grid))

        # ─── 运行状态 + 进度条 ───
        self.status_label = QLabel("就绪")
        self.status_label.setProperty("subtitle", True)
        root.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFixedHeight(14)
        self.progress.setFormat("等待开始")
        root.addWidget(self.progress)

        # ─── 日志卡片 ───
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(0, 0, 0, 0)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("logView")
        self.log_view.setPlaceholderText("下载日志将显示在此处 ...")
        self.log_view.setMinimumHeight(100)
        log_layout.addWidget(self.log_view)
        root.addWidget(card("运行日志", log_layout), 1)

        # ─── 操作按钮 ───
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        self.start_btn = QPushButton("开始执行")
        self.start_btn.setProperty("primary", True)
        self.start_btn.setDefault(True)
        self.start_btn.setFixedWidth(120)
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setProperty("danger", True)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setFixedWidth(120)
        self.stop_btn.clicked.connect(self._stop)
        btn_row.addStretch(1)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.start_btn)
        root.addLayout(btn_row)
        self.tabs.addTab(self._scroll_wrap(tab_photo), "照片/追溯下载")
        self.tabs.addTab(self._scroll_wrap(self._build_common_tab()), "共性分析")
        self.tabs.addTab(self._scroll_wrap(self._build_sninfo_tab()), "SN 信息查询")

        # ─── 状态栏 ───
        sb = self.statusBar()
        sb.showMessage("就绪")
        sb_label = QLabel("Copyright©️ABU NPD EOL FACA")
        sb_label.setStyleSheet(f"color: {C_SUB}; font-size: 11px;")
        sb.addPermanentWidget(sb_label)

    # ---------- 共性分析标签页 ----------
    def _build_common_tab(self):
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(14)

        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(8)
        grid.addWidget(QLabel("专案"), 0, 0)
        self.common_project = QComboBox()
        for pid in LDC_PROJECTS:
            self.common_project.addItem(pid, pid)
        self.common_project.setMinimumWidth(180)
        grid.addWidget(self.common_project, 0, 1)
        grid.addWidget(hint("需 C4 token(邮箱验证码登录);数据中心有映射的专案"), 0, 2)

        grid.addWidget(QLabel("Fail SN"), 1, 0)
        self.common_sn_edit = QTextEdit()
        self.common_sn_edit.setPlaceholderText("每行一个 Fail SN")
        self.common_sn_edit.setMinimumHeight(64)
        grid.addWidget(self.common_sn_edit, 1, 1, 1, 2)
        self.common_sn_file_btn = QPushButton("选择 SN 文件")
        self.common_sn_file_btn.setProperty("secondary", True)
        self.common_sn_file_btn.clicked.connect(self._pick_common_sn_file)
        grid.addWidget(self.common_sn_file_btn, 1, 3)

        grid.addWidget(QLabel("日期范围"), 2, 0)
        self.common_auto_date = QCheckBox("自动按 Fail SN 推断")
        self.common_auto_date.setChecked(True)
        self.common_start = QDateEdit()
        self.common_start.setCalendarPopup(True)
        self.common_start.setDate(QDate(2026, 7, 1))
        self.common_start.setMinimumWidth(110)
        self.common_end = QDateEdit()
        self.common_end.setCalendarPopup(True)
        self.common_end.setDate(QDate(2026, 8, 12))
        self.common_end.setMinimumWidth(110)
        grid.addWidget(self.common_auto_date, 2, 1)
        grid.addWidget(self.common_start, 2, 2)
        grid.addWidget(self.common_end, 2, 3)

        grid.addWidget(QLabel("Pass 采样/天"), 3, 0)
        self.common_pass = QSpinBox()
        self.common_pass.setRange(500, 20000)
        self.common_pass.setValue(3000)
        self.common_pass.setMinimumWidth(100)
        grid.addWidget(self.common_pass, 3, 1)
        grid.addWidget(QLabel("分析模式"), 3, 2)
        self.common_mode = QComboBox()
        self.common_mode.addItem("量产 MP(大量 Fail,默认)", "mp")
        self.common_mode.addItem("试产 NPI(小样本)", "npi")
        self.common_mode.addItem("自动(<20 Fail 走 NPI)", "auto")
        self.common_mode.setMinimumWidth(180)
        grid.addWidget(self.common_mode, 3, 3)
        grid.addWidget(hint("NPI 关注材料/治工具/工作区;MP 用 FDR 严格筛选"), 4, 1, 1, 3)
        root.addWidget(card("共性分析参数", grid))

        self.common_table = QTableWidget()
        self.common_table.setColumnCount(9)
        self.common_table.setHorizontalHeaderLabels(
            ["维度", "值", "Fail数", "样本数", "Fail率", "Lift",
             "Fail占比", "p_adj", "Score"])
        for col, width in enumerate([90, 150, 70, 80, 80, 60, 90, 80, 90]):
            self.common_table.setColumnWidth(col, width)
        self.common_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.common_table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.common_table, 1)

        self.common_progress = QProgressBar()
        self.common_progress.setRange(0, 1)
        self.common_progress.setValue(0)
        self.common_progress.setFixedHeight(14)
        self.common_progress.setFormat("等待分析")
        root.addWidget(self.common_progress)

        self.common_log = QTextEdit()
        self.common_log.setReadOnly(True)
        self.common_log.setMinimumHeight(72)
        root.addWidget(self.common_log)

        ppt_row = QHBoxLayout()
        ppt_row.addWidget(QLabel("桑基图维度"))
        self.sankey_dim_list = QListWidget()
        self.sankey_dim_list.setMinimumHeight(96)
        self.sankey_dim_list.setMinimumWidth(320)
        ppt_row.addWidget(self.sankey_dim_list, 1)
        self.ppt_btn = QPushButton("生成 PPT(含桑基图)")
        self.ppt_btn.setProperty("primary", True)
        self.ppt_btn.clicked.connect(self._common_ppt_run)
        ppt_row.addWidget(self.ppt_btn)
        root.addLayout(ppt_row)

        btn_row = QHBoxLayout()
        self.common_run_btn = QPushButton("开始共性分析")
        self.common_run_btn.setProperty("primary", True)
        self.common_run_btn.clicked.connect(self._common_run)
        btn_row.addStretch(1)
        btn_row.addWidget(self.common_run_btn)
        root.addLayout(btn_row)
        return w

    # ---------- SN 信息查询标签页 ----------
    def _build_sninfo_tab(self):
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(14)
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(8)
        grid.addWidget(QLabel("专案"), 0, 0)
        self.sninfo_project = QComboBox()
        for pid in SFC_PROJECTS:
            self.sninfo_project.addItem("SFC·" + SFC_PROJECTS[pid].get("label", pid),
                                        ("SFC", pid))
        for pid in LDC_PROJECTS:
            self.sninfo_project.addItem("数据中心·" + pid, ("LDC", pid))
        self.sninfo_project.setMinimumWidth(220)
        grid.addWidget(self.sninfo_project, 0, 1)
        grid.addWidget(QLabel("SN"), 1, 0)
        self.sninfo_sn = QLineEdit()
        self.sninfo_sn.setPlaceholderText("输入 SN,自动带出所有站位信息")
        grid.addWidget(self.sninfo_sn, 1, 1, 1, 2)
        self.sninfo_query_btn = QPushButton("查询")
        self.sninfo_query_btn.setProperty("primary", True)
        self.sninfo_query_btn.clicked.connect(self._sninfo_query)
        grid.addWidget(self.sninfo_query_btn, 1, 3)
        self.sninfo_export_btn = QPushButton("导出 Excel")
        self.sninfo_export_btn.setProperty("secondary", True)
        self.sninfo_export_btn.setEnabled(False)
        self.sninfo_export_btn.clicked.connect(self._sninfo_export)
        grid.addWidget(self.sninfo_export_btn, 1, 4)
        root.addWidget(card("SN 信息查询", grid))

        self.sninfo_table = QTableWidget()
        self.sninfo_table.setColumnCount(8)
        self.sninfo_table.setHorizontalHeaderLabels(
            ["站位", "进站时间", "出站时间", "生产时间", "机台号", "头",
             "Tray ID", "穴位"])
        self.sninfo_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sninfo_table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.sninfo_table, 1)
        self.sninfo_log = QTextEdit()
        self.sninfo_log.setReadOnly(True)
        self.sninfo_log.setMinimumHeight(72)
        root.addWidget(self.sninfo_log)
        return w

    def _sninfo_query(self):
        kind, project = self.sninfo_project.currentData()
        sn = self.sninfo_sn.text().strip()
        if not sn:
            QMessageBox.warning(self, "提示", "请输入 SN。")
            return
        token = self._c4_token()
        if kind == "LDC" and not token:
            QMessageBox.warning(self, "提示", "数据中心查询需要 C4 token,"
                                              "请先邮箱验证码登录。")
            return
        self.sninfo_query_btn.setEnabled(False)
        self._append_sninfo_log("查询 %s / %s ..." % (project, sn))
        self.sninfo_worker = SnInfoWorker(
            project, sn, token, self._login_userid, self._login_password)
        self.sninfo_worker.log_line.connect(self._append_sninfo_log)
        self.sninfo_worker.done.connect(self._sninfo_done)
        self.sninfo_worker.start()

    def _sninfo_done(self, r, err: str):
        self.sninfo_query_btn.setEnabled(True)
        if err:
            self._append_sninfo_log(f"[查询] 失败: {err}")
            return
        if r is None:
            self.sninfo_export_btn.setEnabled(False)
            return
        proc = r["process"]
        self.sninfo_table.setRowCount(len(proc))
        for i, (_, row) in enumerate(proc.iterrows()):
            for j in range(8):
                self.sninfo_table.setItem(
                    i, j, QTableWidgetItem(str(row.iloc[j])))
        self.sninfo_table.resizeColumnsToContents()
        self.sninfo_export_btn.setEnabled(True)
        self._last_sninfo = r
        self._last_sninfo_sn = self.sninfo_sn.text().strip()
        self._append_sninfo_log("[查询] 完成,制程站位 %d 个" % len(proc))

    def _sninfo_export(self):
        r = getattr(self, "_last_sninfo", None)
        if r is None:
            return
        from sn_info import rows_to_df
        proc = r["process"]
        detail = rows_to_df(r["basic"], r["rows"])
        import datetime as _dt
        out = Path(self.dir_edit.text().strip() or str(BASE_DIR / "downloads"))
        out.mkdir(parents=True, exist_ok=True)
        path = out / ("SN信息_%s_%s.xlsx" % (
            self._last_sninfo_sn.replace("+", "_")[:40],
            _dt.datetime.now().strftime("%Y%m%d_%H%M%S")))
        with pd.ExcelWriter(path) as writer:
            proc.to_excel(writer, sheet_name="制程信息", index=False)
            detail.to_excel(writer, sheet_name="全字段明细", index=False)
        QMessageBox.information(self, "导出完成", str(path))

    def _append_sninfo_log(self, msg: str):
        self.sninfo_log.append(msg)
        self.sninfo_log.verticalScrollBar().setValue(
            self.sninfo_log.verticalScrollBar().maximum())

    def _add_sankey_dim(self, dim: str, checked: bool = False):
        item = QListWidgetItem(dim)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.sankey_dim_list.addItem(item)

    def _pick_common_sn_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Fail SN 文件", str(BASE_DIR),
            "SN 文件 (*.txt *.csv);;所有文件 (*)")
        if path:
            try:
                self.common_sn_edit.setPlainText(
                    Path(path).read_text(encoding="utf-8-sig"))
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "提示", f"读取失败: {exc}")

    @staticmethod
    def _c4_token() -> str:
        try:
            base = Path(sys.executable).resolve().parent if getattr(
                sys, "frozen", False) else Path(__file__).resolve().parent
            cfg = json.loads((base / "config.json").read_text(encoding="utf-8-sig"))
            return (cfg.get("c4") or {}).get("token", "")
        except Exception:  # noqa: BLE001
            return ""

    def _common_run(self):
        token = self._c4_token()
        if not token:
            QMessageBox.warning(self, "提示", "config.json 中没有 C4 token。")
            return
        sns = [s.strip() for s in self.common_sn_edit.toPlainText().splitlines()
               if s.strip()]
        if not sns:
            QMessageBox.warning(self, "提示", "请输入 Fail SN(每行一个)。")
            return
        project = self.common_project.currentData()
        if self.common_auto_date.isChecked():
            dates: List[str] = []
        else:
            dates = [
                self.common_start.date().toString("yyyy-MM-dd"),
                self.common_end.date().toString("yyyy-MM-dd"),
            ]
        out_dir = Path(self.dir_edit.text().strip() or str(BASE_DIR / "downloads"))
        self.common_table.setRowCount(0)
        self.common_log.clear()
        self.common_run_btn.setEnabled(False)
        self._append_common_log(f"专案 {project},Fail SN {len(sns)} 个,"
                                f"日期 {'自动' if not dates else '~'.join(dates)}")
        self.common_worker = CommonalityWorker(
            token, project, sns, dates, self.common_pass.value(), out_dir,
            self.common_mode.currentData())
        self.common_worker.log_line.connect(self._append_common_log)
        self.common_worker.progress.connect(self._set_common_progress)
        self.common_worker.done.connect(self._common_done)
        self.common_progress.setRange(0, 1)
        self.common_progress.setValue(0)
        self.common_progress.setFormat("准备分析 ...")
        self.common_worker.start()

    def _common_ppt_run(self):
        data_csv = getattr(self, "_common_data_csv", "")
        if not data_csv:
            QMessageBox.warning(self, "提示",
                                "请先运行一次共性分析,生成合并数据后再生成 PPT。")
            return
        checked = [self.sankey_dim_list.item(i).text()
                   for i in range(self.sankey_dim_list.count())
                   if self.sankey_dim_list.item(i).checkState() == Qt.Checked]
        sankey_dims = checked
        self.ppt_btn.setEnabled(False)
        self._append_common_log("开始生成 PPT ...")
        self.ppt_worker = CommonalityPptWorker(
            data_csv, getattr(self, "_common_project", ""),
            getattr(self, "_common_mode", "mp"),
            getattr(self, "_common_fail_count", 0), sankey_dims,
            Path(self.dir_edit.text().strip() or str(BASE_DIR / "downloads")))
        self.ppt_worker.log_line.connect(self._append_common_log)
        self.ppt_worker.progress.connect(self._set_common_progress)
        self.ppt_worker.done.connect(self._ppt_done)
        self.ppt_worker.start()

    def _set_common_progress(self, value: int, total: int, text: str):
        if total <= 0:
            self.common_progress.setRange(0, 0)  # 忙碌动画
            self.common_progress.setFormat(text)
            return
        self.common_progress.setRange(0, max(total, 1))
        self.common_progress.setValue(min(value, max(total, 1)))
        self.common_progress.setFormat(text + "  %v/%m (%p%)")

    def _ppt_done(self, pptx_path: str, err: str):
        self.ppt_btn.setEnabled(True)
        self.common_progress.setRange(0, 1)
        self.common_progress.setValue(0)
        self.common_progress.setFormat("等待分析")
        if err:
            self._append_common_log(f"[PPT] 生成失败: {err}")
            return
        self._append_common_log(f"[PPT] 完成: {pptx_path}")
        QMessageBox.information(self, "PPT 生成完成", f"已保存:\n{pptx_path}")

    def _append_common_log(self, msg: str):
        self.common_log.append(msg)
        self.common_log.verticalScrollBar().setValue(
            self.common_log.verticalScrollBar().maximum())

    def _common_done(self, top, excel_path: str, merged_csv: str,
                     fail_count: int):
        self.common_run_btn.setEnabled(True)
        self.common_progress.setRange(0, 1)
        self.common_progress.setValue(0)
        self.common_progress.setFormat("等待分析")
        if top is None:
            self._append_common_log("[共性] 无结果(见上方日志)")
            return
        self.common_table.setRowCount(len(top))
        for i, (_, row) in enumerate(top.iterrows()):
            for j, col in enumerate(
                    ["dimension", "value", "fail_count", "unit_count",
                     "fail_rate", "lift", "fail_ratio", "p_adj", "score"]):
                item = QTableWidgetItem(str(row[col]))
                self.common_table.setItem(i, j, item)
        # 记住本次结果 + 填充桑基图维度下拉
        self._common_data_csv = merged_csv
        self._common_project = self.common_project.currentData()
        self._common_mode = self.common_mode.currentData()
        self._common_fail_count = fail_count
        dims = list(dict.fromkeys(str(d) for d in top["dimension"]))
        self.sankey_dim_list.clear()
        for i, d in enumerate(dims):
            # 默认勾选实际前 3 个维度(替换原来的"自动(前3个)"选项)
            self._add_sankey_dim(d, checked=(i < 3))
        self._append_common_log(f"[共性] 完成,Top {len(top)} 已保存: {excel_path}")
        QMessageBox.information(
            self, "共性分析完成",
            f"Top {len(top)} 共性可疑点\nExcel: {excel_path}\n数据: {merged_csv}")

    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 SN 文件", str(BASE_DIR),
            "SN 文件 (*.txt *.csv *.xlsx);;所有文件 (*)")
        if not path:
            return
        try:
            sns = load_sn_list(Path(path))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "读取失败", str(exc))
            return
        self.file_label.setText(f"{Path(path).name} ({len(sns)} 个 SN)")
        self.sn_edit.setPlainText("\n".join(sns))

    def _pick_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择保存目录", str(BASE_DIR))
        if path:
            self.dir_edit.setText(path)

    def _parse_sns(self) -> List[str]:
        raw = self.sn_edit.toPlainText().replace("，", ",")
        sns = [s.strip() for s in raw.replace("\n", ",").split(",") if s.strip()]
        seen, out = set(), []
        for s in sns:
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out

    def _start(self):
        self._refresh_projects()
        sns = self._parse_sns()
        if not sns:
            QMessageBox.warning(self, "提示", "请先输入 SN 或选择 SN 文件。")
            return
        dl_dir = Path(self.dir_edit.text().strip() or str(BASE_DIR / "downloads"))
        dl_dir.mkdir(parents=True, exist_ok=True)
        project = self.project_combo.currentData() or ""

        self.log_view.clear()
        self.progress.setRange(0, len(sns))
        self.progress.setValue(0)
        self.progress.setFormat("SN %v/%m (%p%)")
        self.status_label.setText(f"准备处理 {len(sns)} 个 SN ...")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        if project.startswith("SFC:"):
            # SFC 门户链路(APP007/Cali/ATW-N/ATW-E)
            sfc_project = project.split(":", 1)[1]
            exports = []
            if self.exp_serin.isChecked():
                exports.append("serin")
            if self.exp_mcimg.isChecked():
                exports.append("mcimg")
            if self.exp_excel.isChecked():
                exports.append("excel")
            if self.exp_download.isChecked():
                exports.append("download")
            if not exports:
                QMessageBox.warning(self, "提示", "请至少勾选一项要导出的内容。")
                self.start_btn.setEnabled(True)
                self.stop_btn.setEnabled(False)
                return
            if not self._login_userid:
                QMessageBox.warning(
                    self, "提示",
                    "未保存登录账号,请通过 文件→重新登录 完成登录后重试。")
                self.start_btn.setEnabled(True)
                self.stop_btn.setEnabled(False)
                return
            self._append_log(f"[SFC] 专案 {sfc_project},导出: {','.join(exports)}")
            self.sfc_worker = SfcWorker(
                sns, sfc_project, exports,
                self._login_userid, self._login_password, dl_dir)
            self.sfc_worker.log_line.connect(self._append_log)
            self.sfc_worker.progress.connect(lambda i, n: self.progress.setValue(i))
            self.sfc_worker.status.connect(self.status_label.setText)
            self.sfc_worker.done.connect(self._done)
            self.sfc_worker.start()
        else:
            self.worker = DownloadWorker(
                sns, dl_dir,
                DB_CFG["host"], DB_CFG["port"], DB_CFG["database"],
                DB_CFG["user"], DB_CFG["password"], project=project,
                sfc_user=self._login_userid or "",
                sfc_password=self._login_password or "")
            self.worker.log_line.connect(self._append_log)
            self.worker.progress.connect(lambda i, n: self.progress.setValue(i))
            self.worker.status.connect(self.status_label.setText)
            self.worker.ask_sfc.connect(self._ask_sfc_fallback)
            self.worker.done.connect(self._done)
            self.worker.start()

    def _refresh_projects(self):
        """加载 Greenplum 专案 + SFC 门户专案到下拉列表。"""
        if self.project_combo.count() > 1:
            return  # 已加载
        # SFC 门户专案
        for pid, cfg in SFC_PROJECTS.items():
            self.project_combo.addItem(cfg["label"], "SFC:" + pid)
        try:
            gp = GreenplumSerin(
                host=DB_CFG["host"], port=DB_CFG["port"],
                database=DB_CFG["database"],
                user=DB_CFG["user"], password=DB_CFG["password"])
            gp.connect()
            projs = gp.list_projects()
            for p in projs:
                self.project_combo.addItem(p.upper(), p)
            self.project_hint.setText(
                f"已加载 {len(projs)} 个 Greenplum 专案 + {len(SFC_PROJECTS)} 个 SFC 专案")
        except Exception as exc:  # noqa: BLE001
            self.project_hint.setText(
                f"Greenplum 加载失败(检查 config.json);已加载 {len(SFC_PROJECTS)} 个 SFC 专案")

    def _stop(self):
        if self.worker:
            self.worker.stop()
            self.status_label.setText("正在停止,请稍候...")
            self._append_log("[!] 停止请求已发送,等待当前文件完成...")

    def _ask_sfc_fallback(self, failed_count: int):
        """直连有失效链接时询问用户是否从 SFC 补齐。"""
        if self.worker is None:
            return
        ret = QMessageBox.question(
            self, "失效链接补齐",
            f"C4/GP 直连有 {failed_count} 个图片链接失效。\n"
            "是否从 SFC 补齐?\n\n"
            "选【是】:走 SFC 查询并尝试下载补齐;\n"
            "选【否】:直接输出结果,失效图片以链接形式展示。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        self.worker.set_sfc_choice(ret == QMessageBox.Yes)

    def _append_log(self, msg: str):
        self.log_view.append(msg)
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum())

    def _done(self, result: dict, excel_path: str):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("完成")
        if "out_dir" in result and not excel_path:
            # SFC 查询结果
            out_dir = result.get("out_dir", "")
            msg = (
                f"SN: {result['sn_count']} 个\n"
                f"共收集链接: {result['total']} 个\n"
                f"输出目录: {out_dir}"
            )
            QMessageBox.information(self, "完成", msg)
            return
        msg = (
            f"SN: {result['sn_count']} 个\n照片: {result['total']} 张\n"
            f"下载成功: {result['downloaded']} 张\n失败: {result['failed']} 张\n"
            f"保存目录: {self.dir_edit.text()}"
        )
        if excel_path:
            msg += f"\n\nExcel: {excel_path}"
        QMessageBox.information(
            self, "完成",
            msg)

    def _show_about(self):
        QMessageBox.about(
            self, "关于",
            "SN_Report v1.0\n\n"
            "Greenplum Serin 照片一键下载\n"
            "输入 Module SN,自动查询 EOL+FOL 全部站位照片并下载。",
        )


def _jwt_user(token: str) -> str:
    """从 JWT payload 解出用户显示文本,如 '邓振宇 (F1679837)'。"""
    try:
        import base64
        payload = token.split(".")[1] + "==="
        data = json.loads(base64.urlsafe_b64decode(payload.encode()).decode("utf-8"))
        name = data.get("UserName", "")
        uid = data.get("UserId", "")
        return "{} ({})".format(name, uid).strip()
    except Exception:  # noqa: BLE001
        return ""


class LoginWindow(QDialog):
    """SFC/一账通登录界面(走 10.151.128.45:8081 验证)。

    登录方式:
    1. 一账通账号密码 → SFC 系统验证(首选,无需邮箱验证码);
    2. 邮箱验证码登录(C4/IIOT token,备用);
    3. 手动打开 tokenbylogin 页面登录后粘贴 Token。
    登录成功后记录账号密码并 accept()。
    """
    login_ok = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SN_Report - 权限登录(IIOT/C4)")
        self.setModal(True)
        self.setStyleSheet(APPLE_QSS)
        self.mail_worker: Optional[MailCodeWorker] = None
        self.mail_worker2: Optional[MailCodeWorker] = None
        self.auth_worker: Optional[AuthWorker] = None
        self.sfc_worker: Optional[SfcLoginWorker] = None
        self._auto_worker: Optional[AuthWorker] = None
        self._manual_login_started = False
        self.last_user_text = ""
        self.last_userid = ""
        self.last_password = ""
        self._build_ui()
        self._append_log("[登录] 请输入一账通账号密码,点击[登录](SFC 系统验证);"
                         "或使用邮箱验证码/粘贴 Token 登录。")
        self._auto_check_saved_token()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("欢迎使用NPD EOL FACA工具")
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #1D1D1F;")
        root.addWidget(title)
        sub = QLabel("一账通账号密码登录(SFC 10.151.128.45:8081 验证)")
        sub.setStyleSheet(f"color: {C_SUB}; font-size: 12px;")
        root.addWidget(sub)
        guide = QLabel(
            "三种功能所需登录账号:\n"
            "· 照片/追溯下载 → SFC账号(无需邮箱验证)\n"
            "· 共性分析 → C4账号(需要邮箱验证)\n"
            "· SN 信息查询 → SFC账号;选【数据中心】专案时需 C4账号\n\n"
            "登录方式:\n"
            "· SFC账号:填一账通账号密码点【登 录】\n"
            "· C4账号:点【邮箱验证码登录(C4)】,验证码发到邮箱后输入\n"
            "· 邮箱验证码失败:tokenbylogin 页面登录后粘贴 Token 验证")
        guide.setWordWrap(True)
        guide.setStyleSheet(f"color: {C_SUB}; font-size: 12px;")
        root.addWidget(guide)

        # 账号信息
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(8)
        grid.addWidget(QLabel("一账通账号"), 0, 0)
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("工号,如 F1679837")
        grid.addWidget(self.user_edit, 0, 1, 1, 3)
        grid.addWidget(QLabel("密码"), 1, 0)
        self.pwd_edit = QLineEdit()
        self.pwd_edit.setEchoMode(QLineEdit.Password)
        self.pwd_edit.setPlaceholderText("一账通密码")
        grid.addWidget(self.pwd_edit, 1, 1, 1, 3)
        root.addWidget(card("账号信息", grid))

        # 手动 Token(可选)
        tg = QGridLayout()
        tg.setVerticalSpacing(6)
        tg.setHorizontalSpacing(8)
        tg.addWidget(QLabel("粘贴 Token"), 0, 0)
        self.token_edit = QLineEdit()
        self.token_edit.setPlaceholderText("tokenbylogin 页面登录后复制的 JWT(可选)")
        tg.addWidget(self.token_edit, 0, 1, 1, 3)
        self.open_page_btn = QPushButton("打开 tokenbylogin 页面")
        self.open_page_btn.setProperty("link", True)
        self.open_page_btn.clicked.connect(self._open_token_page)
        tg.addWidget(self.open_page_btn, 0, 4)
        self.verify_token_btn = QPushButton("验证 Token")
        self.verify_token_btn.setProperty("secondary", True)
        self.verify_token_btn.clicked.connect(self._verify_token)
        tg.addWidget(self.verify_token_btn, 0, 5)
        root.addWidget(card("手动 Token(可选)", tg))

        self.status = hint("未登录")
        root.addWidget(self.status)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(120)
        self.log_view.setStyleSheet(
            "QTextEdit { background: #F5F5F7; border: 1px solid #E5E5EA;"
            " border-radius: 8px; padding: 6px; color: #3A3A3C; font-size: 12px; }"
        )
        root.addWidget(self.log_view)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.exit_btn = QPushButton("退出")
        self.exit_btn.setProperty("secondary", True)
        self.exit_btn.clicked.connect(self.reject)
        self.mail_login_btn = QPushButton("邮箱验证码登录(C4)")
        self.mail_login_btn.setProperty("secondary", True)
        self.mail_login_btn.clicked.connect(self._do_mail_login)
        self.login_btn = QPushButton("登 录")
        self.login_btn.setProperty("primary", True)
        self.login_btn.clicked.connect(self._do_sfc_login)
        btn_row.addStretch(1)
        btn_row.addWidget(self.exit_btn)
        btn_row.addWidget(self.mail_login_btn)
        btn_row.addWidget(self.login_btn)
        root.addLayout(btn_row)

        self.setMinimumWidth(620)

    # ---------- 登录动作 ----------
    def _do_sfc_login(self):
        """一账通账号密码 → SFC 系统验证(首选,无需邮箱验证码)。"""
        self._manual_login_started = True
        userid = self.user_edit.text().strip()
        password = self.pwd_edit.text()
        if not userid or not password:
            QMessageBox.warning(self, "提示", "请输入一账通账号和密码。")
            return
        self.login_btn.setEnabled(False)
        self.status.setText("正在连接 SFC 系统验证 ...")
        self._append_log(f"[登录] SFC 验证账号 {userid} ...")
        self.sfc_worker = SfcLoginWorker(userid=userid, password=password)
        self.sfc_worker.log_line.connect(self._append_log)
        self.sfc_worker.done.connect(self._sfc_login_done)
        self.sfc_worker.start()

    def _sfc_login_done(self, ok: bool, userid: str, password: str, message: str):
        self.login_btn.setEnabled(True)
        if not ok:
            self.status.setStyleSheet("color: #FF3B30;")
            self.status.setText(f"登录失败: {message}")
            self._append_log(f"[登录] 登录失败: {message}")
            return
        self.last_userid = userid
        self.last_password = password
        self.last_user_text = userid
        self.status.setStyleSheet("color: #34C759;")
        self.status.setText(f"登录成功: {userid}")
        self._append_log("[登录] 登录成功,进入操作界面 ...")
        self.login_ok.emit(userid)
        self.accept()

    def _do_mail_login(self):
        self._manual_login_started = True
        userid = self.user_edit.text().strip()
        password = self.pwd_edit.text()
        if not userid or not password:
            QMessageBox.warning(self, "提示", "请输入一账通账号和密码。")
            return
        self.login_btn.setEnabled(False)
        self.status.setText("正在发送验证码到邮箱 ...")
        self._append_log("[登录] 开始邮箱验证码登录 ...")
        self.mail_worker = MailCodeWorker(userid=userid, password=password)
        self.mail_worker.log_line.connect(self._append_log)
        self.mail_worker.code_required.connect(self._ask_mail_code)
        self.mail_worker.done.connect(self._login_done)
        self.mail_worker.user_info.connect(self._on_user_info)
        self.mail_worker.start()

    def _ask_mail_code(self, prompt: str):
        self.status.setText("请输入邮箱验证码")
        code, ok = QInputDialog.getText(
            self, "邮箱验证码", prompt, QLineEdit.Normal, "")
        if not (ok and code.strip()):
            self.login_btn.setEnabled(True)
            self.status.setText("已取消登录")
            self._append_log("[登录] 用户取消输入验证码")
            return
        self.status.setText("正在提交验证码并换取 token ...")
        self._append_log("[登录] 收到验证码,提交并换 token ...")
        self.mail_worker2 = MailCodeWorker(
            userid=self.user_edit.text().strip(),
            password=self.pwd_edit.text(),
            code=code.strip(),
        )
        self.mail_worker2.log_line.connect(self._append_log)
        self.mail_worker2.done.connect(self._login_done)
        self.mail_worker2.user_info.connect(self._on_user_info)
        self.mail_worker2.start()

    def _verify_token(self):
        self._manual_login_started = True
        token = self.token_edit.text().strip()
        if not token:
            QMessageBox.warning(
                self, "提示",
                "请先在 tokenbylogin 页面登录后复制 Token:\n"
                "http://10.151.130.134:8086/#/tokenbylogin",
            )
            return
        self.verify_token_btn.setEnabled(False)
        self.status.setText("正在验证 Token ...")
        self._append_log("[登录] 开始验证手动 Token ...")
        self.auth_worker = AuthWorker(token=token)
        self.auth_worker.log_line.connect(self._append_log)
        self.auth_worker.done.connect(self._login_done)
        self.auth_worker.start()

    def _open_token_page(self):
        url = QUrl("http://10.151.130.134:8086/#/tokenbylogin")
        ok = QDesktopServices.openUrl(url)
        if not ok:
            QMessageBox.warning(
                self, "提示",
                "无法自动打开浏览器,请手动访问:\n"
                "http://10.151.130.134:8086/#/tokenbylogin",
            )
        else:
            self._append_log("[登录] 已在浏览器打开 tokenbylogin 页面,"
                             "登录后复制 Token 粘贴回来。")

    def _on_user_info(self, user_text: str):
        self.last_user_text = user_text

    def _login_done(self, ok: bool, token: str, message: str):
        sender = self.sender()
        if self._auto_worker is not None and sender is self._auto_worker:
            # 后台自动 token 校验的结果
            if self._manual_login_started:
                return  # 用户已选择手动登录,忽略迟到的自动结果
            if not ok:
                self._auto_worker = None
                self.status.setStyleSheet("color: #FF9500;")
                self.status.setText("已保存 token 失效,请选择登录方式")
                self._append_log("[登录] 已保存 token 失效,请手动登录")
                return
            self._auto_worker = None
            # token 有效:直接进入(未手动操作时)
            user_text = self.last_user_text or _jwt_user(token)
            self.status.setStyleSheet("color: #34C759;")
            self.status.setText(f"已保存 token 有效,自动登录成功: "
                                f"{user_text or token[:20] + '...'}")
            self._append_log("[登录] 已保存 token 有效,自动进入操作界面 ...")
            self.login_ok.emit(user_text)
            self.accept()
            return
        self.login_btn.setEnabled(True)
        self.verify_token_btn.setEnabled(True)
        if message == "NEED_CODE":
            return  # code_required 已接管
        if not ok:
            self.status.setStyleSheet("color: #FF3B30;")
            self.status.setText(f"登录失败: {message}")
            self._append_log(f"[登录] 登录失败: {message}")
            return
        user_text = self.last_user_text or _jwt_user(token)
        if not self.last_userid:
            self.last_userid = self.user_edit.text().strip()
            self.last_password = self.pwd_edit.text()
        self.status.setStyleSheet("color: #34C759;")
        self.status.setText(f"登录成功: {user_text or token[:20] + '...'}")
        self._append_log("[登录] 登录成功,进入操作界面 ...")
        self.login_ok.emit(user_text)
        self.accept()

    def _auto_check_saved_token(self):
        """启动时若有已保存 token,后台验证,通过则直接进入主界面。"""
        try:
            base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
                else Path(__file__).resolve().parent
            cfg_path = base / "config.json"
            if not cfg_path.exists():
                return
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            token = (cfg.get("c4") or {}).get("token", "")
            if not token:
                return
            self.status.setText("检测到已保存 token,正在验证 ...")
            self._append_log("[登录] 检测到已保存 token,自动验证中 ...")
            self.auth_worker = AuthWorker(token=token)
            self.auth_worker.log_line.connect(self._append_log)
            self.auth_worker.done.connect(self._login_done)
            self._auto_worker = self.auth_worker
            self.auth_worker.start()
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"[登录] 自动验证跳过: {exc}")

    def _append_log(self, msg: str):
        self.log_view.append(msg)
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum())


def main() -> int:
    try:
        # 高分屏缩放必须在 QApplication 创建之前(Windows 缩放清晰)
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        app = QApplication(sys.argv[:1])
        app.setApplicationName("SN_Report")
        # 登录门禁:模拟 C4 登录,通过后才进入操作界面
        login = LoginWindow()
        if login.exec_() != QDialog.Accepted:
            return 0
        win = MainWindow()
        win.set_login_user(login.last_user_text, login.last_userid,
                           login.last_password)
        win.show()
        return app.exec_()
    except Exception:  # noqa: BLE001
        (BASE_DIR / "crash.log").write_text(
            traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    sys.exit(main())
