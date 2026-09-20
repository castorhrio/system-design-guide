#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_site.py — 把 Markdown 笔记编译成一个纯静态阅读站。

用法：
    python tools/build_site.py
    SDG_OUT=/tmp/site python tools/build_site.py

环境变量：
    SDG_SRC     源仓库根目录（默认：本脚本所在目录的上一级）
    SDG_OUT     输出目录（默认：<仓库同级>/.site）
    SDG_ASSETS  存放 style.css / app.js 的目录（默认：本脚本所在目录）
    SDG_BASE    部署路径前缀，仅用于 404 页（默认：/system-design-guide）

设计要点：
  * 站内所有链接都用**相对路径**，因此无论是 GitHub Pages 的子路径部署，
    还是本地 `python -m http.server` 预览，都能正常工作，换域名也不用改。
  * 图片按字节原样复制，blob 哈希与主仓库一致，推送到 gh-pages 时无需重传。
  * 产物是纯静态 HTML，写 .nojekyll 跳过 Jekyll。
"""

import html as html_mod
import json
import os
import posixpath
import re
import shutil
import sys
import urllib.parse

from markdown_it import MarkdownIt

# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SRC = os.environ.get("SDG_SRC") or ROOT
OUT = os.environ.get("SDG_OUT") or os.path.join(ROOT, ".site")
ASSETS = os.environ.get("SDG_ASSETS") or HERE
BASE = (os.environ.get("SDG_BASE") or "/system-design-guide").rstrip("/")

SITE_TITLE = "系统设计中文精讲"
SITE_DESC = "面向初级开发者的系统设计教程：28 章中文精讲、127 条勘误、182 条补充。"
REPO_URL = "https://github.com/castorhrio/system-design-guide"
SOURCE_URL = "https://github.com/liquidslr/system-design-notes"

SHORT_TITLES = {
    1: "从零到百万用户", 2: "粗略估算", 3: "系统设计框架", 4: "限流器",
    5: "一致性哈希", 6: "键值存储", 7: "分布式唯一 ID", 8: "URL 短链",
    9: "网络爬虫", 10: "通知系统", 11: "信息流系统", 12: "聊天系统",
    13: "搜索自动补全", 14: "YouTube", 15: "Google Drive", 16: "附近服务",
    17: "附近的朋友", 18: "Google Maps", 19: "分布式消息队列",
    20: "监控告警系统", 21: "广告点击聚合", 22: "酒店预订系统",
    23: "分布式邮件服务", 24: "类 S3 对象存储", 25: "实时游戏排行榜",
    26: "支付系统", 27: "数字钱包", 28: "股票交易所",
}

PARTS = [
    ("第一部分", "基础功", "第 1–3 章", [1, 2, 3]),
    ("第二部分", "核心组件", "第 4–7 章", [4, 5, 6, 7]),
    ("第三部分", "经典题型", "第 8–15 章", list(range(8, 16))),
    ("第四部分", "大型系统", "第 16–28 章", list(range(16, 29))),
]

GUIDE_FILES = [
    ("00-学习指南/README.md", "guide/", "学习指南"),
    ("00-学习指南/前置知识清单.md", "guide/prerequisites.html", "前置知识清单"),
    ("00-学习指南/学习路线图.md", "guide/roadmap.html", "学习路线图"),
]

APPENDIX_FILES = [
    ("99-附录/术语表.md", "appendix/glossary.html", "术语表"),
    ("99-附录/勘误与补充汇总.md", "appendix/errata.html", "勘误与补充汇总"),
    ("99-附录/高频面试题速查.md", "appendix/interview.html", "高频面试题速查"),
]

# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------

MD = MarkdownIt("gfm-like", {"html": True, "linkify": True, "typographer": False})


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def url_to_file(url):
    """站点相对 URL -> 输出文件路径（posix）"""
    if url == "" or url.endswith("/"):
        return (url + "index.html").lstrip("/")
    return url


def page_prefix(file_path):
    """页面所在目录到站点根的前缀，例如 ch/01/index.html -> ../../"""
    d = posixpath.dirname(file_path)
    if not d:
        return ""
    return "../" * len(d.split("/"))


def rel_link(cur_file, target_url):
    """从当前页面到目标 URL 的相对链接"""
    cur_dir = posixpath.dirname(cur_file)
    if target_url == "" or target_url.endswith("/"):
        rel = posixpath.relpath(target_url.rstrip("/") or ".", cur_dir or ".")
        return "./" if rel == "." else rel + "/"
    return posixpath.relpath(target_url, cur_dir or ".")


def make_slug(text):
    s = text.strip().lower()
    s = re.sub(r"[^\w\u4e00-\u9fff\- ]+", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s or "section"


H_RE = re.compile(r"<h([1-6])>(.*?)</h\1>", re.S)


def add_heading_ids(body):
    toc = []
    used = {}

    def repl(m):
        lvl, inner = int(m.group(1)), m.group(2)
        text = html_mod.unescape(re.sub(r"<[^>]+>", "", inner)).strip()
        slug = make_slug(text)
        if slug in used:
            used[slug] += 1
            slug = "%s-%d" % (slug, used[slug])
        else:
            used[slug] = 0
        if lvl in (2, 3) and text:
            toc.append((lvl, slug, text))
        return '<h%d id="%s">%s</h%d>' % (lvl, slug, inner, lvl)

    return H_RE.sub(repl, body), toc


# --------------------------------------------------------------------------
# 页面清单
# --------------------------------------------------------------------------

def discover_chapters():
    out = []
    for name in sorted(os.listdir(SRC)):
        if not os.path.isdir(os.path.join(SRC, name)):
            continue
        m = re.match(r"^(\d{2})\.\s*(.+)$", name)
        if not m:
            continue
        n = int(m.group(1))
        if 1 <= n <= 28:
            out.append((n, name))
    out.sort(key=lambda x: x[0])
    return out


def build_pages():
    pages = []

    def add(src, url, nav, group, kind, img_dir=""):
        pages.append({"src": src, "url": url, "nav": nav, "group": group,
                      "kind": kind, "img_dir": img_dir,
                      "file": url_to_file(url)})

    add("README.md", "", "首页", "", "home")
    for src, rel, nav in GUIDE_FILES:
        add(src, rel, nav, "guide", "doc")
    for n, dirname in discover_chapters():
        add("%s/README.md" % dirname, "ch/%02d/" % n,
            SHORT_TITLES.get(n, dirname), "ch%02d" % n, "doc", img_dir=dirname)
    for src, rel, nav in APPENDIX_FILES:
        add(src, rel, nav, "appendix", "doc")
    return pages


def build_url_map(pages):
    return {p["src"]: p["url"] for p in pages if p["src"]}


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------

A_RE = re.compile(r'(<a\s[^>]*?href=")([^"]*)(")')
TABLE_RE = re.compile(r"<table>.*?</table>", re.S)
IMG_RE = re.compile(r"<img\s[^>]*>")


def postprocess(body, page, src2url):
    body, toc = add_heading_ids(body)
    cur_file = page["file"]
    src_dir = posixpath.dirname(page["src"]) if page["src"] else ""

    def rewrite(m):
        pre, href, post = m.group(1), m.group(2), m.group(3)
        new = href
        if href and not href.startswith("#") and not href.startswith("//") \
                and not href.startswith("/") \
                and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:", href):
            path, sep, frag = href.partition("#")
            if path:
                joined = posixpath.normpath(posixpath.join(src_dir, urllib.parse.unquote(path)))
                if joined == ".":
                    joined = ""
                hit = None
                for cand in (joined, joined.rstrip("/") + "/README.md"):
                    if cand in src2url:
                        hit = src2url[cand]
                        break
                if hit:
                    new = rel_link(cur_file, hit) + (sep + frag if sep else "")
        if new.startswith("http") and "castorhrio.github.io" not in new:
            return pre + new + post + ' target="_blank" rel="noopener noreferrer"'
        return pre + new + post

    body = A_RE.sub(rewrite, body)
    body = TABLE_RE.sub(lambda m: '<div class="table-wrap">%s</div>' % m.group(0), body)

    def fix_img(m):
        tag = m.group(0)
        if 'loading="' not in tag:
            tag = tag[:-1] + ' loading="lazy" decoding="async">'
        return tag

    body = IMG_RE.sub(fix_img, body)
    return body, toc


def render_nav(pages, current, absolute=False):
    """absolute=True 时输出 BASE 绝对链接 —— 404 页可能在任何深度被服务，必须用绝对路径。"""
    by_url = {p["url"]: p for p in pages}
    cur_file = current["file"]

    def href_for(url):
        if absolute:
            return BASE + "/" + url
        return rel_link(cur_file, url)

    def item(p, num=None):
        cls = "nav-item active" if p["url"] == current["url"] else "nav-item"
        numhtml = '<span class="nav-num">%s</span>' % num if num else ""
        return '<a class="%s" href="%s">%s%s</a>' % (
            cls, href_for(p["url"]), numhtml, html_mod.escape(p["nav"]))

    def group(title, range_, items):
        rng = '<span class="nav-range">%s</span>' % range_ if range_ else ""
        return ('<div class="nav-group"><div class="nav-group-title">%s%s</div>%s</div>'
                % (html_mod.escape(title), rng, "".join(items)))

    parts = []
    home = by_url.get("")
    if home:
        hcls = "nav-home active" if home["url"] == current["url"] else "nav-home"
        parts.append('<a class="%s" href="%s">&#9751;&nbsp;%s</a>'
                     % (hcls, href_for(""), html_mod.escape(home["nav"])))

    parts.append(group("开始学习", "",
                       [item(p) for p in pages if p["group"] == "guide"]))

    for part_no, part_name, range_, nums in PARTS:
        items = [item(by_url["ch/%02d/" % n], "%02d" % n)
                 for n in nums if "ch/%02d/" % n in by_url]
        parts.append(group("%s　%s" % (part_no, part_name), range_, items))

    parts.append(group("附录", "",
                       [item(p) for p in pages if p["group"] == "appendix"]))
    return "\n".join(parts)


def render_toc(toc):
    if not toc:
        return ""
    out = ['<div class="toc-title">本页目录</div>']
    for lvl, slug, text in toc:
        out.append('<a class="lv%d" href="#%s">%s</a>' % (lvl, slug, html_mod.escape(text)))
    return "\n".join(out)


def render_pager(pages, current):
    idx = next((i for i, p in enumerate(pages) if p["url"] == current["url"]), None)
    if idx is None:
        return ""
    out = []
    if idx > 0:
        p = pages[idx - 1]
        out.append('<a class="prev" href="%s"><span class="pg-label">&larr; 上一页</span>'
                   '<span class="pg-title">%s</span></a>'
                   % (rel_link(current["file"], p["url"]), html_mod.escape(p["nav"])))
    else:
        out.append('<span class="spacer"></span>')
    if idx < len(pages) - 1:
        p = pages[idx + 1]
        out.append('<a class="next" href="%s"><span class="pg-label">下一页 &rarr;</span>'
                   '<span class="pg-title">%s</span></a>'
                   % (rel_link(current["file"], p["url"]), html_mod.escape(p["nav"])))
    else:
        out.append('<span class="spacer"></span>')
    return "".join(out)


# --------------------------------------------------------------------------
# 模板
# --------------------------------------------------------------------------

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta name="color-scheme" content="dark light">
<link rel="stylesheet" href="{prefix}assets/style.css">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%234493f8'/%3E%3Ctext x='16' y='23' font-size='15' font-family='sans-serif' font-weight='bold' fill='white' text-anchor='middle'%3ESD%3C/text%3E%3C/svg%3E">
<script>try{{var t=localStorage.getItem('sdg-theme');if(t)document.documentElement.setAttribute('data-theme',t);}}catch(e){{}}</script>
</head>
<body>
<a class="skip" href="#main">跳到正文</a>
<header class="topbar">
  <button class="icon-btn" id="navToggle" aria-label="打开目录" title="目录">&#9776;</button>
  <a class="brand" href="{home}"><span class="logo">SD</span><span class="t">{sitetitle}</span></a>
  <div class="topbar-spacer"></div>
  <div class="search-wrap">
    <input id="search" type="search" placeholder="搜索章节 / 术语 / 关键词…" autocomplete="off" spellcheck="false" aria-label="搜索">
    <div id="searchResults" class="search-results" hidden></div>
  </div>
  <a class="icon-btn" href="{repo}" target="_blank" rel="noopener" title="GitHub 仓库" aria-label="GitHub 仓库">GH</a>
  <button class="icon-btn" id="themeToggle" aria-label="切换主题" title="切换主题">&#9788;</button>
</header>
<div class="layout{layoutclass}">
  <aside class="sidebar" id="sidebar">
{nav}
  </aside>
  <main class="content" id="main">
    <article class="md">
{content}
    </article>
    <nav class="pager">{pager}</nav>
    <footer class="sitefoot">
      <p>本页整理自 <a href="{repo}">castorhrio/system-design-guide</a>；原项目 <a href="{source}">liquidslr/system-design-notes</a> 未附带开源许可证，本仓库定位为个人学习笔记的中文整理，仅供学习交流。</p>
      <p>文中 392 张图片均来自原项目，版权归原作者 / 出版方所有。具体数字只作量级参考，生产决策请以官方文档与压测为准。</p>
    </footer>
  </main>
  <aside class="toc">
{toc}
  </aside>
</div>
<div id="scrim"></div>
<button id="toTop" aria-label="回到顶部" title="回到顶部">&#8593;</button>
<script>window.SDG_SITE={{prefix:"{prefix}"}};</script>
<script src="{prefix}assets/app.js" defer></script>
</body>
</html>
"""


def render_page(page, content, toc_html, nav_html, pager_html, title):
    return TEMPLATE.format(
        title=html_mod.escape(title),
        desc=html_mod.escape(SITE_DESC),
        prefix=page_prefix(page["file"]),
        home=rel_link(page["file"], ""),
        sitetitle=html_mod.escape(SITE_TITLE),
        repo=REPO_URL,
        source=SOURCE_URL,
        layoutclass="" if toc_html else " no-toc",
        nav=nav_html,
        content=content,
        pager=pager_html,
        toc=toc_html,
    )


# --------------------------------------------------------------------------
# 搜索索引
# --------------------------------------------------------------------------

def build_chunks(page, body, per_row=False):
    chunks = []
    text_of = lambda s: re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", " ", s))).strip()
    base = page["url"]

    matches = list(re.finditer(r'<h([1-6]) id="([^"]+)"[^>]*>(.*?)</h\1>', body, re.S))
    for i, m in enumerate(matches):
        if int(m.group(1)) not in (2, 3, 4):
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        excerpt = text_of(body[start:end])[:160]
        heading = text_of(m.group(3))
        if not excerpt and len(heading) < 2:
            continue
        chunks.append({"u": base + "#" + m.group(2), "t": page["nav"],
                       "h": heading, "x": excerpt})

    if per_row:
        for tm in re.finditer(r"<tbody>(.*?)</tbody>", body, re.S):
            for rm in re.finditer(r"<tr>(.*?)</tr>", tm.group(1), re.S):
                cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", rm.group(1), re.S)
                if not cells:
                    continue
                term = text_of(cells[0])
                if len(term) < 2:
                    continue
                rest = " — ".join(text_of(c) for c in cells[1:])
                chunks.append({"u": base, "t": page["nav"], "h": term, "x": rest[:160]})

    chunks.insert(0, {"u": base or "./", "t": page["nav"], "h": page["nav"],
                      "x": text_of(body)[:160]})
    return chunks


# --------------------------------------------------------------------------
# 附录首页（源仓库没有 99-附录/README.md，这里生成一个）
# --------------------------------------------------------------------------

APPENDIX_INDEX_MD = """# 附录

正文之外的速查资料。学的时候不必通读，遇到问题再回来查更有效。

| 文件 | 内容 | 什么时候看 |
|---|---|---|
| [术语表](glossary.html) | 494 条中英对照术语，含 16 组易混淆概念辨析 | 读英文资料时对不上号 |
| [勘误与补充汇总](errata.html) | 127 条勘误 + 182 条补充，按错误类型速查 | 想确认自己学的对不对 |
| [高频面试题速查](interview.html) | 考点、数字、追问、误区、检查清单 | 面试前突击 |

## 术语表怎么用

术语表按主题分成 12 组（基础架构、数据存储、一致性、消息与流、缓存、网络与协议、
安全、可观测性、部署与运维、分布式协调、数据结构、业务模式），每组后面附了易混淆概念的对比辨析。

搜索框可以直接搜中文或英文：输入 `quorum` 或 `法定人数` 都能定位。

## 勘误汇总怎么用

每一条勘误都写成固定四段：**原文怎么说 → 为什么不对 → 正确说法 → 延伸阅读**。
如果你手上有原项目或 Alex Xu 的原书，可以对着章节号逐条核对。
"""


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def main():
    pages = build_pages()
    src2url = build_url_map(pages)

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, "assets"), exist_ok=True)
    open(os.path.join(OUT, ".nojekyll"), "w").close()

    shutil.copy2(os.path.join(ASSETS, "style.css"), os.path.join(OUT, "assets", "style.css"))
    shutil.copy2(os.path.join(ASSETS, "app.js"), os.path.join(OUT, "assets", "app.js"))

    search_index = []
    problems = []
    written = 0
    images_copied = 0

    def emit(page, body, title):
        nonlocal written
        content, toc = postprocess(body, page, src2url)
        doc = render_page(page, content, render_toc(toc),
                          render_nav(pages, page), render_pager(pages, page), title)
        dest = os.path.join(OUT, page["file"].replace("/", os.sep))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8", newline="\n") as f:
            f.write(doc)
        written += 1
        search_index.extend(build_chunks(page, content,
                                        per_row=page["url"].endswith("glossary.html")))

    home = pages[0]
    emit(home, MD.render(read_text(os.path.join(SRC, home["src"]))), SITE_TITLE)

    for page in pages[1:]:
        src_path = os.path.join(SRC, page["src"].replace("/", os.sep))
        if not os.path.isfile(src_path):
            problems.append("缺少源文件: %s" % page["src"])
            continue
        text = read_text(src_path)
        m = re.search(r"^#\s+(.+?)\s*$", text, re.M)
        emit(page, MD.render(text),
             "%s · %s" % (m.group(1).strip() if m else page["nav"], SITE_TITLE))

    ap = {"src": "", "url": "appendix/", "nav": "附录", "group": "appendix",
          "kind": "index", "img_dir": "", "file": "appendix/index.html"}
    emit(ap, MD.render(APPENDIX_INDEX_MD), "附录 · %s" % SITE_TITLE)

    for page in pages:
        if not page["img_dir"]:
            continue
        src_img = os.path.join(SRC, page["img_dir"], "images")
        if not os.path.isdir(src_img):
            continue
        dst_img = os.path.join(OUT, posixpath.dirname(page["file"]).replace("/", os.sep), "images")
        os.makedirs(dst_img, exist_ok=True)
        for fn in os.listdir(src_img):
            shutil.copy2(os.path.join(src_img, fn), os.path.join(dst_img, fn))
            images_copied += 1

    with open(os.path.join(OUT, "assets", "search.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(search_index, f, ensure_ascii=False, separators=(",", ":"))

    # 404 页用绝对路径（它可能在任何深度被服务）
    nf = dict(home)
    nf["file"] = "404.html"
    nf["url"] = "__404__"
    doc = TEMPLATE.format(
        title="页面不存在 · " + SITE_TITLE, desc=html_mod.escape(SITE_DESC),
        prefix=BASE + "/", home=BASE + "/", sitetitle=html_mod.escape(SITE_TITLE),
        repo=REPO_URL, source=SOURCE_URL, layoutclass=" no-toc",
        nav=render_nav(pages, pages[0], absolute=True), pager="", toc="",
        content='<h1 id="p404">404 · 页面不存在</h1>\n'
                '<p>这个地址没有对应内容。试试从<a href="%s/">首页</a>进入，'
                '或者用右上角的搜索框。</p>' % BASE)
    with open(os.path.join(OUT, "404.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(doc)

    print("source      : %s" % SRC)
    print("output      : %s" % OUT)
    print("pages       : %d" % written)
    print("images      : %d" % images_copied)
    print("search items: %d  (%.0f KB)"
          % (len(search_index), os.path.getsize(os.path.join(OUT, "assets", "search.json")) / 1024))
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print("  - %s" % p)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
