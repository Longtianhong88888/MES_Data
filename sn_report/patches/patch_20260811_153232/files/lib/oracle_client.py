"""Oracle 直连客户端:替代 GetInformationDT,从 C4 DataSource.xml 解密出连接并查询。

核心能力:
1. 解密 C4 的 ODCPDataSource.xml 密码(CustomDecrypt 算法已逆向);
2. 连接配置库(wwsfcdb / MESSETCONN)读取 T_DOWNIMGSET(站位→表映射)、
   T_FTPSETITEM(图片服务器)、T_SQLDATA(170+ 条现成查询 SQL);
3. 连接机种数据库(如 cma2db / APM006CONN)按 SN/Sensor/VCM/Carrier 查询图片记录。

依赖: oracledb(纯 Python 模式即可连 11g;老库需要 Instant Client thick 模式)。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

import oracledb


# ---------- C4 密码解密(逆向自 NewODCP.dll CustomDecrypt) ----------
def c4_decrypt(s: str) -> str:
    """DataSource.xml PassWord 解密算法。"""
    out = []
    for ch in s:
        c = ord(ch)
        if 54 < c <= 122:      # '7'..'z' -> -22
            c -= 22
        elif 32 < c <= 54:     # '!'..'6' -> +68
            c += 68
        out.append(chr(c))
    return "".join(out)


def parse_data_source_xml(xml_text: str) -> dict[str, dict[str, str]]:
    """解析 ODCPDataSource.xml,返回 {连接名: {host,port,service,user,password}}。"""
    conns: dict[str, dict[str, str]] = {}
    for m in re.finditer(
        r"<([A-Za-z0-9_]+CONN)>\s*<DataSource>(.*?)</DataSource>\s*"
        r"<PassWord>(.*?)</PassWord>\s*</\1>",
        xml_text, re.S,
    ):
        name, ds, pw = m.group(1), m.group(2).strip(), m.group(3).strip()
        host_m = re.search(r"HOST\s*=\s*([\d.]+)", ds)
        port_m = re.search(r"PORT\s*=\s*(\d+)", ds)
        svc_m = re.search(r"SERVICE_NAME\s*=\s*([^)]+)", ds)
        user_m = re.search(r"User ID=([^;]+)", ds)
        conns[name] = {
            "host": host_m.group(1) if host_m else "",
            "port": port_m.group(1) if port_m else "1521",
            "service": svc_m.group(1).strip() if svc_m else "",
            "user": user_m.group(1).strip() if user_m else "",
            "password": c4_decrypt(pw),
        }
    return conns


class C4Oracle:
    """C4 Oracle 直连封装。"""

    def __init__(self, conns: Optional[dict] = None, data_source_xml: Optional[str] = None,
                 init_client: Optional[str] = None):
        self.conns = conns or {}
        if data_source_xml and not self.conns:
            self.conns = parse_data_source_xml(data_source_xml)
        if not init_client:
            # PyInstaller 单文件 exe:Instant Client 已打入包内,运行时解压在 _MEIPASS
            if getattr(sys, "frozen", False):
                for candidate in (
                    Path(getattr(sys, "_MEIPASS", "")) / "instantclient",
                    Path(sys.executable).resolve().parent / "instantclient",
                ):
                    if (candidate / "oci.dll").exists():
                        init_client = str(candidate)
                        break
        if init_client:
            try:
                oracledb.init_oracle_client(lib_dir=init_client)
            except Exception:
                pass  # 纯 Python 模式或已初始化
        self._pools: dict[str, oracledb.Pool] = {}

    def get(self, conn_name: str) -> dict:
        c = self.conns.get(conn_name)
        if not c:
            raise KeyError(f"连接 {conn_name} 不存在")
        return c

    @property
    def dsn(self) -> str:
        c = self.get(self.conn_name)
        return f"{c['host']}:{c['port']}/{c['service']}"

    def connect(self, conn_name: str):
        c = self.get(conn_name)
        return oracledb.connect(
            user=c["user"], password=c["password"],
            dsn=f"{c['host']}:{c['port']}/{c['service']}",
            tcp_connect_timeout=15,
        )

    def query(self, conn_name: str, sql: str, params: Optional[list] = None) -> list[tuple]:
        with self.connect(conn_name) as conn:
            cur = conn.cursor()
            cur.execute(sql, params or [])
            return cur.fetchall()

    # ---------- 配置库查询 ----------
    def load_station_tables(self, cfg_conn: str = "MESSETCONN") -> list[dict]:
        """T_DOWNIMGSET: 站位 → 表名/字段映射。"""
        rows = self.query(
            cfg_conn,
            "select STATIONID, FILETYPE, TABLENAME, MACHINE from T_DOWNIMGSET order by STATIONID",
        )
        return [
            {"station": r[0], "filetype": r[1], "table": r[2].strip(), "columns": r[3]}
            for r in rows
        ]

    def load_ftp_settings(self, cfg_conn: str = "MESSETCONN") -> list[dict]:
        """T_FTPSETITEM: 站位/FTP/代理/表名配置。"""
        rows = self.query(
            cfg_conn,
            "select STATIONID, FILETYPE, FTPIP, FTPPATH, PROXYADDRESS, LOCALPATH, "
            "TABLENAME, LOADMODE from T_FTPSETITEM",
        )
        return [
            {"station": r[0], "filetype": r[1], "ftp": r[2], "ftppath": r[3],
             "proxy": r[4], "local": r[5], "table": r[6], "mode": r[7]}
            for r in rows
        ]

    def load_sql_data(self, cfg_conn: str = "MESSETCONN") -> list[dict]:
        """T_SQLDATA: C4 全部查询 SQL。"""
        rows = self.query(
            cfg_conn,
            "select SQLEXPLAIN, SQLIST, ATT1, ATT2, OPENFLAG from T_SQLDATA order by ATT1",
        )
        out = []
        for r in rows:
            sql = r[1]
            if hasattr(sql, "read"):
                sql = sql.read()
            out.append({"name": r[0], "sql": sql, "seq": r[2], "key_type": r[3],
                        "open": r[4]})
        return out

    # ---------- 追溯查询 ----------
    def trace_sn(self, data_conn: str, sn: str) -> dict:
        """SN → {lotno, sensorid, vcmid, var_sn, carrierkey, carrierid, carrierxy}。"""
        out = {"sn": sn}
        checks = [
            ("lotno", "select lotno, sn from EQLASERMARKINGBAK where sn=:1", [sn]),
            ("sensorid", "select sn, senserid from SNBINDSENSERIDBAK where sn=:1", [sn]),
            (
                "vcmid",
                "select a.vcmid, a.sn from TESTFOLAAIMAGEBAK a "
                "inner join TESTSNCURRENTBAK c on a.sn=c.att2 where c.sn=:1",
                [sn],
            ),
            (
                "carrier",
                "select sn, carrierkey, carrierid, carrier_col, carrier_row "
                "from FOLSENSERIDINFOBAK where sn in "
                "(select att2 from TESTSNCURRENTBAK where sn=:1)",
                [sn],
            ),
        ]
        for key, sql, params in checks:
            try:
                rows = self.query(data_conn, sql, params)
                if rows:
                    out[key] = rows
            except Exception:
                pass
        return out

    def query_images(self, data_conn: str, table: str, sn: str, limit: int = 50) -> list[dict]:
        """按 SN 查图片表(通用 18 列结构)。"""
        sql = (
            f"select FILETYPE, LOTNO, SN, CARRIERID, CARRIERXY, FILENUMBER, FILETIME, "
            f"FILESIZE, LOCALPATH, FTPPATH, FTPIP, UPLOADTIME, MACHINENO, FILENAME, "
            f"CARRIERX, CARRIERY, RESULT, CARRIERKEY from {table} "
            f"where sn=:1 and rownum<=:2"
        )
        rows = self.query(data_conn, sql, [sn, limit])
        cols = ["filetype", "lotno", "sn", "carrierid", "carrierxy", "filenumber",
                "filetime", "filesize", "localpath", "ftppath", "ftpip", "uploadtime",
                "machineno", "filename", "carrierx", "carriery", "result", "carrierkey"]
        return [dict(zip(cols, r)) for r in rows]


def load_conns_from_decrypted_json(path: str) -> dict:
    """加载已解密的连接 JSON(由 parse_data_source_xml 生成)。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    import sys

    # 用法: python oracle_client.py <数据连接名> <SN>
    client = C4Oracle(
        conns=load_conns_from_decrypted_json(
            "/Users/user/Desktop/MES_Data/reference/lth/cimtool_conns_decrypted.json"),
        init_client="/private/tmp/oracle_ic/ic_arm",
    )
    if len(sys.argv) > 2:
        data_conn, sn = sys.argv[1], sys.argv[2]
    else:
        data_conn, sn = "APM006CONN", "MR0D2130A1EU11337326117000"
    print("== 追溯 ==")
    trace = client.trace_sn(data_conn, sn)
    for k, v in trace.items():
        print(f"  {k}: {v}")
    print("== SF 图片 ==")
    for r in client.query_images(data_conn, "T_SFPICTUREUPLOAD", sn, 5):
        print("  ", r["filename"], "|", (r["ftppath"] or r["localpath"])[:100])
