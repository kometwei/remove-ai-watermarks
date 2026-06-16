# 使用指南

## 安装

### 方式一：开发模式（推荐，使用 uv）

```bash
# 在项目根目录执行
uv sync
```

安装后可通过 `uv run remove-ai-watermarks` 从**任意目录**调用命令。

### 方式二：pip 安装

```bash
pip install -e .
```

安装后直接通过 `remove-ai-watermarks` 命令从**任意目录**调用。

### 可选依赖

```bash
# GPU 加速（不可见水印移除需要）
pip install 'remove-ai-watermarks[gpu]'

# LaMa 修复后端（更好的区域擦除效果）
pip install 'remove-ai-watermarks[lama]'

# Web GUI（可视化浏览器界面）
pip install 'remove-ai-watermarks[web]'
```

---

## 基本用法

安装完成后，可以在**任意目录**下运行，只需提供图片的路径即可。

### 自动检测并移除可见水印

```bash
# 输出到图片同目录（默认 <文件名>_clean.<扩展名>）
remove-ai-watermarks visible /path/to/photo.jpg

# 指定输出路径
remove-ai-watermarks visible /path/to/photo.jpg -o /path/to/output/clean.jpg
```

### 指定水印类型

```bash
# 自动识别（默认）
remove-ai-watermarks visible photo.jpg --mark auto

# 指定类型
remove-ai-watermarks visible photo.jpg --mark lenovo
remove-ai-watermarks visible photo.jpg --mark gemini
remove-ai-watermarks visible photo.jpg --mark doubao
remove-ai-watermarks visible photo.jpg --mark jimeng
remove-ai-watermarks visible photo.jpg --mark samsung
```

### 跳过检测强制移除

```bash
# 即使检测不到也强制在默认位置移除
remove-ai-watermarks visible photo.jpg --mark lenovo --no-detect
```

---

## 支持的水印类型

### 可见水印（无需 GPU，即时处理）

| 标记 | 来源 | 位置 | 移除方式 |
|------|------|------|----------|
| `gemini` | Google Gemini / Nano Banana 火花标 | 右下角 | 逆 Alpha 混合 |
| `doubao` | 豆包 "豆包AI生成" | 右下角 | 逆 Alpha 混合 |
| `jimeng` | 即梦 "★ 即梦AI" | 右下角 | 逆 Alpha 混合 |
| `samsung` | Samsung Galaxy AI | 左下角 | 逆 Alpha 混合 |
| `lenovo` | 联想天禧 "AI生成" | 右下角 | 逆 Alpha 混合 |

### 不可见水印（需要 GPU）

| 水印 | 说明 |
|------|------|
| SynthID | Google / OpenAI 不可见像素水印 |
| Stable Signature | Stability AI 隐式签名 |
| TreeRing | 扩散模型指纹水印 |

```bash
# 移除不可见水印（需要 GPU 依赖）
remove-ai-watermarks invisible photo.jpg

# 指定设备和强度
remove-ai-watermarks invisible photo.jpg --device cuda --strength 0.15
```

---

## 常用命令

### 识别图片来源和水印

```bash
remove-ai-watermarks identify photo.jpg

# JSON 格式输出
remove-ai-watermarks identify photo.jpg --json
```

### 完整移除（可见 + 不可见 + 元数据）

```bash
remove-ai-watermarks all photo.jpg -o /output/dir/clean.jpg
```

### 元数据操作

```bash
# 仅检查 AI 元数据
remove-ai-watermarks metadata photo.jpg --check

# 移除 AI 元数据
remove-ai-watermarks metadata photo.jpg --remove

# 移除并保存到指定路径
remove-ai-watermarks metadata photo.jpg --remove -o /output/dir/stripped.jpg
```

### 手动擦除任意区域

```bash
# 擦除指定像素区域（可重复多次）
remove-ai-watermarks erase photo.jpg --region x,y,w,h

# 使用 LaMa 后端（效果更好）
remove-ai-watermarks erase photo.jpg --region 800,500,200,50 --backend lama

# 多个区域
remove-ai-watermarks erase photo.jpg --region 100,200,50,30 --region 800,900,100,40
```

---

## 批量处理

```bash
# 批量处理目录下所有图片
remove-ai-watermarks batch /input/dir/ --mode visible -o /output/dir/

# 批量完整处理
remove-ai-watermarks batch /input/dir/ --mode all -o /output/dir/

# 仅批量移除元数据
remove-ai-watermarks batch /input/dir/ --mode metadata -o /output/dir/
```

`--mode` 选项：
- `visible` — 仅可见水印（默认）
- `invisible` — 仅不可见水印
- `metadata` — 仅元数据
- `all` — 全部

---

## 目录结构示例

```
/my-photos/
├── input/            # 原始图片
│   ├── photo1.jpg
│   ├── photo2.jpg
│   └── photo3.jpg
└── output/           # 处理后输出
    ├── photo1.jpg
    ├── photo2.jpg
    └── photo3.jpg
```

```bash
# 单张处理
remove-ai-watermarks visible /my-photos/input/photo1.jpg -o /my-photos/output/photo1.jpg

# 批量处理
remove-ai-watermarks batch /my-photos/input/ --mode visible -o /my-photos/output/
```

---

## 常见问题

### 检测不到水印？

1. 确认图片来自对应平台（水印可能已被裁剪或压缩掉）
2. 使用 `--no-detect` 强制移除：`remove-ai-watermarks visible photo.jpg --mark lenovo --no-detect`
3. 先用 `identify` 命令检查图片来源

### 移除后有残影？

- 确保使用最新版本的 alpha 模板
- 尝试 `--no-inpaint` 关闭修复，或调整 `--inpaint-strength`
- 对于 JPEG 压缩严重的图片，效果可能略差

### 不可见水印移除失败？

- 需要安装 GPU 依赖：`pip install 'remove-ai-watermarks[gpu]'`
- 需要 CUDA/MPS/XPU 兼容的 GPU
- 或使用 [raiw.cc](https://raiw.cc) 云服务

---

## Web GUI（可视化操作界面）

启动本地服务器，在浏览器中进行可视化水印移除操作。

### 安装 Web GUI 依赖

```bash
pip install 'remove-ai-watermarks[web]'
```

### 启动服务器

```bash
remove-ai-watermarks serve
```

启动后会自动打开浏览器访问 `http://127.0.0.1:8000`。

```bash
# 自定义端口
remove-ai-watermarks serve --port 9000

# 不自动打开浏览器
remove-ai-watermarks serve --no-open-browser

# 允许局域网访问
remove-ai-watermarks serve --host 0.0.0.0
```

### 功能说明

- **拖拽上传**：将图片拖拽到上传区，或点击选择文件（支持批量）
- **水印类型选择**：自动识别或手动指定水印类型
- **Before/After 对比**：滑动对比处理前后效果，长按空格闪现原图
- **手动框选**：切换到框选工具，在图片上画框指定水印区域
- **智能预检测**：切换到框选模式时，后端自动检测水印位置并预画虚线框
- **自适应缩放**：图片自动适应窗口大小，支持滚轮缩放
- **批量下载**：所有图片处理完成后，可一键打包下载全部结果

### 操作流程

1. 上传图片（拖拽或点击）
2. 选择水印类型（默认自动识别）
3. 点击「开始处理」
4. 查看 Before/After 对比效果
5. 如需微调，切换到框选工具手动指定区域后重新处理
6. 下载结果
