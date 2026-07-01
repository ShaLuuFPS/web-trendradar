# 设计规范 · Design System

> **风格定位：深色编辑叙事风（Editorial Data Journalism × Dark Mode）**
>
> 灵感来源：Cape Town Dam Levels、Technology Radar 2017、Financial Dashboard
>
> 核心理念：让数据读起来像一篇有态度的热点报道，而非冰冷的监控大屏。

---

## 1. 配色 · Color Palette

### 1.1 主色与强调色

| 角色 | 色值 | 用途 |
|------|------|------|
| **Primary Gold** | `#D4A056` | 主按钮边框、重点标注、高亮数字、VERDICT 标签 |
| **Accent Cyan** | `#4ECDC4` | 正面情绪、数据系列 B、趋势线、辅助强调 |

### 1.2 背景层级

| 层级 | 色值 | 用途 |
|------|------|------|
| **Page BG** | `#0F1119` | 页面底色（深蓝灰） |
| **Card BG** | `#13161F` | 卡片/面板底色 |
| **Glass BG** | `rgba(19, 22, 31, 0.7)` | 玻璃拟态卡片（配合 `backdrop-filter: blur(12px)`） |
| **Elevated** | `#1A1D28` | 悬浮/激活态更高层级 |

### 1.3 文字颜色

| 角色 | 色值 | 用途 |
|------|------|------|
| **Text Primary** | `#E2E8F0` | 标题、核心数据 |
| **Text Secondary** | `#94A3B8` | 正文、辅助信息 |
| **Text Muted** | `#64748B` | 水印、禁用态、占位符 |

### 1.4 语义颜色

| 语义 | 色值 | 用途 |
|------|------|------|
| **Positive** | `#4ECDC4` | 正面情绪、上升趋势 |
| **Neutral** | `#94A3B8` | 中性情绪、持平 |
| **Negative** | `#E74C3C` | 负面情绪、下降趋势（降低饱和度使用，避免刺眼） |

### 1.5 边框与分割

| 角色 | 色值 | 用途 |
|------|------|------|
| **Card Border** | `rgba(255, 255, 255, 0.05)` | 卡片微边框 |
| **Divider** | `rgba(255, 255, 255, 0.06)` | 分割线 |
| **Input Border** | `rgba(255, 255, 255, 0.1)` | 输入框边框 |

---

## 2. 字体 · Typography

### 2.1 字体族

| 角色 | 字体 | 风格 |
|------|------|------|
| **Display / 大标题** | **Playfair Display** (serif) | 衬线体，杂志编辑感，有态度 |
| **Body / UI** | **Inter** (sans-serif) | 无衬线，可读性优先 |

### 2.2 字号层级

| 层级 | 字号 | 字重 | 行高 | 用途 |
|------|------|------|------|------|
| **Hero KPI** | `72px` / `4.5rem` | `700` (Bold) | `0.9` | 首页核心大数字 |
| **H1** | `32–40px` | `700` | `1.1` | 页面主标题（衬线） |
| **H2** | `24–28px` | `600` | `1.2` | 区块标题 |
| **H3** | `18–20px` | `600` | `1.3` | 卡片标题 |
| **Body** | `14px` | `400` | `1.6` | 正文、表格内容 |
| **Caption** | `12px` | `400` | `1.5` | 辅助标注、时间戳、VERDICT 标签 |
| **Small / Label** | `11px` | `500` | `1.4` | 分类标签、表头、UPPERCASE 导航 |

### 2.3 数字风格

- 大数字使用 **渐变发光**：`linear-gradient(to bottom, #FFFFFF, #94A3B8)` 做文字渐变（`background-clip: text`）
- 千分位逗号分隔，增强可读性
- 百分比跟随数字，小两号置于右上

---

## 3. 间距 · Spacing

### 3.1 基准网格

- **基准单位**：`8px`
- 所有内外边距取自 `{4, 8, 12, 16, 24, 32, 48, 64}` 集合

### 3.2 常用间距

| 场景 | 值 | 用途 |
|------|------|------|
| **Section Gap** | `32px` | 页面大模块之间 |
| **Card Gap** | `24px` | 卡片行/列间距 |
| **Card Padding** | `24px` | 卡片内边距 |
| **Element Gap** | `16px` | 卡片内元素间距 |
| **Inline Gap** | `8px` | 行内元素（标签、按钮组） |
| **Tight** | `4px` | 图标与文字、紧密排列 |

### 3.3 留白原则

- **呼吸感优先**：宁少勿挤，单个指标应占据足够空间
- 卡片内部内容不贴边，保持 `24px` 内边距
- 表格行高不低于 `40px`，保证扫码舒适

---

## 4. 组件样式 · Components

### 4.1 卡片 · Card

```
background: rgba(19, 22, 31, 0.7);
backdrop-filter: blur(12px);
border: 1px solid rgba(255, 255, 255, 0.05);
border-radius: 6px;
box-shadow: 0 4px 30px rgba(0, 0, 0, 0.5);
padding: 24px;
```

- 小圆角（4-6px），拒绝大圆角
- 微边框 + 玻璃模糊背景，层次感来源于透明度叠加
- 阴影克制但明确，营造悬浮感

### 4.2 按钮 · Button

#### Primary（主要操作）
```
background: transparent;
border: 1px solid #D4A056;
color: #D4A056;
border-radius: 6px;
padding: 10px 20px;
font-size: 14px;
font-weight: 500;
```
- 轮廓线框风格，金色边框 + 金色文字
- Hover：金色微发光 `box-shadow: 0 0 12px rgba(212, 160, 86, 0.25)`
- **每个视图最多一个 Primary 按钮**

#### Secondary（次要操作）
```
background: rgba(30, 35, 48, 0.9);
border: 1px solid rgba(255, 255, 255, 0.08);
color: #E2E8F0;
border-radius: 6px;
padding: 8px 16px;
font-size: 13px;
```
- 半透明深色填充，低调不抢眼
- Hover：背景提亮

#### Ghost（无边框）
```
background: transparent;
border: none;
color: #94A3B8;
```
- 用于表格内操作、工具栏图标按钮
- Hover：颜色变为 `#E2E8F0`

### 4.3 导航栏 · Navigation

```
background: rgba(15, 17, 25, 0.9);
backdrop-filter: blur(8px);
border-bottom: 1px solid rgba(255, 255, 255, 0.05);
height: 64px;
padding: 0 24px;
```
- **顶部导航**，非侧边栏
- Logo/标题左对齐，操作按钮右对齐
- 导航项使用 `text-transform: uppercase` + `letter-spacing: 0.05em`
- 激活态：金色文字 + 底部 2px 金色下划线

### 4.4 输入框 · Input

```
background: rgba(19, 22, 31, 0.9);
border: 1px solid rgba(255, 255, 255, 0.1);
border-radius: 6px;
color: #E2E8F0;
padding: 10px 14px;
font-size: 14px;
```
- Focus：边框变为 `#D4A056`，微发光

### 4.5 表格 · Table

```
header: transparent bg, 11px, #64748B, uppercase
cell: 14px, #94A3B8, 40px+ row height
border: 仅底部 1px solid rgba(255,255,255,0.04)
hover: row bg rgba(255,255,255,0.02)
```
- 无竖线，极简横线分隔
- 表头小写大写化
- 行 hover 微弱高亮

### 4.6 标签/徽章 · Badge

```
background: rgba(212, 160, 86, 0.1);
border: 1px solid rgba(212, 160, 86, 0.2);
color: #D4A056;
border-radius: 4px;
padding: 2px 8px;
font-size: 11px;
```
- VERDICT 标签使用金色边框 + 金色文字
- 排名徽章：Top 3 金色、Top 10 灰白、其余无标记

### 4.7 图表 · Chart

- **极简无轴线**：弱化/移除传统坐标轴线
- 数据点直接标注数值
- 无网格线或极淡网格线 `rgba(255,255,255,0.04)`
- 图表背景透明，融入深色页面
- 悬停 tooltip 使用毛玻璃半透明背景

### 4.8 离散气泡散点图 · Scatter Bubble Chart

- **用途**：展示 Top 5（今日）或 Top 8（7天）热点在时间窗口内的热度值变化与排名更迭
- **技术**：ECharts 5.5，嵌入 Streamlit 页面 via `st.components.v1.html`
- **X 轴**：时间轴（今日按分钟，7天按天）
- **Y 轴**：热度值 hot_score（连续值，非排名）
- **数据点**：散点（scatter），每次数据抓取产生一个数据点

#### 气泡编码

| 维度 | 编码方式 | 说明 |
|------|---------|------|
| **大小** | 对数映射 8-60px | `symbolSize = 8 + normalized(log10(score)) * 52` |
| **颜色** | 事件 ID | 每个事件一个独特色，10 色调色板循环 |
| **透明度** | 85% | 重叠时自然加深 |

#### 调色板（深色背景优化）

```js
['#FF6B6B', '#4ECDC4', '#FFD93D', '#6C5CE7', '#A8E6CF',
 '#FF8A5C', '#45B7D1', '#F8B500', '#FF477E', '#00D2FF']
```

#### 交互

- **悬停高亮**：hover 事件 A 任意点 → A 所有点发光，其他事件变暗（opacity 0.12）
- **悬停连线**：hover 时间 A → 该事件各点之间出现半透明虚线串联
- **NEW 脉冲**：5 分钟内新出现的数据点外围叠加 `effectScatter` 波纹动效
- **Tooltip**：事件标题 + 排名 + 热度 + 情绪标签 + AI 简评 + 时间

#### 待实现

- 渐隐退场动画（事件掉出榜单时最后一个点淡出），见 `docs/散点图待实现功能.md`

### 4.9 环形图 · Donut Chart

- **用途**：展示情绪分布占比（正面 / 中性 / 负面）
- **技术**：ECharts pie series，与散点图共用同一 HTML 组件
- **样式**：环形（`radius: ['55%', '78%']`），非实心饼
- **中心文字**：总数 + 正面占比（Playfair Display 衬线体）
- **高度**：200px，紧凑模式

#### 配色

| 情绪 | 色值 |
|------|------|
| 😊 正面 | `#4ECDC4` |
| 😐 中性 | `#94A3B8` |
| 😡 负面 | `#E74C3C` |

### 4.10 千万级热度标注 · Mega-hit Badge

- **触发条件**：`hot_score ≥ 10,000,000`
- **数字格式**：`🔥🔥` 前缀 + 金色渐变色数字（`color: #D4A056; font-weight: 700`）
- **行背景**：`rgba(212, 160, 86, 0.06)` 金辉底色
- **左侧竖线**：`border-left: 2px solid #D4A056`

#### 百万级（辅助标注）

- **触发条件**：`1,000,000 ≤ hot_score < 10,000,000`
- **数字格式**：`🔥` 前缀，正常数字颜色

---

## 5. 布局 · Layout

### 5.1 整体结构

```
┌──────────┬──────────────────────────────────┐
│  Sidebar │  Main Content                    │
│          │                                  │
│  🔥      │  Hero Section                    │
│  Trend   │  ┌──────────────────────────┐    │
│  Radar   │  │ 今日/最近7天热点概览      │    │
│          │  │ KPI 数字 + 总评           │    │
│  ⏱ 下次  │  └──────────────────────────┘    │
│  抓取    │                                  │
│          │  Charts (全宽单列)                  │
│  ──────  │  ┌──────────────────────────────┐ │
│  平台 ▼  │  │ 离散气泡散点图 (ECharts 400px) │ │
│  时间 ○  │  │ 数据更新于 14:30（3分钟前）     │ │
│  ──────  │  │ 情绪环形图 (ECharts 200px)     │ │
│  📊 API  │  └──────────────────────────────┘ │
│  用量    │  热点榜单                          │
│  卡片    │  ┌──────────────────────────┐    │
│          │  │ 列表视图 · 加载更多按钮     │    │
│          │  │ 千万级金辉 · AI 情绪标签  │    │
│          │  └──────────────────────────┘    │
│          │                                  │
│          │  Footer — 数据溯源                │
└──────────┴──────────────────────────────────┘
```

- **侧边栏**：平台下拉 + 时间 Radio（今日/最近7天）+ API 用量卡片，全页面跟随选择
- **Hero 区**：热点总数、正面占比、平均热度 KPI +「总评」编辑结论
- **图表区**：左侧排名趋势折线图（Top 5 × 10 点）+ 右侧情绪 Donut 环形图
- **榜单区**：列表视图，每页 12 条，点击按钮加载更多

### 5.2 混合叙事结构

- **上半部（叙事层）**：大标题 + 核心 KPI + VERDICT 结论 → 30 秒读懂"发生了什么"
- **下半部（数据层）**：可交互表格 + 趋势图 → 深入查阅

### 5.3 响应式原则

- 桌面端为主（1200px+）
- KPI 行使用等宽多列
- 图表区 2 列网格
- 表格单列全宽

---

## 6. 情感与情绪 · Tone

### 6.1 设计气质

| 关键词 | 描述 |
|--------|------|
| **编辑感** | 像杂志文章而非 BI 工具 |
| **叙事性** | 数据之间有因果关系，不只是罗列 |
| **克制** | 一屏一个焦点，不堆砌信息 |
| **温度** | 衬线体 + 金色 = 有人味，非冷冰冰 |

### 6.2 禁止事项

- ❌ 禁止高饱和度撞色（如 #FF0000 纯红、#00FF00 纯绿）
- ❌ 禁止大圆角卡片（>8px）
- ❌ 禁止纯白背景
- ❌ 禁止超过一个 Primary 按钮同屏
- ❌ 禁止粗网格线 / 重阴影
- ❌ 禁止 emoji 作为 UI 图标（数据标注中的情感 emoji 除外）
- ❌ 禁止使用 `slate` 灰阶（Tailwind），统一使用 neutral gray

---

## 7. 技术实现 · Implementation

### 7.1 Streamlit 映射

| Design Spec | Streamlit 实现 |
|-------------|---------------|
| 深色背景 `#0F1119` | `.streamlit/config.toml` → `backgroundColor` |
| 金色主色 `#D4A056` | `.streamlit/config.toml` → `primaryColor` |
| 玻璃拟态卡片 | CSS injection via `st.markdown()` |
| Playfair Display | Google Fonts `@import` in custom CSS |
| 自定义组件样式 | CSS attribute selectors `[data-testid="..."]` |
| 极简图表 | Streamlit native charts + CSS override |

### 7.2 CSS 注入顺序

1. `st.set_page_config()` — 必须是第一个 Streamlit 命令
2. `inject_design_css()` — Google Fonts + 全局 CSS
3. 页面内容渲染

---

## 8. 参考 · References

| 参考图 | 借鉴要素 |
|--------|---------|
| `多折线图.png` | 多折线排名趋势、毛玻璃 tooltip、垂直指示线、深色图表背景 |
| `各种柱状图.png` | 编辑式数据叙事、VERDICT 标签、衬线标题、极简坐标轴 |
| `新奇的数据图.png` | 大数字渐变发光、金色强调、漏斗图创意 |
| `非侧边栏参考.png` | 玻璃拟态卡片、深色层次、顶部导航 |
| `侧边栏.png` | 导航项样式、分组标签、微弱分隔 |
| `横柱状图.jpg` | 极简暗黑背景、双色语义、直接标注 |
| `新颖表达方式.jpg` | 四色分区、霓虹发光、Radar/Grid 视图切换 |
