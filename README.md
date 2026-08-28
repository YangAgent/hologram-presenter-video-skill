# hologram-presenter-video-skill

Agent Skills 仓库，目前包含一个 skill：[hologram-presenter-video](skills/hologram-presenter-video)。

## hologram-presenter-video 是什么

将用户内容制作成**单人知识讲解视频**的 Agent Skill：一个讲解角色开口口播，与悬浮全息信息互动，产出单个 MP4 成品。适用于知识科普、教程、信息摘要或产品机制说明。

## 核心设计

- **可复用 Profile**：首次使用时通过一次访谈建立角色与场景档案（`profile/profile.json`），之后所有视频任务复用同一套 Profile，保证角色形象、场景风格、呈现方式前后一致。
- **Gate 确认机制**：从 Profile 构建（Gate0）到分镜、口播稿、视频生成，每个关键节点都必须等用户明确确认才推进，全程可追溯，不会静默生成。
- **分段生成 + 合并**：视频按分镜拆成多个片段生成，片段间通过硬切改变视角与构图，最后合并为一个 MP4；不添加背景音乐和转场。
- **口播稿即事实来源**：角色只说用户确认过的口播文稿内容，不静默引入外部事实。
- **相对路径约定**：指令、脚本、配置与运行产物全部使用相对路径，不依赖 skill 安装位置。

## 与 MiniMax H3 生态的协作

- **依赖 `h3-prompt-writing` Skill**：本 skill 依赖运行环境中安装的 MiniMax H3 官方 `h3-prompt-writing` skill，由它按 H3 当前规范生成结构化提示词（Ref2VA 模式）。本 skill 不内置、不复刻该规范，始终加载该 Skill 的实时定义来产出提示词。
- **提示词是核心产物**：skill 最终产出整套 H3 结构化提示词，以及描述参考图视频生成任务的 `ref2v-tasks.json` 任务清单。
- **有则调用，无则止步**：如果运行环境中存在 MiniMax H3 的参考图生成视频 Skill，本 skill 会自动搜索发现并调用它，把任务清单交给它生成视频片段；如果环境中没有这类 Skill，流程则只产出到提示词与任务清单为止。本 skill 不内置任何视频生成 API。

## 目录结构

```
hologram-presenter-video-skill/
└── skills/
    └── hologram-presenter-video/   # 全息讲解视频 skill
        ├── SKILL.md                # Skill 入口与流程编排
        ├── agents/openai.yaml      # Agent 接口元数据
        ├── references/             # 阶段参考文档（如 Profile 访谈流程）
        └── scripts/                # 辅助脚本（口播密度检查、视频合并）
```

## 运行产物

运行时生成的 `profile/`（角色场景档案）创建在skill内部，`hologram-video-runs/`（单次运行清单、口播稿、分镜与视频片段）以及成品视频均在用户当前工作目录下创建，已被 `.gitignore` 排除，不会进入本仓库。
