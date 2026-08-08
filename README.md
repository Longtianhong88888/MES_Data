# 快捷登录测试脚本

零安装:只依赖 Windows 自带的 PowerShell 5.1,不需要安装 Python 或任何软件,
也不会被安全软件当成可执行文件删除。

## 用法

1. 下载本仓库 ZIP(Code → Download ZIP)并解压到 Windows
2. 把 `config.example.json` 复制为 `config.json`,填入登录地址、账号和密码
   (不复制也可以,直接运行时会提示输入)
3. 双击 `login_windows.bat`

## 输出说明

- 脚本自动完成 ASP.NET 登录:GET `login.aspx` → 解析 `__VIEWSTATE`/`__EVENTVALIDATION`
  → POST 账号密码 → 打开 `index.aspx` 应用入口
- frame 中出现"登入已過期"跳转 = 会话无效;全部正常加载 = 登录成功
- 登录成功后扫描 top/left/home 三个 frame,列出菜单链接
- 逐个抓取 SN 追溯查询页(`sn_*.html`),报告查询表单的输入框和按钮结构,
  为下一步"输入模组 SN 查询全制程绑定信息"做准备
- 过程页面保存:`login_page.html`、`login_post_result.html`、`login_result.html`、
  `frame_1.html` / `frame_2.html` / `frame_3.html`
- 完整日志保存在 `login.log`

## 常见问题

- 输出 `LOGIN FAILED` → 检查 `config.json` 里的账号密码
- 登录成功但 frame 仍提示会话失效 → 站点可能升级了登录方式(如验证码),把
  `login_page.html` 发回分析

## 安全说明

- `config.json` 已被 `.gitignore` 忽略,真实密码不会进入仓库
- 如果 PowerShell 执行策略被禁,请在 cmd 中手动运行:

```cmd
powershell -NoProfile -ExecutionPolicy Bypass -File login_test.ps1
```
