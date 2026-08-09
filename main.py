import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

# 方案B: 优先使用项目内 lib/ 目录中的离线依赖(Windows 免安装,无需 pip)
_LIB_DIR = BASE_DIR / "lib"
if sys.platform.startswith("win") and (_LIB_DIR / "requests").is_dir():
    sys.path.insert(0, str(_LIB_DIR))

import requests
from bs4 import BeautifulSoup


def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"请先复制 config.example.json 为 config.json 并填写配置：{CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    )
    return session


def login(session: requests.Session, config: Dict[str, Any]) -> None:
    login_url = config["login_url"]
    username = config["username"]
    password = config["password"]
    form = config.get("login_form", {})

    data = {
        form.get("username_field", "username"): username,
        form.get("password_field", "password"): password,
    }
    data.update(form.get("extra_fields", {}))

    response = session.post(login_url, data=data, timeout=30)
    response.raise_for_status()

    if response.url == login_url:
        print("警告：登录后仍然停留在登录页面，可能登录失败或需要额外认证。")
    else:
        print(f"已登录：{response.url}")


def fetch_page(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def parse_resource_links(html: str, selector: str = "a") -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    return [tag.get("href") for tag in soup.select(selector) if tag.get("href")]


def download_file(session: requests.Session, file_url: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = file_url.split("?")[0].rstrip("/").split("/")[-1] or "downloaded"
    target_path = dest_dir / filename

    with session.get(file_url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with open(target_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

    return target_path


def main() -> None:
    config = load_config()
    session = create_session()

    login(session, config)

    resource_url = config.get("resource_url")
    html = fetch_page(session, resource_url)

    print("资源页面已获取，长度：", len(html))

    # 解析页面中的链接，按需修改选择器
    links = parse_resource_links(html, selector="a")
    print(f"检测到链接数量：{len(links)}")

    download_dir = BASE_DIR / config.get("download_dir", "downloads")
    for link in links[:10]:
        if link.startswith("http"):
            print(f"开始下载：{link}")
            path = download_file(session, link, download_dir)
            print(f"已保存：{path}")
        else:
            print(f"忽略相对链接：{link}")


if __name__ == "__main__":
    main()
