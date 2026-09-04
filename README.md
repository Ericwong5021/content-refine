# content-refine (内容精炼)

> 创作者视频知识全景书的标准化提取、重组、成书与自动化发布引擎。

---

## 架构概览

本项目采用 **pnpm Monorepo** 架构，将生产流水线、通用前端阅读模板、多博主独立站点实例统一治理：

```text
content-refine/
├── pipeline/                           # 【生产流水线】ASR转录、Codex观点提取、Markdown全书与数据导出
├── template/                           # 【核心模板】Next.js 16 + React 19 通用电子书阅读器
├── sites/                              # 【博主独立实例】多博主站点矩阵
│   ├── aaa-linxi/                      # AAA麟西 (aaa-linxi-ebook.vercel.app)
│   └── facai-xiongdi/                  # 发财兄弟 (facai-xiongdi-ebook.vercel.app)
├── content-store/                      # 【长期存证库】原始 ASR、Codex 校订快照与 Markdown 书稿
├── .github/workflows/                  # 【CI/CD】代码静态检查与各博主独立部署
└── cli.py                              # 【统一命令行工具】
```

---

## 快速上手

### 1. 环境准备
* Node.js >= 22
* pnpm >= 11 (`corepack enable pnpm`)
* Python >= 3.10

安装前端 Monorepo 依赖：
```bash
pnpm install
```

### 2. 本地开发与预览

独立启动某个博主的电子书站点：
```bash
# 方式 A：使用 root 快捷命令
pnpm dev:linxi          # 预览 AAA麟西 (http://localhost:3000)
pnpm dev:facai          # 预览 发财兄弟 (http://localhost:3000)

# 方式 B：使用 pnpm filter
pnpm --filter site-aaa-linxi dev
pnpm --filter site-facai-xiongdi dev
```

全量静态构建与类型检查：
```bash
pnpm build:all
```

---

## 标准化工作流（新增博主与出书）

### 第一步：创建新博主实例
使用统一 CLI 工具初始化新博主站点：
```bash
./cli.py site:create <博主ID> --title "<书名>" --author "<作者名>" --brand-mark "<首字>"
# 示例：
./cli.py site:create laoyao --title "老姚商业全景书" --author "老姚" --brand-mark "姚"
```
该命令会自动在 `sites/<博主ID>` 创建独立站点，并在 `content-store/<博主ID>` 建立存证目录。

### 第二步：运行流水线提取与校订
1. 在 `content-store/<博主ID>/items.jsonl` 中准备视频链接与 ID。
2. 运行转录与 Codex 校订流水线：
   ```bash
   # 转录音频
   python pipeline/transcribe.py content-store/<博主ID>/items.jsonl content-store/<博主ID>/raw content-store/<博主ID>/local-asr
   
   # Codex 结构化校订提取观点
   python pipeline/refine.py content-store/<博主ID>/local-asr content-store/<博主ID>/refined
   ```

### 第三步：编译出书并导出站点数据
```bash
# 导出前端渲染所需的 book.json
./cli.py pipeline:export <博主ID>
```

### 第四步：同步阅读器模板升级（可选）
当 `template/` 阅读器新增功能（如排版增强、深色模式等）时，一键同步到所有博主实例：
```bash
./cli.py site:sync-template
```

---

## CI/CD 与自动化部署

本项目通过 GitHub Actions 实现**增量自动化部署**：
* 配置文件：`.github/workflows/deploy.yml`
* 当推送代码至 `main` 分支时，工作流会自动检测哪个博主目录（`sites/<博主ID>`）发生了变更，并调用 Vercel 自动化部署对应站点，互不干扰。
* 仓库需在 GitHub Secrets 中配置 `VERCEL_TOKEN`。
