# 项目记忆:ATW CMBU C3 模组 SN 全制程追溯

最后更新:2026-08-09

## 目标

输入一个模组 SN,查询整个制程(前端 + 后端)中与该 SN 绑定的全部信息:
站位轨迹、组件绑定(sensor/VCM/lens)、ACF 测试数据(sensorID/flexid)、各站位图片。

制程分界:前端(FOL,Clean Room 0.1K)在 Laser Marking 之前,**没有模组 SN**,
数据靠 sensor ID / VCM ID / lens ID 关联;后端(EOL,Clean Room 10K)用模组 SN。

## 环境与约束

- Windows 平行桌面 VM:不能下载/安装软件;不能直连图片文件服务器
  (`cma1.fs.com` / `10.142.119.202:8081`)
- 公司台式机:可直连图片服务器;文件经**公司网盘**中转
- MES 站点:`10.151.128.45:8081`;报表门户:ReportPortal `10.151.130.120:8091`
  (实际节点 `10.151.130.225/226:8091`,TEMP 导出可直连)
- PowerShell 5.1 解析含中文的 .ps1 **必须带 UTF-8 BOM**;bat 必须 CRLF

## 工具链(仓库 Longtianhong88888/MES_Data,login_test 目录)

| 文件 | 作用 |
|---|---|
| `login_test.ps1` | 主脚本:登录 + SN 追溯 + ACF sensorID + MC IMG 图片清单/Excel |
| `pack_lists.bat` | 打包图片链接清单为 `image_lists.zip`(网盘传输) |
| `download_images.ps1` / `.bat` | 公司台式机按清单批量下载图片(无需登录) |

## login_test.ps1 步骤与状态

1. ASP.NET 登录:`GET login.aspx` → 解析 `__VIEWSTATE/__EVENTVALIDATION` →
   POST `Login1$useridtb` / `Login1$userpwdtb` / `Login1$LoginImageButton` ✅
2. 打开 `index.aspx?project=19&custom=LH_Apple_APP003&num=KH297` 应用入口 ✅
3. 验证会话(抓 top/left/home frames,检查"登入已過期"注入)✅
4. 菜单链接扫描 ✅
5. SN search(`report/snsearch.aspx`,字段 `sntextbox`,触发 `Button1`):
   返回 SN 汇总 + 站位轨迹 + 组件绑定 + 耗材,生成 `sn_trace_report.txt` ✅
6. Test data 页(`VTQReport/VTQTestDataDownLoad.aspx`,字段 `barcodetxt`,
   searchbutton)按 SN 查询 **404,未解决**(该页可能只支持日期/批号/SensorID 模式)
7. ReportPortal 打开 ACF Test Data / MC IMG UpLoadInfo
   (POST `p=APP003&p=ODSAPP003CONN&p=8S01&userID=G1655895`)✅
8. **ACF Test Data** 三种机型查询(上料機/下料機/主機):
   自动提取 **sensorID / flexid**,下载 Excel + 图片清单 ✅
9. **MC IMG UpLoadInfo** 按站位查询:
   SearchType=SN + Condition=SN 有效;生成图片元数据 + Excel + 图片清单 ✅

## 已验证的关键数据(测试 SN:DNMHU30035Q00013G9+4162+Q)

- 批号 `K6233A004-09`,包号 `PK6233A004-09`,线体 `EOL Line7202`,SFC `MBO/PBO`
- 站位轨迹约 32 个:OIS PNP → Cube Assembly → VCM Sealing → Z-cal test →
  Active alignment(AA)→ FVI → FOL PACK → **Laser marking(SN 诞生)** →
  MFG 测试 → EOL FVI → ACF → Top/Bottom FR → FVI_3 → Chassis attach
- **sensorID = `5ACB50170392`**(ACF下料機 数据)
- **flexid = `FNJHTCM09SD00014VP`**
- ACF film lotno `44610535YE-6E0111A018`,机台 `ACF7217`
- ACF 图片:上料機 2 张(AOI/PPR)、下料機 1 张、主機 4 张
  (CubeInspect/AcfInspect/PanelPic/CompoPic),链接清单已保存
- MC IMG:该 SN 仅 **ACFFlip** 站位有 1 张 PPR 图(机台 `ECF7201N`);
  AA/LM/AVI/FRTOP 无记录

## 门户查询机制要点(踩过的坑)

- 查询 = multipart/form-data POST `/ReportPortal/Search`;页面字段值要
  **HTML 解码**(`&quot;` → `"`),如 `OtherValue`
- GetList(`/ReportPortal/GetList`,body `Jsonstr=<JSON>`)枚举下拉选项;
  `SendParameter.Value` 空值必须用 `null` 不能用 `""`;SearchType 参数要传
  数组 `["选中ID"]`;目前返回 `Resultvalue:[]`,选项枚举未成功(但 SN 查询已可用)
- 结果页是 EasyUI datagrid,数据在 `<p>` 标签;图片直链是签名 URL
  (`AWSAccessKeyId/Expires/Signature`,有效期约一年)
- Excel 导出链接在结果页 `href="...TEMP\...xlsx"`(反斜杠需转 `/`)

## 当前进度/阻塞

- **已完成**:登录、SN search 站位轨迹+组件绑定、ACF sensorID/flexid、
  MC IMG 各站位图片清单与 Excel 元数据
- **阻塞**:图片文件下载——VM 无法直连图片服务器,需按"V 形分工":
  VM 生成清单 → `pack_lists.bat` 打包 → 公司网盘 → 公司台式机
  `download_images.bat` 批量下载
- 待验证:公司台式机端实际下载效果

## 维护注意

- `login_test.ps1` 每次修改后用 apply_patch 会**丢失 BOM**,
  必须重新加 `EF BB BF`(用 `xxd -l 4` 验证)再推送
- bat 文件保持 CRLF
- 运行输出与结果文件保存在脚本同目录 `downloads\`(VM 本地副本 C:\MES_Data-main)

## 下一步(恢复点)

1. 验证公司台式机用 `download_images.bat` 能下到全部图片
2. 可选增强:90+ 站位全扫(自动收集该 SN 所有站位图片清单)、日期参数化、
   生成最终合并追溯报告(站位轨迹 + 组件绑定 + 测试数据 + 图片清单)
3. 排查 Step 8 的 404(Test data 按 SN 查询)
