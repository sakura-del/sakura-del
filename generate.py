#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Neofetch-style GitHub profile card generator.

Reads profile.json, pulls numbers from the GitHub REST API, converts the avatar
into ASCII art and writes dark_mode.svg + light_mode.svg.

    python generate.py                 # cached if fresh (< 6 h)
    python generate.py --refresh       # always re-fetch
    python generate.py --offline       # cache only, no network
    python generate.py --preview       # also render preview-*.png via Edge/Chrome
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

from PIL import Image, ImageFilter, ImageOps

ROOT = os.path.dirname(os.path.abspath(__file__))
API = "https://api.github.com"

FONT_SIZE = 15
LINE_H = 19
ADVANCE = 9.0            # px per ASCII cell (Consolas 15px * size-adjust 109%)
PAD = 16
PORTRAIT_COLS = 48
VAL_COL = 30             # value column, in cells from the start of the line
CARD_W = 1050
PORTRAIT_GAP = 30

THEMES = {
    "dark": dict(bg="#161b22", stroke="#30363d", text="#c9d1d9", k="#ffa657",
                 v="#a5d6ff", cc="#616e7f", a="#3fb950", d="#f85149", pt="#8b949e"),
    "light": dict(bg="#ffffff", stroke="#d0d7de", text="#1f2328", k="#953800",
                  v="#0550ae", cc="#8c959f", a="#1a7f37", d="#cf222e", pt="#6e7781"),
}

RAMP = " .:-=+*#%@"


def log(*a):
    print(*a)


# ---------------------------------------------------------------- github api
def http_json(url, token=None, tries=3, allow_202=False):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "neofetch-profile-card",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    last = None
    for attempt in range(tries):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                status = getattr(r, "status", 200)
                body = r.read().decode("utf-8")
                hdrs = dict(r.headers)
            if status == 202:
                # GitHub returns 202 while it computes repo statistics
                if allow_202:
                    time.sleep(2 + attempt * 2)
                    last = "202 (computing)"
                    continue
                return None, hdrs
            return (json.loads(body) if body.strip() else None), hdrs
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            last = "%s %s" % (e.code, body[:200])
            if e.code == 404:
                return None, dict(e.headers)
            if e.code in (403, 429):
                raise RuntimeError("GitHub API limit hit (%s): %s" % (url, body[:200]))
            time.sleep(1 + attempt)
        except Exception as e:                      # noqa: BLE001 - network
            last = repr(e)
            time.sleep(1 + attempt)
    raise RuntimeError("request failed: %s (%s)" % (url, last))


def link_last_page(headers):
    link = headers.get("Link") or headers.get("link") or ""
    m = re.search(r'[?&]page=(\d+)>;\s*rel="last"', link)
    return int(m.group(1)) if m else None


def fetch_data(username, token, refresh=False):
    cache_dir = os.path.join(ROOT, "cache")
    cache_path = os.path.join(cache_dir, "stats.json")
    if not refresh and os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        if cached.get("username") == username and time.time() - cached.get("_ts", 0) < 6 * 3600:
            log("  cache: %.1f h old (--refresh to re-fetch)" % ((time.time() - cached["_ts"]) / 3600))
            return cached

    log("  GET /users/%s" % username)
    user, _ = http_json("%s/users/%s" % (API, username), token)
    log("  GET /users/%s/repos" % username)
    repos, _ = http_json("%s/users/%s/repos?per_page=100&sort=updated" % (API, username), token) or ([], {})
    repos = repos or []

    stars = sum(r["stargazers_count"] for r in repos)
    homepage = next((r["homepage"].strip() for r in repos if (r.get("homepage") or "").strip()), "")
    languages, commits, loc_add, loc_del = {}, 0, 0, 0
    for r in repos:
        full = r["full_name"]
        try:
            _, hdrs = http_json(
                "%s/repos/%s/commits?author=%s&per_page=1" % (API, full, username), token)
            n = link_last_page(hdrs)
            commits += 1 if (n is None and hdrs.get("status") != "404") else (n or 0)
        except Exception as e:                      # noqa: BLE001
            log("    ! commits %s: %s" % (full, e))
        try:
            lang, _ = http_json("%s/repos/%s/languages" % (API, full), token)
            for k, v in (lang or {}).items():
                languages[k] = languages.get(k, 0) + v
        except Exception as e:                      # noqa: BLE001
            log("    ! languages %s: %s" % (full, e))
        try:
            freq, _ = http_json("%s/repos/%s/stats/code_frequency" % (API, full),
                                token, tries=6, allow_202=True)
            for w in freq or []:
                if isinstance(w, list) and len(w) >= 3:
                    # GitHub reports deletions as negative numbers
                    loc_add += abs(int(w[1]))
                    loc_del += abs(int(w[2]))
        except Exception as e:                      # noqa: BLE001
            log("    ! code_frequency %s: %s" % (full, e))
        log("    ok %s" % full)

    data = dict(
        username=username,
        name=user.get("name"),
        bio=user.get("bio"),
        blog=((user.get("blog") or "").strip() or homepage),
        created_at=user.get("created_at"),
        avatar_url=user.get("avatar_url"),
        repos=len([r for r in repos if not r["fork"]]),
        contributed=len(repos),
        stars=stars,
        followers=user.get("followers", 0),
        following=user.get("following", 0),
        commits=commits,
        loc_add=loc_add,
        loc_del=loc_del,
        loc=loc_add - loc_del,
        languages=languages,
        _ts=time.time(),
    )
    os.makedirs(cache_dir, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def uptime(created_at):
    if not created_at:
        return "unknown"
    start = dt.datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    years = now.year - start.year
    months = now.month - start.month
    days = now.day - start.day
    if days < 0:
        months -= 1
        days += (now.replace(day=1) - dt.timedelta(days=1)).day
    if months < 0:
        years -= 1
        months += 12
    parts = []
    if years:
        parts.append("%d year%s" % (years, "" if years == 1 else "s"))
    if months:
        parts.append("%d month%s" % (months, "" if months == 1 else "s"))
    parts.append("%d day%s" % (days, "" if days == 1 else "s"))
    return ", ".join(parts)


# ------------------------------------------------------------ avatar -> ascii
def ensure_avatar(path, url):
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    log("  download avatar -> %s" % os.path.basename(path))
    req = urllib.request.Request(url, headers={"User-Agent": "neofetch-profile-card"})
    with urllib.request.urlopen(req, timeout=90) as r, open(path, "wb") as f:
        f.write(r.read())
    return path


def ascii_portrait(path, cfg):
    img = Image.open(path).convert("L")
    if cfg.get("crop"):
        img = img.crop(tuple(cfg["crop"]))
    img = img.resize((max(1, img.width // 2), max(1, img.height // 2)), Image.LANCZOS)
    if cfg.get("blur", 0.8):
        img = img.filter(ImageFilter.GaussianBlur(cfg["blur"]))
    if cfg.get("sharpen", 0):
        img = img.filter(ImageFilter.UnsharpMask(
            radius=3, percent=int(cfg["sharpen"] * 100), threshold=2))
    if cfg.get("invert"):
        img = ImageOps.invert(img)
    lo, hi = cfg.get("lo", 0.45), cfg.get("hi", 0.90)
    img = img.point([
        int(round(min(1.0, max(0.0, (i / 255.0 - lo) / max(1e-6, hi - lo))) * 255))
        for i in range(256)
    ])
    cols = cfg.get("cols", PORTRAIT_COLS)
    w, h = img.size
    cell = cfg.get("cell", LINE_H / ADVANCE)
    rows = max(1, int(round(cols * (h / w) / cell)))
    px = img.resize((cols, rows), Image.LANCZOS)
    gamma = cfg.get("gamma", 0.55)
    ramp = cfg.get("ramp", RAMP)
    n = len(ramp) - 1
    lines = []
    for y in range(rows):
        line = "".join(
            ramp[int(round(((px.getpixel((x, y)) / 255.0) ** gamma) * n))] for x in range(cols)
        ).rstrip()
        lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    return lines


# ----------------------------------------------------------------- text utils
def is_wide(ch):
    o = ord(ch)
    return (0x1100 <= o <= 0x115F or 0x2E80 <= o <= 0xA4CF or 0xAC00 <= o <= 0xD7A3
            or 0xF900 <= o <= 0xFAFF or 0xFE30 <= o <= 0xFE6F or 0xFF00 <= o <= 0xFF60
            or 0xFFE0 <= o <= 0xFFE6 or 0x1F300 <= o <= 0x1FAFF)


def disp_w(s):
    return sum(2 if is_wide(c) else 1 for c in str(s))


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fill_dots(used, val_col=VAL_COL):
    """Dots that put the value column at `val_col` cells, like neofetch does."""
    gap = val_col - used
    if gap <= 0:
        return " "
    if gap <= 3:
        return " " * gap
    return " " + "." * (gap - 2) + " "


def field_line(key, value, key_cls="k", value_cls="v"):
    used = 2 + disp_w(key) + 1
    return [(". ", "cc"), (key, key_cls), (":", "cc"),
            (fill_dots(used), "cc"), (value, value_cls)]


def blank_line():
    return [(".", "cc")]


def title_line(text, target=61):
    w = disp_w(text)
    return [(text, "t"), (" " + "─" * max(0, target - w - 1), "cc")]


# ---------------------------------------------------------------- content
def build_content(cfg, data):
    langs = data.get("languages") or {}
    skip = {"HTML", "CSS", "Markdown", "JSON", "YAML", "Dockerfile", "Shell", "Batchfile"}
    code = [k for k, _ in sorted(langs.items(), key=lambda kv: -kv[1]) if k not in skip]
    markup = [k for k in ("HTML", "CSS", "SCSS", "Shell", "Dockerfile", "Markdown", "JSON")
              if k in langs]

    def fit_list(items, max_cells=30):
        out = []
        for it in items:
            cand = ", ".join(out + [it])
            if out and disp_w(cand) > max_cells:
                break
            out.append(it)
        return ", ".join(out) if out else "-"

    subs = {
        "username": cfg["username"],
        "host": cfg.get("host", "localhost"),
        "name": data.get("name") or cfg["username"],
        "uptime": uptime(data.get("created_at")),
        "repos": "{:,}".format(data["repos"]),
        "contributed": "{:,}".format(data["contributed"]),
        "stars": "{:,}".format(data["stars"]),
        "followers": "{:,}".format(data["followers"]),
        "commits": "{:,}".format(data["commits"]),
        "loc": "{:,}".format(data["loc"]),
        "loc_add": "{:,}".format(data["loc_add"]),
        "loc_del": "{:,}".format(data["loc_del"]),
        "langs": fit_list(code),
        "markup": fit_list(markup),
        "blog": re.sub(r"^https?://", "", data.get("blog") or "").rstrip("/") or "-",
        "email": cfg.get("email") or "-",
        "bio": data.get("bio") or "-",
    }

    def sub(s):
        return re.sub(r"\{\{(\w+)\}\}", lambda m: str(subs.get(m.group(1), m.group(0))), str(s))

    lines = []
    for sec in cfg["sections"]:
        if sec.get("blank_before") and lines:
            lines.append(blank_line())
        if sec.get("title"):
            lines.append(title_line(sub(sec["title"])))
        for f in sec.get("fields", []):
            if f.get("blank_before"):
                lines.append(blank_line())
            lines.append(field_line(sub(f["key"]), sub(f["value"])))

    st = cfg.get("stats") or {}
    if st.get("enabled", True):
        if lines:
            lines.append(blank_line())
        lines.append(title_line(st.get("title", "- GitHub Stats")))
        for r in st.get("rows", []):
            if r.get("type") == "pair":
                lk, rk = sub(r["left_key"]), sub(r["right_key"])
                lv, rv = sub(r["left_value"]), sub(r["right_value"])
                used = 2 + disp_w(lk) + 1
                left = [(". ", "cc"), (lk, "k"), (":", "cc"), (fill_dots(used), "cc"), (lv, "v")]
                head = sum(disp_w(t) for t, _ in left) + 3          # + " | "
                right = [(" | ", "cc"), (rk, "k"), (":", "cc")]
                right_used = head + sum(disp_w(t) for t, _ in right)
                right += [(fill_dots(right_used, r.get("right_col", 54)), "cc"), (rv, "v")]
                lines.append(left + right)
            elif r.get("type") == "loc":
                key = sub(r.get("key", "Lines of Code on GitHub"))
                value = sub("{{loc}}")
                add, dele = sub("{{loc_add}}"), sub("{{loc_del}}")
                used = 2 + disp_w(key) + 1
                lines.append([(". ", "cc"), (key, "k"), (":", "cc"),
                              (fill_dots(used), "cc"), (value, "v"),
                              (" ( ", "cc"), (add, "a"), ("++", "a"), (", ", "cc"),
                              (dele, "d"), ("--", "d"), (" )", "cc")])
    return lines


# --------------------------------------------------------------------- svg
def write_svg(path, theme_name, rows_needed, portrait, content):
    t = THEMES[theme_name]
    right_x = PAD + PORTRAIT_COLS * ADVANCE + PORTRAIT_GAP
    height = PAD + 14 + rows_needed * LINE_H + PAD - LINE_H + 6
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<svg xmlns="http://www.w3.org/2000/svg" width="%dpx" height="%dpx" '
             'font-family="ConsolasFallback,Consolas,Menlo,monospace" font-size="%dpx" '
             'xml:space="preserve" role="img" aria-label="GitHub profile card">'
             % (CARD_W, height, FONT_SIZE),
             "<style>@font-face{src:local('Consolas'),local('Menlo'),local('Cascadia Mono');"
             "font-family:'ConsolasFallback';size-adjust:109%%;}"
             ".k{fill:%s}.v{fill:%s}.cc{fill:%s}.a{fill:%s}.d{fill:%s}.t{fill:%s;font-weight:bold}"
             "text,tspan{white-space:pre;}</style>"
             % (t["k"], t["v"], t["cc"], t["a"], t["d"], t["k"]),
             '<rect x="0.5" y="0.5" width="%d" height="%d" rx="%d" fill="%s" stroke="%s"/>'
             % (CARD_W - 1, height - 1, 15, t["bg"], t["stroke"])]

    parts.append('<text x="%d" y="%d" fill="%s">' % (PAD, PAD + 14, t["pt"]))
    for i, line in enumerate(portrait):
        if line:
            parts.append('<tspan x="%d" y="%d">%s</tspan>'
                         % (PAD, PAD + 14 + i * LINE_H, esc(line)))
    parts.append("</text>")

    parts.append('<text x="%d" y="%d" fill="%s">' % (right_x, PAD + 14, t["text"]))
    for i, line in enumerate(content):
        if not line:
            continue
        y = PAD + 14 + i * LINE_H
        # one anchored tspan per row; the inner tspans flow horizontally from it
        row = ['<tspan x="%d" y="%d">' % (right_x, y)]
        for text, cls in line:
            if not text:
                continue
            row.append('<tspan class="%s">%s</tspan>' % (cls, esc(text)))
        row.append("</tspan>")
        parts.append("".join(row))
    parts.append("</text>")
    parts.append("</svg>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts) + "\n")
    return height


def find_browser():
    for p in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ):
        if os.path.exists(p):
            return p
    return None


def render_preview(svg_name, png_name, width, height, browser):
    url = "file:///" + os.path.join(ROOT, svg_name).replace("\\", "/")
    out = os.path.join(ROOT, png_name)
    subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=2", "--screenshot=" + out,
                    "--window-size=%d,%d" % (width, height), url],
                   check=False, capture_output=True, timeout=120)
    return out if os.path.exists(out) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    args = ap.parse_args()

    with open(os.path.join(ROOT, "profile.json"), "r", encoding="utf-8") as f:
        cfg = json.load(f)

    if args.offline:
        with open(os.path.join(ROOT, "cache", "stats.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        log("GitHub data: @%s" % cfg["username"])
        data = fetch_data(cfg["username"], args.token, args.refresh)

    avatar_path = os.path.join(ROOT, cfg.get("avatar", {}).get("file", "avatar.png"))
    if not os.path.exists(avatar_path):
        ensure_avatar(avatar_path, (data.get("avatar_url") or "") + "&s=460")
    portrait = ascii_portrait(avatar_path, cfg.get("avatar", {}))
    content = build_content(cfg, data)
    rows = max(len(portrait), len(content))
    log("  portrait %d rows, text %d lines, widest %d cells"
        % (len(portrait), len(content), max(disp_w("".join(t for t, _ in l)) for l in content)))

    size = {}
    for theme in ("dark", "light"):
        size[theme] = write_svg(os.path.join(ROOT, "%s_mode.svg" % theme), theme, rows,
                                portrait, content)
        log("  wrote %s_mode.svg" % theme)

    if args.preview:
        b = find_browser()
        if not b:
            log("  ! no Chrome/Edge found, skip preview")
        else:
            for theme in ("dark", "light"):
                png = render_preview("%s_mode.svg" % theme, "preview-%s.png" % theme,
                                     CARD_W, size[theme], b)
                log("  preview: %s" % png)

    log("  repos=%s stars=%s commits=%s followers=%s loc=%s (+%s/-%s)"
        % (data["repos"], data["stars"], data["commits"], data["followers"],
           "{:,}".format(data["loc"]), "{:,}".format(data["loc_add"]),
           "{:,}".format(data["loc_del"])))


if __name__ == "__main__":
    main()
