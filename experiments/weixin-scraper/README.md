# 微信公众号文章爬虫

基于微信合集 (album) API 发现并抓取公众号文章，输出纯文本供 MaaS 事件提取管道使用。

## 依赖安装

```bash
pip install -r requirements.txt
playwright install msedge
```

## 快速开始

### 查看合集

```bash
# 列出该公众号的所有合集及其文章数量
python list_articles.py --list-albums "https://mp.weixin.qq.com/s/xxxx"

# 用多篇种子文章发现更多合集（不同文章可能属于不同合集）
python list_articles.py --list-albums \
    --seed-urls "https://mp.weixin.qq.com/s/yyyy" \
    "https://mp.weixin.qq.com/s/xxxx"

# 深度模式：递归采样已知合集文章，尝试发现更多合集
python list_articles.py --deep --list-albums "https://mp.weixin.qq.com/s/xxxx"
```

### 发现文章列表

```bash
# 列出所有合集文章（文本格式）
python list_articles.py "https://mp.weixin.qq.com/s/xxxx"

# JSON 格式输出
python list_articles.py --format json "https://mp.weixin.qq.com/s/xxxx"

# 只输出 URL 列表（方便管道串联）
python list_articles.py --max 20 --format urls "https://mp.weixin.qq.com/s/xxxx"

# 只抓取指定合集
python list_articles.py --album-ids 4180876154233864205 "https://mp.weixin.qq.com/s/xxxx"
```

### 抓取单篇文章

```bash
python fetch_weixin.py "https://mp.weixin.qq.com/s/xxxx"

# 自定义超时和输出目录
python fetch_weixin.py --timeout 45 --output-dir ./raw "https://mp.weixin.qq.com/s/xxxx"
```

### 批量抓取

```bash
python list_articles.py --max 10 --format urls "https://mp.weixin.qq.com/s/xxxx" | while read url; do
    python fetch_weixin.py "$url"
    sleep 5
done
```

输出文件默认保存到 `../agent_maas_cli/texts/`，可直接被 MaaS 事件提取管道消费。

## 工作原理

### 文章发现 (`list_articles.py`)

1. 从种子文章页面提取 `__biz` 和该文章所属的合集 ID
2. 通过 `mp/appmsgalbum?action=getalbum&f=json`（无需认证）遍历每个合集，分页获取全部文章
3. 去重、按时间倒序排列

**`--seed-urls`**：提供多篇来自不同合集的文章 URL，合并发现所有合集。

**`--deep`**：对已知合集，获取其文章 URL 并访问文章页面，检查是否有其他合集 ID，递归直到无新合集。

### 文章抓取 (`fetch_weixin.py`)

1. Playwright + MSEdge 渲染文章页面（规避微信反爬）
2. BeautifulSoup4 提取标题、作者、日期、正文
3. 输出纯文本文件

## 限制

微信是封闭生态，**没有公开的无认证 API 可以列出某公众号的全部文章或全部合集**。

- **合集 API**：只能发现种子文章所属的合集。不同合集之间没有交叉引用。
- **`--seed-urls`**：需要手动提供属于不同合集的文章 URL。多篇种子可以覆盖更多合集。
- **`--deep`**：如果合集之间有文章重叠，可以递归发现。但如果两个合集完全没有共同文章，则无法互相发现。
- **profile 页面**：被 TLS 级别认证拦截，无法从外部访问。
- **搜狗微信搜索**：2023 年后基本失效。
- **请求频率**：微信有 IP 级别的反爬限速。建议请求间隔 ≥ 5 秒。

## 技术栈

| 组件 | 用途 |
|------|------|
| **Playwright** | 浏览器自动化，规避微信反爬 |
| **BeautifulSoup4** | HTML 解析 |
| **MSEdge 浏览器** | Chromium 核心 |
| **Python 3.10+** | 运行环境 |

## 参考

- [Playwright 文档](https://playwright.dev/python/)
- [BeautifulSoup 文档](https://www.crummy.com/software/BeautifulSoup/bs4/doc/)
