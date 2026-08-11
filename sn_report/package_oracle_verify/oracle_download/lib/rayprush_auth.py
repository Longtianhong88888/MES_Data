"""Rayprush 一账通登录验证(10.151.128.45:8081)。

登录页是 ASP.NET WebForms:
    GET  /  拿 __VIEWSTATE/__VIEWSTATEGENERATOR/__EVENTVALIDATION
    POST /  带 Login1$useridtb / Login1$userpwdtb / Login1$LoginImageButton
失败:HTTP 200 且页面含 <script>alert('用戶信息不存在'|'密碼錯誤'...)</script>
成功:跳转到业务页(URL 离开 /,或不再出现登录表单)。
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from typing import Optional, Tuple


class RayprushAuth:
    LOGIN_URL = "http://10.151.128.45:8081/"
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

    def __init__(self, login_url: Optional[str] = None, timeout: int = 15) -> None:
        self.login_url = (login_url or self.LOGIN_URL).rstrip("/") + "/"
        self.timeout = timeout
        self.cookies: Optional[str] = None

    def _get(self, url: str) -> Tuple[str, dict]:
        req = urllib.request.Request(url, headers={"User-Agent": self.UA})
        resp = urllib.request.urlopen(req, timeout=self.timeout)
        headers = dict(resp.headers)
        return resp.read().decode("utf-8", "replace"), headers

    @staticmethod
    def _hidden(body: str, name: str) -> str:
        m = re.search(r'name="%s"[^>]*value="([^"]*)"' % re.escape(name), body)
        return m.group(1) if m else ""

    def _login_page(self) -> Tuple[str, str, str, str]:
        body, _ = self._get(self.login_url)
        return (
            body,
            self._hidden(body, "__VIEWSTATE"),
            self._hidden(body, "__VIEWSTATEGENERATOR"),
            self._hidden(body, "__EVENTVALIDATION"),
        )

    def login(self, userid: str, password: str) -> Tuple[bool, str]:
        """验证一账通账号密码。返回 (是否通过, 说明)。"""
        userid = (userid or "").strip()
        if not userid or not password:
            return False, "请填写一账通账号与密码"
        try:
            _, vs, vg, ev = self._login_page()
        except Exception as exc:  # noqa: BLE001
            return False, f"无法访问登录页 {self.login_url}: {exc}"
        if not vs:
            return False, "登录页缺少 __VIEWSTATE,页面结构可能变化"

        data = urllib.parse.urlencode({
            "__LASTFOCUS": "",
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": vs,
            "__VIEWSTATEGENERATOR": vg,
            "__EVENTVALIDATION": ev,
            "Login1$useridtb": userid,
            "Login1$userpwdtb": password,
            "Login1$LoginImageButton": "登 入",
        }).encode()
        req = urllib.request.Request(
            self.login_url,
            data=data,
            headers={
                "User-Agent": self.UA,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": self.login_url,
            },
        )
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            return False, f"登录请求返回 HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001
            return False, f"登录请求失败: {exc}"

        final_url = resp.geturl()
        body = resp.read().decode("utf-8", "replace")
        self.cookies = resp.headers.get("Set-Cookie")

        # 失败:页面出现 alert('...') 提示
        alert = re.search(r"alert\('([^']*)'\)", body)
        if alert:
            return False, alert.group(1) or "登录失败"

        # 失败:仍是登录表单页(未跳转)
        if "Login1$useridtb" in body and final_url.rstrip("/") == self.login_url.rstrip("/"):
            return False, "账号或密码错误(仍停留在登录页)"

        # 成功:跳离登录页 / 不再出现登录表单
        if final_url.rstrip("/") != self.login_url.rstrip("/") or "Login1$useridtb" not in body:
            return True, "验证通过"
        return False, "登录结果无法确认,请人工检查"


if __name__ == "__main__":
    import sys

    auth = RayprushAuth()
    ok, msg = auth.login(
        sys.argv[1] if len(sys.argv) > 1 else "",
        sys.argv[2] if len(sys.argv) > 2 else "",
    )
    print("OK" if ok else "FAIL", "|", msg)
