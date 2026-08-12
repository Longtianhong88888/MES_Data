"""登录界面(PyQt5):让用户在图形界面里输入 Rayprush 一账通账号密码 / C4 Token / 时间窗。

功能:
- 字段预填现有 config.json 的值;
- 「登录测试」用输入的账号实际验证 Rayprush 一账通(10.151.128.45:8081),
  验证通过后才允许保存并继续;
- 「保存」把账号写入根 config.json,C4 Token 与分析时间窗写入 sn_report/config.json;
- 「记住密码」不勾选时,密码只保留在本次运行内存中,不写入磁盘。

依赖 PyQt5(Windows 打包时随 exe 内置;便携版 Python 需另装)。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QDateTimeEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .config import PROJECT_DIR, SN_REPORT_DIR, _load_json


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class _LoginWorker(QThread):
    """后台线程执行 Rayprush 一账通验证,避免界面卡死。"""

    finished_ok = pyqtSignal(int)
    finished_err = pyqtSignal(str)

    def __init__(self, root_cfg: Dict[str, Any]) -> None:
        super().__init__()
        self.root_cfg = root_cfg

    def run(self) -> None:
        try:
            from .rayprush_auth import RayprushAuth

            auth = RayprushAuth(
                login_url=self.root_cfg.get("login_url")
                or "http://10.151.128.45:8081/"
            )
            ok, msg = auth.login(
                self.root_cfg.get("username", ""),
                self.root_cfg.get("password", ""),
            )
            if ok:
                self.finished_ok.emit(0)
            else:
                self.finished_err.emit(msg)
        except Exception as exc:  # noqa: BLE001
            self.finished_err.emit(str(exc))


class LoginDialog(QDialog):
    """MES 登录信息输入对话框。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rayprush 一账通登录 - 全制程追溯")
        self.setMinimumWidth(560)

        self.root_cfg: Dict[str, Any] = {}
        self.sn_cfg: Dict[str, Any] = {}

        root_path = PROJECT_DIR / "config.json"
        sn_path = SN_REPORT_DIR / "config.json"
        self._root_path = root_path
        self._sn_path = sn_path
        old_root = _load_json(root_path)
        old_sn = _load_json(sn_path)

        form = QFormLayout()
        self.login_url_edit = QLineEdit(str(old_root.get("login_url", "")))
        self.login_url_edit.setPlaceholderText("Rayprush 一账通地址(默认 http://10.151.128.45:8081/)")
        self.username_edit = QLineEdit(str(old_root.get("username", "")))
        self.username_edit.setPlaceholderText("一账通账号")
        self.password_edit = QLineEdit(str(old_root.get("password", "")))
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("一账通密码")
        self.resource_edit = QLineEdit(str(old_root.get("resource_url", "")))
        self.resource_edit.setPlaceholderText("应用入口(可选,留空自动用登录地址)")

        self.remember_chk = QCheckBox("记住密码(写入本地 config.json)")
        self.remember_chk.setChecked(bool(old_root.get("password")))
        self.show_pw_chk = QCheckBox("显示密码")
        self.show_pw_chk.toggled.connect(
            lambda on: self.password_edit.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password
            )
        )
        pw_row = QWidget()
        pw_lay = QHBoxLayout(pw_row)
        pw_lay.setContentsMargins(0, 0, 0, 0)
        pw_lay.addWidget(self.password_edit)
        pw_lay.addWidget(self.show_pw_chk)

        form.addRow("一账通地址", self.login_url_edit)
        form.addRow("一账通账号", self.username_edit)
        form.addRow("一账通密码", pw_row)
        form.addRow("应用入口", self.resource_edit)
        form.addRow("", self.remember_chk)

        self.token_edit = QPlainTextEdit(str((old_sn.get("c4") or {}).get("token", "")))
        self.token_edit.setPlaceholderText(
            "战情中心 C4 Token(可选)\n获取: 登录 http://10.151.130.134:8086/#/tokenbylogin 后复制"
        )
        self.token_edit.setFixedHeight(64)
        form.addRow("C4 Token", self.token_edit)

        window = old_sn.get("analysis_window", {})
        self.start_edit = QDateTimeEdit(
            datetime.strptime(str(window.get("start", "2026-06-01 00:00")).strip(), "%Y-%m-%d %H:%M")
        )
        self.start_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.start_edit.setCalendarPopup(True)
        self.end_edit = QDateTimeEdit(
            datetime.strptime(str(window.get("end", "2026-08-08 23:59")).strip(), "%Y-%m-%d %H:%M")
        )
        self.end_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.end_edit.setCalendarPopup(True)
        win_row = QWidget()
        win_lay = QHBoxLayout(win_row)
        win_lay.setContentsMargins(0, 0, 0, 0)
        win_lay.addWidget(QLabel("从"))
        win_lay.addWidget(self.start_edit)
        win_lay.addWidget(QLabel("到"))
        win_lay.addWidget(self.end_edit)
        form.addRow("分析时间窗", win_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #b00;")

        self.test_btn = QPushButton("登录测试")
        self.save_btn = QPushButton("保存并关闭")
        self.cancel_btn = QPushButton("取消")
        self.save_btn.setDefault(True)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.test_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.save_btn)

        root_lay = QVBoxLayout(self)
        root_lay.addLayout(form)
        root_lay.addWidget(self.status_label)
        root_lay.addLayout(btn_row)

        self.test_btn.clicked.connect(self._test_login)
        self.save_btn.clicked.connect(self._save)
        self.cancel_btn.clicked.connect(self.reject)

        self._worker: Optional[_LoginWorker] = None
        self._verified = False

    def _collect_root(self, remember: bool) -> Dict[str, Any]:
        old = _load_json(self._root_path)
        root = dict(old)
        root["login_url"] = self.login_url_edit.text().strip()
        root["username"] = self.username_edit.text().strip()
        root["password"] = self.password_edit.text() if remember else ""
        resource = self.resource_edit.text().strip()
        if resource:
            root["resource_url"] = resource
        return root

    def _collect_sn(self) -> Dict[str, Any]:
        old = _load_json(self._sn_path)
        sn = dict(old)
        sn.setdefault("c4", {})["token"] = self.token_edit.toPlainText().strip()
        sn.setdefault("analysis_window", {})["start"] = self.start_edit.dateTime().toString("yyyy-MM-dd HH:mm")
        sn.setdefault("analysis_window", {})["end"] = self.end_edit.dateTime().toString("yyyy-MM-dd HH:mm")
        return sn

    def _test_login(self) -> None:
        root = self._collect_root(remember=True)
        if not root.get("username") or not root.get("password"):
            self.status_label.setText("请填写一账通账号和密码后再验证。")
            return
        self.test_btn.setEnabled(False)
        self.status_label.setText("正在验证 Rayprush 一账通 ...")
        self._worker = _LoginWorker(root)
        self._worker.finished_ok.connect(self._test_ok)
        self._worker.finished_err.connect(self._test_err)
        self._worker.start()

    def _test_ok(self, _frame_count: int) -> None:
        self.test_btn.setEnabled(True)
        self._verified = True
        self.status_label.setStyleSheet("color: #080;")
        self.status_label.setText("一账通验证通过,可以保存后继续。")
        QMessageBox.information(self, "登录验证", "一账通账号密码验证通过")

    def _test_err(self, msg: str) -> None:
        self.test_btn.setEnabled(True)
        self._verified = False
        self.status_label.setStyleSheet("color: #b00;")
        self.status_label.setText(f"验证失败: {msg}")
        QMessageBox.warning(self, "登录验证", f"一账通验证失败:\n{msg}")

    def _save(self) -> None:
        if not self._verified:
            self.status_label.setText("请先点击「登录测试」验证一账通账号密码。")
            QMessageBox.warning(
                self, "未验证",
                "必须先通过 Rayprush 一账通验证,才能保存并继续。\n"
                "请点击「登录测试」验证账号密码。",
            )
            return
        remember = self.remember_chk.isChecked()
        root = self._collect_root(remember=remember)
        if not root.get("username"):
            self.status_label.setText("请填写一账通账号。")
            return
        if not root.get("password"):
            self.status_label.setText("密码为空;若不想保存密码,请取消勾选「记住密码」并输入本次使用的密码。")
            return

        _write_json(self._root_path, root)
        _write_json(self._sn_path, self._collect_sn())

        self.root_cfg = self._collect_root(remember=True)
        self.sn_cfg = self._collect_sn()
        if not remember:
            self.status_label.setText("已保存(密码未写入磁盘,仅本次运行有效)。")
        self.accept()
