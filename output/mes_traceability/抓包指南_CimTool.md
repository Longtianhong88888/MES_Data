# 抓包指南:CimTool(C4 IIOT)查询接口

目的:抓一次 CimTool 从「登录 → DownSerinData 查询 → 下载图片」的真实请求,
拿到它实际调用的 HTTP 接口 / Oracle SQL / 参数,之后我们用 Python 原样复刻。

## 准备工作(内网机器不能联网 → 先在有网机器下载便携版,再拷入)

1. **Wireshark 便携版**(必抓,HTTP + Oracle SQL 都能看到):
   - 下载:`https://www.wireshark.org/download.html` → Windows x64 PortableApps 版(免安装)
   - 或任何一台机器装好 Wireshark,把整个安装目录拷过去
2. **(可选)Fiddler Classic**(HTTP 最清晰):
   - `https://www.telerik.com/download/fiddler`(免费,安装后可直接拷目录)
   - 主要用于 HTTP 明文 + 导出 .har;Oracle SQL 它看不到,所以 Wireshark 为主

## 抓包步骤(Wireshark)

1. 双击 `WiresharkPortable.exe` 启动;
2. 选择网卡(通常是"以太网"或"WLAN"),双击开始捕获;
3. 设置显示过滤器(可选,减少噪音):
   ```
   host 10.151.0.0/8 or host 10.142.0.0/8
   ```
4. 打开 `MIS\CimTool\CimTool.exe`,完整操作一遍,每个动作只做一次:
   - 打开"获取Token"(tokenbylogin 页面)→ 登录 → 复制/粘贴 Token → 点"确认Token";
   - 进入 **DownSerinData**:选机种(如 APO006)、选站位(勾若干站)、ID 类选 SN、
     导入一个 SN 清单(1~3 个即可)、设定开始/结束时间 → 点查询/下载;
   - 如有"下载图片/共性图片"按钮,也点一次;
5. 停止捕获(Wireshark 红色方块)→ File → Save As → 保存为 `cimtool_capture.pcapng`;
6. 把 pcapng 放到 `reference\lth\` 或直接发我。

## 关键:抓到后我先看什么

- **HTTP**(Follow TCP Stream / HTTP 过滤器):
  - `VerifySignatureAndCode` 的完整 URL 和 `signedDataString` 到底是什么格式(这是你现在 token 验证失败的关键);
  - DownSerinData 查询实际请求的接口:URL、方法、Headers、Body(SN 列表、机种、站位、时间窗);
  - 图片下载的 URL 结构。
- **Oracle TNS**(tcp 1521):Wireshark 会自动解 TNS,能看到
  `SELECT ... FROM T_<机种>_EOLPICTUREDATA ...` 等 SQL 全文和绑定参数。

## 备用:如果 Fiddler/代理看不到 HTTP

有的 .NET 程序不走系统代理。两种办法:
- 用 **Proxifier** 强制 CimTool 走 Fiddler(127.0.0.1:8888);
- 或者直接以 Wireshark 抓包为准(TCP 流里 HTTP 明文一样能看到)。

## 抓完发我之后

我从 pcapng/.har 里提取:
1. IIOT 鉴权真实格式(修好 token 验证);
2. 数据查询接口与参数 → 写进 `sn_report/lib/c4_client.py`(或新增 `iiot_client.py`);
3. Oracle 表结构 → 直接替换 `trace_key_resolver` 的数据源(不再依赖 GetInformationDT 列 ID)。
