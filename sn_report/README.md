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

4. 运行:

   ```bat
   run_sn_report.bat --sns sns.txt
   ```

   或指定输出:

   ```bat
   run_sn_report.bat --sns sns.txt --out output\FACA_报告.pptx
   ```

## 常用参数

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

## 注意事项

- 图片下载:VM 无法直连 `cma1.fs.com` 图片服务器时,工具只保存签名 URL 清单,
  由公司台式机用 `download_images.bat` 按清单下载;`report.download_images=true` 时会在可直连的机器上直接下载。
- 单 SN 失败不会中断批量;每个 SN 的告警会显示在 PPT 标题右侧。
- `--discover` 与首次 `--c4` 运行后,建议把确认的列名回填到配置,再正式批量。
