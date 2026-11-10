# 说明（不用提交到 GitHub 也行，留着自己看）

这套东西就是把 `dark_mode.svg` / `light_mode.svg` 两张图当头像卡贴在 GitHub 主页上，
数字由 GitHub Actions 每天跑一次 `generate.py` 重新拉取并提交。

## 1. 上线（3 步）

仓库名必须是 **`sakura-del/sakura-del`**（和用户名同名），它的 `README.md` 才会显示在主页。

```powershell
# 在 github.com 上先建一个空的公开仓库 sakura-del/sakura-del，不要勾选 README
cd C:\Users\Lenovo\Desktop\github-profile-card
git init
git add README.md dark_mode.svg light_mode.svg generate.py profile.json avatar.png cache\stats.json .github\workflows\build.yaml
git commit -m "feat: neofetch profile card"
git remote add origin https://github.com/sakura-del/sakura-del.git
git push -u origin main
```

推完打开 <https://github.com/sakura-del> 就能看到。GitHub 默认给新仓库开 Actions，
第一次 push 会顺带跑一次 workflow（`Actions` 标签页里能看到绿勾）。

> 本机直连 `git push` 常被墙掉，需要走代理：
> `git -c http.proxy=http://127.0.0.1:7894 -c https.proxy=http://127.0.0.1:7894 push -u origin main`

## 2. 改内容

`profile.json` 里三块：

| 位置 | 作用 |
| --- | --- |
| `sections[].fields` | 左侧文字区的每一行，`{{...}}` 是自动变量 |
| `stats.rows` | GitHub 统计区，数字自动填 |
| `avatar` | 头像转 ASCII 的参数（裁剪框、对比度、字符宽度） |

可用变量：`{{username}} {{host}} {{uptime}} {{repos}} {{contributed}} {{stars}} {{commits}}
{{followers}} {{loc}} {{loc_add}} {{loc_del}} {{langs}} {{markup}} {{blog}} {{email}}`

改完本地预览（会调 Edge 无头截图）：

```powershell
python generate.py --refresh --preview      # 生成 + preview-dark.png / preview-light.png
python generate.py --offline                # 只用 cache，不联网
```

刷新数字不一定现在就跑：脚本有 6 小时缓存，要强制重拉加 `--refresh`。

## 3. 头像换 / 调

- 想换头像：覆盖 `avatar.png`（方形，≥460px），再 `--refresh` 重跑。照片比线稿转 ASCII 好看得多。
- 头像太黑/太白：调 `avatar.lo` / `avatar.hi`（亮度区间，窄一点对比更强）、`avatar.gamma`。
- 只想要脸：调 `avatar.crop`（原图坐标 `[左, 上, 右, 下]`，460×460 时脸大致在 `[150,150,400,420]`）。
- 字符集：`avatar.ramp`，默认 `" .:-=+*#%@"`。

## 4. 常见问题

- **改了 SVG，主页没变**：GitHub 的图片走 camo 代理，会缓存几小时。给 README 里的 URL 加 `?v=2` 之类的参数可立即刷新。
- **深色/浅色不一致**：靠 `<picture>` + `prefers-color-scheme` 切两张图，浏览器设置跟随 GitHub 主题。
- **中文字宽**：SVG 用 Consolas + 中文回退字体，中文按 2 格算；`Languages.Real` 这类中文只出现在行尾，不影响对齐。
- **Actions 失败**：多半是 `code_frequency` 接口返回 202（GitHub 正在算统计），脚本会自动重试 6 次，仍失败就沿用上次数值，不会把画写坏。
- **统计口径**：`repos` 只算自己名下的非 fork 仓库；`commits` 是这些仓库里你署名的提交数；`loc` 来自 GitHub 的 code frequency（增删行数差），私有仓库不算。
