# Changelog

本项目所有重要修改都记录在此文件。
遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 规范，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- 初始化 git 仓库并接入 GitHub 远程（硬指标：版本控制 + GitHub）。
- 新增 `.gitignore`：排除机密（`cookies.json`、令牌）、大体积媒体（`downloads/`）、Python 缓存。
- 新增 `CHANGELOG.md`：建立"每次修改必有 changelog"的工程规范。
- 安装 BMAD-METHOD v6.8.0（core + bmm 模块，44 个 skill，中文交流/文档）。
- 新增 `资源库需求.md`：记录资源库 / 资源后台项目需求与硬指标。

### 现有基础（接管前已存在）
- `ig_downloader.py`：基于 instaloader 的 Instagram 图片/Story 下载脚本。
- `requirements.txt`、`usernames.txt`：依赖与目标账号清单。
