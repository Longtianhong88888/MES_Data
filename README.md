# 内部网站资源抓取程序

这是一个 Python 项目模板，用于从公司内部网站登录并获取资源。

## 依赖

- Python 3.11+
- requests
- beautifulsoup4
- lxml

## 安装

```bash
python -m pip install -r requirements.txt
```

## 使用方法

1. 复制 `config.example.json` 为 `config.json`
2. 填写 `login_url`、`username`、`password` 和目标资源 URL
3. 运行：

```bash
python main.py
```

## Windows 直接运行

如果你希望 Mac 上开发好的代码直接切换到 Windows 运行，可以直接把本项目文件夹复制到 Windows：

- 通过 Parallels 共享文件夹
- 或通过局域网 SMB
- 或通过移动硬盘/U 盘

项目内已内置 `lib/` 目录，包含全部依赖的离线拷贝（requests、beautifulsoup4、lxml 及其传递依赖），
Windows 端**无需联网、无需安装任何软件**，进入项目目录后直接运行：

```cmd
run_windows.bat
```

`run_windows.bat` 会自动找到项目内 `python\python.exe`（嵌入式 Python 3.11）并运行 `main.py`。

说明：

- 依赖存放在 `lib/` 中，由 `main.py` 启动时自动加入 `sys.path`，不需要 pip 安装
- 如需在**有外网**的机器上重新生成或升级依赖，可在 Mac 上执行：
  `python3 -m pip download -r requirements.txt --platform win_amd64 --python-version 3.11 --only-binary=:all: -d wheels`
  然后把 `wheels/` 拷到 Windows，运行 `install_windows_requirements.bat`（离线安装到嵌入式 Python）
- 如果你已经有可携带的 Python 运行环境（例如你之前 `auto_report` 项目打包出的可移植环境），请把它放到本项目目录中

## 说明

- `main.py` 提供了登录、页面抓取、HTML 链接解析和文件下载的基础代码结构
- 由于你公司的内部网站只能从 Windows 平行桌面访问，建议在 Windows 远程桌面环境中运行这个脚本
- 如果登录流程包含验证码、单点登录或浏览器动态提交，则可能需要使用浏览器自动化（例如 `selenium`）
- 请勿将真实账号密码提交到版本控制
