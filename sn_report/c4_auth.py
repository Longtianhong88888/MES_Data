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
import urllib.request
import urllib.parse
from typing import Optional, Tuple


class C4Auth:
    TOKEN_URL = "https://tasksd.efoxconn.com:8080/api/User"
    VERIFY_URL = "http://10.151.128.181:8081/api/BelieveAuthPoint/VerifySignatureAndCode"
    AUTHORIZE_URL = "http://10.151.128.181:8081/api/BelieveAuthPoint/AuthorizeEndpoint"
    INFO_DT_URL = "http://10.151.128.35:8095/api/MachineParameter/GetInformationDT"
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.token: Optional[str] = None
        self.user_info: dict = {}
        # tokenbylogin 用 HTTPS(自签名),关闭证书校验
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE

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
