"""C4 通行权限登录(模拟 CimTool TokenLogin/UserLogin)。

链路(逆向自 CimTool.exe):
1. POST https://tasksd.efoxconn.com:8080/api/User {userName,password}
   -> 返回 JWT(tokenbylogin 授权中心)
2. GET  http://10.151.128.181:8081/api/BelieveAuthPoint/VerifySignatureAndCode
   ?signedDataString=<JWT> -> 验证签名,通过后 IIOT 服务端可访问 10.142.116.140
3. GET  http://10.151.128.181:8081/api/BelieveAuthPoint/AuthorizeEndpoint
   ?syscode=S20230111001&signcode=IDLSystem&userid=&password=&ipaddress=
   -> 老版登录(转调 Foxconn SSO)
"""

from __future__ import annotations

import json
import ssl
import http.cookiejar
import urllib.error
import urllib.request
import urllib.parse
from typing import Optional, Tuple


class C4Auth:
    TOKEN_URL = "https://tasksd.efoxconn.com:8080/api/User"
    VERIFY_URL = "http://10.151.128.181:8081/api/BelieveAuthPoint/VerifySignatureAndCode"
    AUTHORIZE_URL = "http://10.151.128.181:8081/api/BelieveAuthPoint/AuthorizeEndpoint"
    GET_TOKEN_BELIEVE = "http://10.151.128.181:8081/api/BelieveAuthPoint/GetTokenByBelieve"
    INFO_DT_URL = "http://10.151.128.35:8095/api/MachineParameter/GetInformationDT"
    SSO_AUTHORIZE = "https://sso.foxconn.com/connect/authorize"
    SSO_MAIL_SEND = "https://sso.foxconn.com/Civet/LoginStandard/mailSendCode"
    SSO_MAIL_LOGIN = "https://sso.foxconn.com/Civet/LoginStandard/mailLogin"
    SSO_CALLBACK = "http://localhost:60322/Home/HomeMain"
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.token: Optional[str] = None
        self.user_info: dict = {}
        self.sso_cookies = None
        # tokenbylogin 用 HTTPS(自签名),关闭证书校验
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self._ctx),
            urllib.request.HTTPCookieProcessor(self._jar),
        )

    def login(self, userid: str, password: str) -> Tuple[bool, str]:
        """一账通账号密码换 JWT。返回 (是否成功, token/说明)。"""
        body = json.dumps({"userName": userid, "password": password}).encode()
        req = urllib.request.Request(
            self.TOKEN_URL, data=body,
            headers={"User-Agent": self.UA, "Content-Type": "application/json"},
        )
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx)
            data = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            return False, f"登录请求 HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001
            return False, f"登录请求失败: {exc}"

        if not data.get("status"):
            return False, str(data.get("message") or "登录失败")
        token = data.get("data") or data.get("token") or ""
        if isinstance(token, dict):
            token = token.get("token") or token.get("access_token") or ""
        if not token:
            return False, "响应中未找到 token"
        self.token = token
        self.user_info = data
        return True, token

    def verify(self) -> Tuple[bool, str]:
        """IIOT VerifySignatureAndCode 验证当前 JWT。"""
        return self.verify_token(self.token or "")

    def verify_token(self, token: str) -> Tuple[bool, str]:
        """验证用户手动获取的 JWT。

        VerifySignatureAndCode 对完整 JWT 会报 Invalid signature(它要的是从
        JWT 提取的片段),因此以 GetInformationDT 实测为准:能查到 BOI-T
        即说明 token 有效、服务端授予了访问权限。
        """
        if not token:
            return False, "token 为空"
        self.token = token
        # 用 GetInformationDT 实测(BOI-T 是服务端已配置的机种)
        ok, payload = self.get_information_dt(
            device="BOI-T",
            sn="DNMHTV000F50000Y2N+2001+Q",
            columns=["sn"],
        )
        if ok:
            return True, "验证通过(token 有效,服务端授予访问权限)"
        msg = str(payload.get("message") or payload.get("Message") or "验证失败")
        # 兼容: 若 GetInformationDT 未配置但 VerifySignatureAndCode 通过
        url = self.VERIFY_URL + "?" + urllib.parse.urlencode(
            {"signedDataString": token})
        req = urllib.request.Request(url, headers={"User-Agent": self.UA})
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            data = json.loads(resp.read().decode("utf-8", "replace"))
            if data.get("status"):
                return True, "验证通过(VerifySignatureAndCode)"
        except Exception:
            pass
        return False, msg

    def authorize(self, userid: str, password: str, ip: str = "") -> Tuple[bool, str]:
        """老版 AuthorizeEndpoint(转调 Foxconn SSO)。"""
        params = {
            "syscode": "S20230111001",
            "signcode": "IDLSystem",
            "userid": userid,
            "password": password,
            "ipaddress": ip,
        }
        url = self.AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": self.UA})
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            data = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            return False, f"授权请求失败: {exc}"
        if data.get("status"):
            return True, str(data.get("data") or "授权通过")
        return False, str(data.get("message") or "授权失败")

    def get_information_dt(self, device: str, sn: str,
                           columns: Optional[list] = None,
                           plant_id: str = "8S01",
                           type_: str = "8S01") -> Tuple[bool, dict]:
        """GetInformationDT 查询(表单编码 POST,逆向确认的绑定方式)。

        返回 (是否成功, {status, message, resultvalue})。
        """
        if not self.token:
            return False, {"message": "未登录,请先获取权限"}
        form = {
            "Device": device,
            "plantID": plant_id,
            "type": type_,
            "ColumnSelect": ",".join(columns or ["sn"]),
            "snlist": sn,
        }
        data = urllib.parse.urlencode(form, doseq=True).encode()
        req = urllib.request.Request(
            self.INFO_DT_URL, data=data,
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": self.UA,
            },
        )
        try:
            resp = urllib.request.urlopen(req, timeout=60)
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8", "replace"))
            except Exception:
                payload = {"status": False, "message": f"HTTP {exc.code}"}
        except Exception as exc:  # noqa: BLE001
            return False, {"message": f"查询失败: {exc}"}
        return bool(payload.get("status")), payload

    # ---------- SSO 邮箱验证登录(复刻 C4) ----------
    def authorize_url(self, userid: str, password: str, ip: str = "") -> Tuple[bool, str]:
        """AuthorizeEndpoint 换 SSO 授权 URL(带 state,进入 MFA)。"""
        params = {
            "syscode": "S20230111001",
            "signcode": "IDLSystem",
            "userid": userid,
            "password": password,
            "ipaddress": ip,
        }
        url = self.AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": self.UA})
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            data = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            return False, f"授权请求失败: {exc}"
        if not data.get("status"):
            return False, str(data.get("message") or "授权失败")
        return True, str(data.get("resultvalue") or "")

    def sso_mfa_page(self, authorize_url: str) -> Tuple[bool, str, str]:
        """访问 SSO 授权 URL,进入 MFA 页。返回 (ok, RequestVerificationToken, mfa页html)。"""
        # SSO 返回的 URL 可能含未编码的空格(scope 参数),先规范编码
        authorize_url = authorize_url.replace(" ", "%20")
        req = urllib.request.Request(authorize_url, headers={"User-Agent": self.UA})
        try:
            resp = self._opener.open(req, timeout=self.timeout)
            body = resp.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            return False, "", f"SSO 页面访问失败: {exc}"
        import re
        m = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]*)"', body)
        token = m.group(1) if m else ""
        return True, token, body

    def sso_send_mail_code(self, userid: str, mail_type: str,
                           request_token: str) -> Tuple[bool, str]:
        """发送邮箱验证码。mail_type 常见: Mail/Outlook 等。"""
        data = urllib.parse.urlencode({
            "MailUserId": userid,
            "MailType": mail_type,
            "__RequestVerificationToken": request_token,
        }).encode()
        req = urllib.request.Request(
            self.SSO_MAIL_SEND, data=data,
            headers={"User-Agent": self.UA, "Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            resp = self._opener.open(req, timeout=self.timeout)
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            return False, f"发送验证码失败: {exc}"
        if payload.get("result") == 1:
            return True, "验证码已发送到邮箱"
        return False, str(payload.get("msg") or "发送失败")

    def sso_mail_login(self, userid: str, mail_type: str, verify_code: str,
                       return_url: str, request_token: str) -> Tuple[bool, str]:
        """提交邮箱验证码,成功返回跳转 URL(带 code)。"""
        data = urllib.parse.urlencode({
            "MailUserId": userid,
            "MailType": mail_type,
            "VerifyCode": verify_code,
            "ReturnUrl": return_url,
            "__RequestVerificationToken": request_token,
        }).encode()
        req = urllib.request.Request(
            self.SSO_MAIL_LOGIN, data=data,
            headers={"User-Agent": self.UA, "Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            resp = self._opener.open(req, timeout=self.timeout)
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            return False, f"邮箱验证提交失败: {exc}"
        if payload.get("result") == 1:
            return True, str(payload.get("ReturnUrl") or "")
        return False, str(payload.get("msg") or "验证码错误")

    def sso_get_token(self, userid: str, password: str, verify_code: str = "",
                      mail_type: str = "auth_mail") -> Tuple[bool, str]:
        """完整 SSO 邮箱验证登录:AuthorizeEndpoint -> MFA页 -> 验证码 -> 回调 code
        -> GetTokenByBelieve 换 JWT。

        必须在一个会话内连续完成(回调 URL 里的 state 自带 ~10 分钟有效期,
        且 OAuth code 一次性消费)。verify_code 为空则先发码到邮箱。
        返回 (是否成功, token/说明)。
        """
        import re

        # 1) AuthorizeEndpoint -> SSO 授权 URL
        ok, msg = self.authorize_url(userid, password)
        if not ok:
            return False, f"获取 SSO 授权 URL 失败: {msg}"
        auth_url = msg.replace(" ", "%20")

        # 2) 访问 SSO URL -> MFA 页,拿防伪 token
        ok, rv, _body = self.sso_mfa_page(auth_url)
        if not ok or not rv:
            return False, rv or "进入 MFA 页面失败(未取得防伪 token)"

        # 3) 发送/提交邮箱验证码
        if not verify_code:
            ok, msg = self.sso_send_mail_code(userid, mail_type, rv)
            if not ok:
                return False, msg
            return False, "VERIFY_CODE_REQUIRED|" + msg

        ok, msg = self.sso_mail_login(userid, mail_type, verify_code, auth_url, rv)
        if not ok:
            return False, f"验证码提交失败: {msg}"
        return_url = msg

        # 4) 跟随 ReturnUrl,拦截 C4 本机回调(localhost:60322)抓 code/state
        code, state = self._follow_sso_callback(return_url)
        if not code or not state:
            return False, "回调未取得 code/state(可能验证码过期或会话失效)"

        # 5) GetTokenByBelieve 换 JWT(state 有效期 ~10 分钟,立即换)
        q = urllib.parse.urlencode({
            "code": code,
            "signedDataString": urllib.parse.unquote(state),
        })
        req = urllib.request.Request(
            self.GET_TOKEN_BELIEVE + "?" + q,
            headers={"User-Agent": self.UA},
        )
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            return False, f"换 token 失败: HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001
            return False, f"换 token 失败: {exc}"

        if not (payload.get("status") or payload.get("code") == 200):
            return False, str(payload.get("message") or "换 token 失败")
        data = payload.get("data") or {}
        token = data.get("token") or ""
        if not token:
            return False, "响应中未找到 token"
        self.token = token
        info = data.get("userInfo") or {}
        self.user_info = {
            "userid": info.get("userid", ""),
            "username": info.get("username", ""),
            "userMail": info.get("userMail", ""),
            "expMinutes": data.get("expMinutes", ""),
        }
        return True, token

    def _follow_sso_callback(self, return_url: str) -> Tuple[str, str]:
        """跟随 SSO ReturnUrl 直到 localhost 回调,提取 (code, state)。

        用自定义 redirect handler 拦截对 localhost:60322 的跳转
        (C4 回调地址,本机无监听),避免 Connection refused。
        """
        class _Capture(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                self.last = newurl
                host = urllib.parse.urlparse(newurl).hostname or ""
                if host in ("localhost", "127.0.0.1"):
                    self.callback = newurl
                    return None
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        capture = _Capture()
        # 复用 self._jar:MFA 页/验证码提交建立的 SSO 会话 cookie 必须保留
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self._ctx),
            urllib.request.HTTPCookieProcessor(self._jar),
            capture,
        )
        req = urllib.request.Request(return_url, headers={"User-Agent": self.UA})
        try:
            opener.open(req, timeout=30)
            final_url = capture.callback or capture.last or ""
        except Exception:
            final_url = capture.callback or capture.last or ""
        if not final_url:
            return "", ""
        import re
        m = re.search(r"[?&]code=([^&\s]+)", final_url)
        code = m.group(1) if m else ""
        m = re.search(r"[?&]state=([^&\s]+)", final_url)
        state = m.group(1) if m else ""
        return code, state


if __name__ == "__main__":
    import sys

    auth = C4Auth()
    ok, msg = auth.login(
        sys.argv[1] if len(sys.argv) > 1 else "",
        sys.argv[2] if len(sys.argv) > 2 else "",
    )
    print("LOGIN:", "OK" if ok else "FAIL", "|", msg[:120] if not ok else msg[:80])
    if ok:
        ok2, msg2 = auth.verify()
        print("VERIFY:", "OK" if ok2 else "FAIL", "|", msg2)
