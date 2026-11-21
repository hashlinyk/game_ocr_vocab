# game_ocr_vocab — 游戏画面离线英文单词助手

全离线的 Windows 工具：实时监视所选屏幕区域（含全屏游戏），画面变化时 OCR 识别英文单词，
逐行显示单词 + 中文翻译，支持标记「已掌握 / 生词本」和点击发音（Windows 离线 TTS）。

## 安装（仅需联网一次）

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python scripts/prepare_dict.py        # 下载 ECDICT 词典(~63MB) -> data/dict.db
.venv/Scripts/python scripts/prepare_ocr_models.py  # 预下载 OCR 模型(~30MB)
.venv/Scripts/python scripts/prepare_tts.py         # 下载 Piper 神经语音模型(~63MB)；跳过则回退 SAPI 机械音
```

GitHub 直连慢时给 prepare_dict 加镜像：`python scripts/prepare_dict.py --proxy https://ghfast.top/`
或设环境变量 `GH_PROXY`。

## 运行

```bash
.venv/Scripts/python -m game_ocr_vocab
```

点「框选区域」→ 全屏遮罩上拖拽框出游戏文字区域（Esc 取消）→ 面板自动追加新词。

## 功能

- 每行：单词 / 音标 / 中文翻译（悬停看完整释义）
- 「掌握」：标记已掌握并从列表移除，之后该词不再出现
- 「生词本」：移入生词本，同样不再出现（存 `data/vocab.db`，重启保留）
- 「发音」：Windows SAPI 离线朗读
- 词形还原：glows/forgotten/looted/potions 自动还原为 glow/forget/loot/potion 查词典
- 画面变化检测：缩小+灰度+像素差比例阈值，静止零触发；OCR 冷却 1.2s

## 调参

`game_ocr_vocab/config.py`：`CHANGE_RATIO`(变化灵敏度，调大更不敏感)、`COOLDOWN`、
`DEBUG_SAVE_FRAMES`(把每次触发 OCR 的帧存到 data/debug/ 供核对)。

## 免安装分发（CI 自动构建）

推送到 `main` 后 GitHub Actions 自动构建 Windows 免安装版：
仓库 **Actions → 最新 run → Artifacts** 下载 `game_ocr_vocab_win64_v<版本>.zip`，
或在 **Releases** 页下载（`latest` = 最新构建），解压双击 `游戏单词助手.exe` 即用（Windows 10/11 x64，全离线）。

## 版本管理

版本号唯一来源：`game_ocr_vocab/__init__.py` 的 `__version__`（设置窗口「关于」页可见）。

发正式版流程：

```bash
# 1. 修改 __version__ = "x.y.z"
# 2. 提交并打 tag
git commit -am "release vx.y.z"
git tag vx.y.z
git push && git push --tags
```

push tag（`v*`）会自动构建并创建对应版本号的 Release；push `main` 则滚动更新 `latest` Release。

本地打包：`pyinstaller game_ocr_vocab.spec --noconfirm`，产物在 `dist/game_ocr_vocab/`。
打包版词典/OCR 模型内置于程序中；用户词库（`vocab.db`）生成在 exe 同级 `data/` 目录。

## 已知限制

- **必须解压到纯英文路径**（如 `D:\GameOcrVocab`）：Piper 语音引擎的 espeak 音素层
  不支持含中文/非 ASCII 的目录路径，放在中文目录会导致点发音时卡死或闪退。

- **独占全屏**：个别真·独占全屏(DirectX FSE)或带反作弊的游戏会拦截桌面捕获（黑帧/无帧），
  把游戏显示模式切为 **无边框窗口(Borderless/Windowed Fullscreen)** 即可。
- 区域选择只覆盖主显示器。
- OCR 针对清晰文本优化；花哨艺术字/半透明底可能漏识别，可适当调低 `CHANGE_RATIO` 多触发几次。

## 测试

```bash
.venv/Scripts/python -m game_ocr_vocab.dictionary   # 词典查询自测
.venv/Scripts/python -m game_ocr_vocab.capture --region 100,100,900,500 --seconds 8
.venv/Scripts/python -m game_ocr_vocab.ocr_worker   # 对 data/debug/test_card.png 跑 OCR 管线
.venv/Scripts/python scripts/e2e_test.py            # 端到端(捕获->OCR->增量去重)
```
