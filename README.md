# 快捷登录测试脚本

零安装:只依赖 Windows 自带的 PowerShell 5.1,不需要安装 Python 或任何软件,
也不会被安全软件当成可执行文件删除。

## 用法

1. 下载本仓库 ZIP(Code → Download ZIP)并解压到 Windows
2. 把 `config.example.json` 复制为 `config.json`,填入登录地址、账号和密码
   (不复制也可以,直接运行时会提示输入)
3. 双击 `login_windows.bat`

## 输出说明

- 页面返回主系统 frameset(`<frameset>`)→ 自动登录成功,脚本还会用同一会话
  抓取 top/left/home 三个 frame 页面验证登录态
- 页面仍包含密码输入框(`type="password"`)→ 登录失败,或需要验证码/额外认证
- 登录后返回的页面会保存为 `login_result.html`,可以用浏览器打开检查
- 验证用的 frame 页面保存为 `frame_1.html` / `frame_2.html` / `frame_3.html`
- 完整日志保存在 `login.log`

## 安全说明

- `config.json` 已被 `.gitignore` 忽略,真实密码不会进入仓库
- 如果 PowerShell 执行策略被禁,请在 cmd 中手动运行:

```cmd
powershell -NoProfile -ExecutionPolicy Bypass -File login_test.ps1
```
