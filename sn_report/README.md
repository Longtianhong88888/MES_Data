# SN 全制程追溯报告工具

输入一个或多个 SN(通常是 FACA 用的 Fail SN),一键查询每个 SN 的全部相关信息:

- SN 汇总(批号 / 线体 / 包号 / SFC / 测试结果)
- 站位轨迹(每站进站时间)
- **机台号 / 载板号 / 穴位号**(通过战情中心 C4 批量接口,需配置)
- 组件绑定(sensor / VCM / lens / flex / stiffener 等)
- **PR 图片**(MC IMG UpLoadInfo,签名 URL / 图片清单 / 可下载)
- ACF 测试数据(sensorID / flexid)

最后自动汇总成 PPT 报告。逻辑基于已跑通的 `login_test/login_test.ps1`,
解析方式升级为"表头驱动",页面结构变化时用 `--discover` 查看实际表头。

## 运行环境(Windows)

需要 Python 3.8+ 与依赖:

```bat
install_windows_requirements.bat   :: 项目根目录,安装 requests/bs4/lxml/openpyxl/python-pptx
```

VM 若不能联网安装,项目根 `lib\` 已经是**完整离线依赖**(Windows cp311):

- 原有:requests / beautifulsoup4 / lxml / certifi / idna / urllib3 / soupsieve / typing_extensions
- 2026-08-09 补齐:openpyxl / python-pptx / PIL(Pillow,含 7 个 .pyd)/
  xlsxwriter / et_xmlfile —— 从公司 BOI-T 工具 exe 提取
  (脚本:`reference/boi_commonality_unpacked/extract_offline_deps.py`)
- **2026-08-11 补齐:PyQt5(登录界面)** —— 项目根 `wheels/` 已内置全部 Windows
  离线安装包(requests/bs4/lxml/openpyxl/pptx/Pillow/XlsxWriter/PyQt5 等 18 个),
  内网电脑运行 `install_windows_requirements.bat` 即从本地 wheels 离线安装;
  SN_Report.exe 打包时 PyQt5 已随 exe 内置,无需任何安装

**前提:Windows 上的 Python 必须是 3.11 x64**(与 lib/ 里 cp311 的 .pyd 一致)。
把整个项目拷到 Windows(或至少 lib\ + sn_report\),双击运行即可,无需联网。

## 使用步骤

1. 准备 SN 列表,每行一个,保存为 `sn_report\sns.txt`(或 .csv / .xlsx 第一列,
   参考 `sn_report\sns.example.txt`):

   ```
   DNMHU30035Q00013G9+4162+Q
   DNMHU30035Q00013G9+4163+R
   ```

2. 确认项目根目录 `config.json` 中的账号与 `resource_url`(应用入口)。

3. (可选)配置 `sn_report/config.json`:
   - `analysis_window`:MC IMG / ACF 查询的时间范围
   - `img_stations`:要查图片的站位 ID 清单
   - `c4`:机台/载板/穴位的批量接口(填 token 后启用)

## 登录界面(可选)

运行 `--login`(或根目录 `config.json` 缺少账号密码时自动弹出)会打开 PyQt5 登录窗口,
可输入并保存:MES 地址 / 账号 / 密码 / C4 Token / 分析时间窗,并支持「登录测试」实际验证会话。

```bat
run_sn_report.bat --login
```

- 不勾选「记住密码」时,密码只保存在本次运行内存中,不写入磁盘;
- 登录界面依赖 PyQt5(打包 exe 时已内置;便携版 Python 需 `pip install PyQt5`);
- C4 Token 获取:`http://10.151.130.134:8086/#/tokenbylogin`(PowerBI/C4+ 账号 + 邮箱验证码)。

4. 运行:

   ```bat
   run_sn_report.bat --sns sns.txt
   ```

   或指定输出:

   ```bat
   run_sn_report.bat --sns sns.txt --out output\FACA_报告.pptx
   ```

## 常用参数

---

## Oracle 直连一键下载(新增,2026-08-11)

数据源不再依赖 MES 网页 / C4 GetInformationDT,直接连 Oracle:
配置库(wwsfcdb,读 `T_DOWNIMGSET` 36 站位→表映射、`T_FTPSETITEM` 图片服务器、
`T_SQLDATA` 229 条现成查询 SQL)+ 机种库(cma6db / APO006APDEV)按 SN 追溯
并下载全部站位照片。密码解密算法已从 `NewODCP.dll` 逆向(见
`lib/oracle_client.py::c4_decrypt`),286 个连接配置已解密到
`reference/lth/cimtool_conns_decrypted.json`。

### 首次部署(台式机,一次)

```bat
git clone git@github.com:Longtianhong88888/MES_Data.git
cd MES_Data\sn_report
python package_oracle_verify.py      :: 生成 package_oracle_verify\ 部署包
```

把 `package_oracle_verify\` 整个目录拷到内网台式机,双击 `run_verify.bat`:
自动解压 Instant Client(Windows x64 19.13)→ 离线安装 wheels(oracledb)→
读 `sns.txt` 逐 SN 查询下载 → 输出 `oracle_download\output\oracle_verify\<时间戳>\`
(verify.json + run.log)与 `downloads\`。

### 后续迭代(增量补丁,不再整包)

本机改完代码后:

```bat
python package_oracle_verify.py                 :: 同步部署包(可选,保证一致性)
python make_patch.py -m "修复xxx"              :: 对比基线,只生成变更文件
```

产物 `sn_report\patches\patch_<时间戳>\` 只含变更文件 + `apply_patch.bat`。
台式机:把该补丁目录拷到 `package_oracle_verify\` 下,双击 `apply_patch.bat`
即完成增量更新(已应用记录在 `.applied_patches.json`)。

### 验证闭环

1. 台式机跑完 → 拷回 `output\oracle_verify\` 与 `downloads\`;
2. 本机分析 verify.json(每 SN × 每站查询/下载明细、错误信息);
3. 改代码 → `make_patch.py` 生成补丁 → 台式机应用 → 继续测试。

| 参数 | 说明 |
|---|---|
| `--sns PATH` | SN 列表文件 |
| `--sn SN` | 单个 SN 快速查询 |
| `--out PATH` | PPT 输出路径 |
| `--discover` | 发现模式:把第一个 SN 的页面表格结构 dump 到 output\discover\,用于确认字段 |
| `--no-images` | 跳过 MC IMG 图片 |
| `--no-acf` | 跳过 ACF 测试数据 |
| `--c4` | 启用 C4 批量接口 |
| `--init-config` | 生成默认配置文件 |

## 输出

- `sn_report\output\SN全制程追溯报告.pptx`:最终报告
- `sn_report\output\raw\*.html`:每个查询的原始页面(排查用)
- `sn_report\output\sn_records.json`:结构化中间结果
- `sn_report\downloads\`:图片清单、ACF/MCIMG Excel 导出、图片文件

## 机台号 / 载板号 / 穴位号 的数据来源

当前 PS1 的 SN search 只返回站位轨迹与组件绑定,不含机台/载板/穴位。
本工具内置了一个 C4 批量接口客户端(参考公司 BOI-T 共性分析工具的实现):

- 接口:`POST http://10.151.128.35:8095/api/MachineParameter/GetInformationDT`
- 认证:Bearer JWT(C4+ / 战情中心 token)
- 在 `sn_report/config.json` 的 `c4.columns` 配置每个站位的
  `mc / carrier / pocket / start_time` 列名,工具会一次性批量拉取并合并到站位记录

若 C4 账号权限不可用,请用 `--discover` 查看 MES SN 页面实际表头,
把机台/载板/穴位所在的表头关键词补充到 `column_keywords`,解析层会自动识别。

## 一键下载所有站位照片(按每站 key 查询)

2026-08-11 新增:输入 Module SN 列表,自动完成「SN → 每站 carrier/pocket/lot」解析后,
按每站查询画像(见 `sn_report/config.json` 的 `img_stations_all`,共 47 站)查照片:

1. **ACF Test Data**:SN → sensorID / flexID;
2. **C4 GetInformationDT**(`c4.columns` 已内置 34 站列名):SN → 每站 carrier / pocket / lot / 机台 / 时间;
3. **MC IMG / TestData**:按每站 `search_type`(SN/Lotno/CarrierID/Time)+ `condition_from`
   组条件查询,并按 pocket(文件名 XY)过滤。

需要先在根 `config.json`(或登录界面)填入:
- `c4.token`:战情中心 Token(`http://10.151.130.134:8086/#/tokenbylogin`);
- `c4.plant_id` / `c4.device`:按工厂实际值填写(当前为空)。

首次在 VM 验证时重点确认:① GetInformationDT 返回列与 CSV 一致;② 各站 MC IMG 的
Station 参数是缩写(如 CA/HA)还是 bak 表名(如 `aaimguploadbak`),不符时改 `img_stations_all` 的 `id`。

## 注意事项

- 图片下载:VM 无法直连 `cma1.fs.com` 图片服务器时,工具只保存签名 URL 清单,
  由公司台式机用 `download_images.bat` 按清单下载;`report.download_images=true` 时会在可直连的机器上直接下载。
- 单 SN 失败不会中断批量;每个 SN 的告警会显示在 PPT 标题右侧。
- `--discover` 与首次 `--c4` 运行后,建议把确认的列名回填到配置,再正式批量。
