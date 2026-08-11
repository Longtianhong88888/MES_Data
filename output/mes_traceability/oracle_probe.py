"""验证 C4 DataSource.xml 解密出的 Oracle 连接(不打印密码)。"""
import json
import sys

import oracledb

try:
    oracledb.init_oracle_client(
        lib_dir="/private/tmp/oracle_ic/ic_arm"
    )
except Exception as exc:
    print("thick init:", exc)


def main(conn_name: str, dsn_path: str):
    conns = json.load(open(dsn_path, encoding="utf-8"))
    c = conns.get(conn_name)
    if not c:
        print(f"未找到 {conn_name}")
        sys.exit(2)
    dsn = f"{c['host']}:{c['port']}/{c['service']}"
    print(f"连接 {conn_name}: {c['host']}:{c['port']}/{c['service']} user={c['user']}")
    try:
        with oracledb.connect(
            user=c["user"], password=c["password"], dsn=dsn,
            tcp_connect_timeout=15,
        ) as conn:
            cur = conn.cursor()
            cur.execute("select sysdate, banner from v$version where rownum=1")
            row = cur.fetchone()
            print("连接成功, DB 时间:", row[0], "| 版本:", row[1])
            # 查 T_DOWNIMGSET 站位映射表
            try:
                cur.execute("select count(*) from T_DOWNIMGSET")
                print("T_DOWNIMGSET 行数:", cur.fetchone()[0])
                cur.execute(
                    "select STATIONID, TABLENAME from T_DOWNIMGSET order by STATIONID"
                )
                rows = cur.fetchall()
                print("T_DOWNIMGSET 前 20 行:")
                for r in rows[:20]:
                    print("  ", r)
            except Exception as e:
                print("T_DOWNIMGSET 查询失败:", type(e).__name__, e)
            # 全库找 DOWNIMGSET / 图片表
            try:
                cur.execute(
                    "select owner, object_name, object_type from all_objects "
                    "where object_name like '%DOWNIMGSET%'"
                )
                print("DOWNIMGSET 对象:", cur.fetchall()[:10])
            except Exception as e:
                print("DOWNIMGSET 全库查询失败:", type(e).__name__, e)
            try:
                cur.execute(
                    "select STATIONID, TABLENAME from T_DOWNIMGSET "
                    "order by STATIONID"
                )
                rows = cur.fetchall()
                print("T_DOWNIMGSET 全部行数:", len(rows))
                for r in rows:
                    print("  ", r)
            except Exception as e:
                print("T_DOWNIMGSET 读取失败:", type(e).__name__, e)
            for pat in ["%APO006%PICTURE%", "%PICTUREDATA%", "%DOWNIMG%"]:
                try:
                    cur.execute(
                        "select owner, object_name from all_objects "
                        "where object_name like :1 and rownum <= 20",
                        [pat],
                    )
                    print(f"对象 {pat}:", cur.fetchall())
                except Exception as e:
                    print(f"对象 {pat} 查询失败:", type(e).__name__, e)
            # 当前用户可访问的表
            try:
                cur.execute(
                    "select table_name from user_tables where rownum <= 15"
                )
                print("当前用户前 15 表:", [r[0] for r in cur.fetchall()])
            except Exception as e:
                print("当前用户表查询失败:", type(e).__name__, e)
    except Exception as e:
        print("连接失败:", type(e).__name__, e)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "APO006CONN",
         sys.argv[2] if len(sys.argv) > 2
         else "/Users/user/Desktop/MES_Data/reference/lth/cimtool_conns_decrypted.json")
