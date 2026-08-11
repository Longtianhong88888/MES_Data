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
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Optional

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
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QTextEdit, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFileDialog, QMessageBox,
    QProgressBar, QMainWindow, QStatusBar,
    QComboBox,
)

from run_gp_download import (
    GreenplumSerin, extract_images, try_download,
    DOMAIN_IP_MAP, load_sn_list,
)
from excel_report import build_excel
from apple_style import APPLE_QSS, C_BG, C_SUB, card, hint


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
    done = pyqtSignal(dict, str)  # (result, excel_path)

    def __init__(self, sns: List[str], download_dir: Path,
                 host: str, port: int, database: str, user: str, password: str,
                 project: str = ""):
        super().__init__()
        self.sns = sns
        self.download_dir = download_dir
        self.project = project
        self.gp = GreenplumSerin(host=host, port=port, database=database,
                                 user=user, password=password)
        self._stop = False

    def stop(self):
        self._stop = True

    def emit(self, msg: str):
        self.log_line.emit(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def run(self):
        result = {"sn_count": len(self.sns), "total": 0, "downloaded": 0,
                  "failed": 0, "sns": {}}
        excel_path = ""
        try:
            self.gp.connect()
            self.emit(f"Greenplum 连接成功: {self.gp.host}:{self.gp.port}/{self.gp.database}")
            self.projects = self.gp.list_projects()
            if self.project:
                self.emit(f"专案: {self.project}")
            else:
                self.emit(f"专案: 自动识别(共 {len(self.projects)} 个专案)")
        except Exception as exc:  # noqa: BLE001
            self.emit(f"Greenplum 连接失败: {exc}")
            self.done.emit(result, "")
            return

        for i, sn in enumerate(self.sns, start=1):
            if self._stop:
                break
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
                for img in imgs:
                    if self._stop:
                        break
                    dest = self.download_dir / sn / "EOL" / f"{img['station']}_{len(per_sn['eol'])}.jpg"
                    ok = try_download(img["url"], dest)[0]
                    img["downloaded"] = ok
                    img["dest"] = str(dest)
                    per_sn["eol"].append(img)
                    per_sn["count"] += 1
                    if ok:
                        per_sn["downloaded"] += 1
                    else:
                        per_sn["failed"] += 1

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
                        for img in imgs:
                            if self._stop:
                                break
                            dest = self.download_dir / sn / "FOL" / f"{img['station']}_{len(per_sn['fol'])}.jpg"
                            ok = try_download(img["url"], dest)[0]
                            img["downloaded"] = ok
                            img["dest"] = str(dest)
                            per_sn["fol"].append(img)
                            per_sn["count"] += 1
                            if ok:
                                per_sn["downloaded"] += 1
                            else:
                                per_sn["failed"] += 1
            else:
                self.emit("  EOL 无数据(SN 不存在或非 BOI 机种)")
            result["sns"][sn] = per_sn
            result["total"] += per_sn["count"]
            result["downloaded"] += per_sn["downloaded"]
            result["failed"] += per_sn["failed"]
            self.progress.emit(i, len(self.sns))
            self.emit(f"  本 SN: 照片 {per_sn['count']} 张,下载 {per_sn['downloaded']} 张")

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
        self.done.emit(result, excel_path)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SN_Report - Greenplum Serin 照片一键下载")
        w, h = window_target_size()
        self.resize(w, h)
        self.setMinimumSize(max(720, int(w * 0.82)), max(560, int(h * 0.85)))
        self.worker: Optional[DownloadWorker] = None
        self.setStyleSheet(APPLE_QSS)
        self._create_menu()
        self._build_ui()

    def _create_menu(self):
        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction("选择 SN 文件", self._pick_file)
        file_menu.addAction("选择保存目录", self._pick_dir)
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close)

        help_menu = self.menuBar().addMenu("帮助")
        help_menu.addAction("关于", self._show_about)

    def _build_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

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
        self.sn_edit.setFixedHeight(90)
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

        # ─── 保存目录卡片 ───
        dir_grid = QGridLayout()
        dir_grid.setVerticalSpacing(6)
        dir_grid.setHorizontalSpacing(8)
        dir_grid.addWidget(QLabel("保存目录"), 0, 0)
        self.dir_edit = QLineEdit(str(BASE_DIR / "downloads"))
        dir_grid.addWidget(self.dir_edit, 0, 1)
        self.dir_btn = QPushButton("浏览")
        self.dir_btn.setProperty("secondary", True)
        self.dir_btn.clicked.connect(self._pick_dir)
        dir_grid.addWidget(self.dir_btn, 0, 2)
        dir_grid.setColumnStretch(1, 1)
        root.addWidget(card("输出设置", dir_grid))

        # ─── 进度条 ───
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setFixedHeight(8)
        root.addWidget(self.progress)

        # ─── 日志卡片 ───
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(0, 0, 0, 0)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("logView")
        self.log_view.setPlaceholderText("下载日志将显示在此处 ...")
        log_layout.addWidget(self.log_view)
        root.addWidget(card("运行日志", log_layout), 1)

        # ─── 操作按钮 ───
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.start_btn = QPushButton("开始下载")
        self.start_btn.setProperty("primary", True)
        self.start_btn.setDefault(True)
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setProperty("danger", True)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        btn_row.addStretch(1)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.start_btn)
        root.addLayout(btn_row)

        # ─── 状态栏 ───
        sb = self.statusBar()
        sb.showMessage("就绪")
        sb_label = QLabel("SN_Report © 2026")
        sb_label.setStyleSheet(f"color: {C_SUB}; font-size: 11px;")
        sb.addPermanentWidget(sb_label)

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
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self.worker = DownloadWorker(
            sns, dl_dir,
            DB_CFG["host"], DB_CFG["port"], DB_CFG["database"],
            DB_CFG["user"], DB_CFG["password"], project=project)
        self.worker.log_line.connect(self._append_log)
        self.worker.progress.connect(lambda i, n: self.progress.setValue(i))
        self.worker.done.connect(self._done)
        self.worker.start()

    def _refresh_projects(self):
        """连接 Greenplum 并刷新专案下拉列表(同步,短暂阻塞)。"""
        if self.project_combo.count() > 1:
            return  # 已加载
        try:
            gp = GreenplumSerin(
                host=DB_CFG["host"], port=DB_CFG["port"],
                database=DB_CFG["database"],
                user=DB_CFG["user"], password=DB_CFG["password"])
            gp.connect()
            projs = gp.list_projects()
            for p in projs:
                self.project_combo.addItem(p.upper(), p)
            self.project_hint.setText(f"已加载 {len(projs)} 个专案")
        except Exception as exc:  # noqa: BLE001
            self.project_hint.setText("专案加载失败(检查 config.json 连接配置)")

    def _stop(self):
        if self.worker:
            self.worker.stop()
            self._append_log("[!] 停止请求已发送,等待当前文件完成...")

    def _append_log(self, msg: str):
        self.log_view.append(msg)
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum())

    def _done(self, result: dict, excel_path: str):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
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


def main() -> int:
    try:
        # 高分屏缩放必须在 QApplication 创建之前(Windows 缩放清晰)
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        app = QApplication(sys.argv[:1])
        app.setApplicationName("SN_Report")
        win = MainWindow()
        win.show()
        return app.exec_()
    except Exception:  # noqa: BLE001
        (BASE_DIR / "crash.log").write_text(
            traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    sys.exit(main())
