# C4+ / IIOT 查询入口逆向发现(2026-08-11)

来源:`reference/lth/C4+20201024/C4+20201024/`(.NET WinForms 程序包,1.0GB)

## 结论

C4 桌面工具 = `C4+Upload.exe`(主程序)+ `MIS/CimTool/CimTool.exe`(**IIOT 查询入口**,
即导出 BOI-T/CHS-T 追溯 CSV 的 DownSerinData 窗口所在程序)。登录后可按 SN/Lot/时间
下载 Serin(全制程追溯)数据与图片。

## IIOT 鉴权

- Token 页面:`http://10.151.130.134:8086/#/tokenbylogin`(WebView2 打开,用户登录拿 JWT)
- 验证:`GET http://10.151.128.181:8081/api/BelieveAuthPoint/VerifySignatureAndCode?signedDataString=<JWT>`
  - 实测:返回 `Invalid signature`(JWT 未被该端点接受,需确认 signedDataString 构造或换新 token)
- 授权:`GET http://10.151.128.181:8081/api/BelieveAuthPoint/AuthorizeEndpoint?syscode=S20230111001&signcode=IDLSystem&password=...`
  - 实测:500,后端转调 `https://authserver.efoxconn.com/api/User/InterUserLogin`(Foxconn SSO)
- MES 门户账号登录:`http://10.151.128.35:8091/MESPortalAPI/Reqdatabaseinfo`(CPMolde.Userid/Password)

## 数据来源(逆向自 CimTool/SFConline/MES.exe 字符串)

### 1) Web API(战情中心)

- `POST http://10.151.128.35:8095/api/MachineParameter/GetInformationDT`
  - 鉴权:Bearer JWT(已验证 token 有效、Device=BOI-T、plantID=8S01 通过)
  - 关键:`ColumnSelect=[列ID]` 需要**列 ID**(不是列名),列 ID 映射在 BOI-T 的 info.xlsx
  - JSON body 不绑定(控制器 NRE),走查询串/表单

### 2) 直连 Oracle(CimTool/SFConline 方式)

- 连接串:`DataSource.xml`(10.151.128.32-34 cmbudb / 10.142.136.201-206 wwsfc,DEV 账号)
- 核心表:
  - `T_DOWNIMGSET`:`SELECT STATIONID,TABLENAME FROM T_DOWNIMGSET ORDER BY STATIONID`
    (站位 ↔ 数据表名映射,下载站位清单的来源)
  - `DATACENTERDEV.T_<机种>_EOLPICTUREDATA` / `T_<机种>_FOLPICTUREDATA`
    (Serin 图片数据,SQL 里有 `SET STATEMENT_MEM='1GB'`)
  - `eqlasermarkingbak`:`select lotno,att6 from eqlasermarkingbak where sn=:sn`(LM)
  - `testfolaaimagebak` / `folsenserr...`(AA 图片)
  - `T_<机种>_LOTDATA_SMT`、`T_<机种>_EOLDATA`(Lot 与缺陷)
- 图片文件服务器(多处):`http://cma1.fs.com:8081/`、`http://10.142.119.201:8081/`、
  `http://10.142.119.202:8081/`、`http://10.142.118.200:8081/`、`http://10.142.117.100:8081/` 等;
  数据库里存 `s3path / filename / att6`,另有 AWSSDK.S3(图片可能同步 S3)

### 3) 其他 API

- `http://10.142.119.228:8083/api/ParaSet/ParaSet`(参数设置)
- `http://10.142.117.206:8088/api/BusReqDatas/SendDataByReqCode`(数据回传)
- `http://10.151.128.225:8091/ReportPortal/GetReportDataSet`(ReportPortal 数据集)
- `http://10.151.128.247:8085/Personnel/GetUserInfoByWorkNo?workno=`(工号校验)

## 完成自动化的三条路

1. **info.xlsx**(BOI-T 列 ID 映射)→ 直接用 GetInformationDT(最干净,只需 token);
2. **抓包 CimTool 一次**(Fiddler/Wireshark)→ 拿到 DownSerinData 实际请求的
   API/参数/SQL,照抄;
3. **反编译 CimTool.exe**(需要 .NET 反编译器,如 ILSpy)→ 读 Get_Serin_data 完整实现。

---

## 2026-08-11 重大突破:Oracle 直连已打通(路线 3 完成)

### 1) C4 密码解密算法(逆向自 NewODCP.dll `CustomDecrypt`)

- 算法:逐字符映射
  - ASCII `'7'..'z'`(55-122)→ 减 22
  - ASCII `'!'..'6'`(33-54)→ 加 68
  - 其余不变
- 示例:`\+4y+**OO` → `Foxconn99`;`*JGDw,Dz!2(+,!.` → `n41.ap.devloper`
- 实现:`sn_report/lib/oracle_client.py::c4_decrypt`

### 2) 已解密的连接(见 `reference/lth/cimtool_conns_decrypted.json`,286 个)

关键可用连接:
- `MESSETCONN`:`10.151.128.211:1521/wwsfcdb` MESSETAPDEV —— **配置库,可读 T_DOWNIMGSET/T_FTPSETITEM/T_SQLDATA**
- `CIMCONN`:`10.151.128.211:1521/wwsfcdb` CIMAPDEV —— 可连
- `APM006CONN`:`10.151.129.163:1521/cma2db` APM006APDEV —— **机种数据库,5087 同义词→APM006DEV**
- `APM001/002/003/005/007`、`ANO/ANM/ANN/APO008` 等同类账号均可连对应 cma2/3/4db
- `APO006CONN`:`10.142.116.140:1521/cma6db` —— **APO006 专属库,当前 Mac 不可达(10.142.116.x 网段不通),需内网机器**
- 老库为 Oracle 11.2,需 Instant Client thick 模式(arm64 已放 `/private/tmp/oracle_ic/ic_arm`)

### 3) 核心表结构(全部实测)

- `T_DOWNIMGSET`(36 站):STATIONID/FILETYPE/TABLENAME/MACHINE(字段映射)
  - 已导出:`output/mes_traceability/downimgset_full.json`
- `T_FTPSETITEM`(6322 行):FTPIP/PROXYADDRESS/LOCALPATH/LOADMODE
  - 已导出:`output/mes_traceability/ftpsetitem_full.json`
- `T_SQLDATA`(229 条,启用 170):**C4 查询 SQL 全集**
  - 已导出:`output/mes_traceability/sql_data_full.json`
- 图片表通用 18 列:FILE-TYPE/LOTNO/SN/CARRIERID/CARRIERXY/FILENUMBER/FILETIME/FILESIZE/
  LOCALPATH/FTPPATH/FTPIP/UPLOADTIME/MACHINENO/FILENAME/CARRIERX/CARRIERY/RESULT/CARRIERKEY
- 追溯链:`EQLASERMARKINGBAK`(SN→Lot)、`SNBINDSENSERIDBAK`(SN→SenserID)、
  `TESTFOLAAIMAGEBAK`(SenserID→VCMID/VAR_SN)、`FOLSENSERIDINFOBAK`(SenserID→CarrierKey/XY)

### 4) 端到端验证结果(APM006 库,真实数据)

- SN `MR0D2130A1EU11337326117000` → `T_SFPICTUREUPLOAD` 查到 5 张 SF 图片
- `FTPPATH` 为带 AWS 签名的 S3 URL(`http://cma1.fs.com:8081/cmaeolsf/...`),内网可直接下载
- 图片网关 `10.142.117.100:8081`(cma1)、`10.142.118.200:8081`(cma2)端口 OPEN

### 5) 待办

- APO006 库 cma6db 需在内网机器连接(或用 APO006 同款机种库验证后直接切换连接名)
- 图片下载:`FTPPATH` 域名(cma1.fs.com)需内网 DNS;签名 URL 已含 AWSAccessKeyId/Expires/Signature
