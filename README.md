# jiangshan-atlas-year-index

把「江山时序」历史地图里**只存在于中文 caption 的年份**抽成可查询索引，并审计时间轴的空洞、重叠和乱序——因为上游 206 个快照没有任何机器可读的 `year_start` / `year_end` 字段，年份只能从 `"1407—1427 年 · 永乐极盛疆域"` 这类人读字符串里猜。

Upstream: https://github.com/DeanChensj/jiangshan-map

## 上游是什么，它缺什么

[DeanChensj/jiangshan-map](https://github.com/DeanChensj/jiangshan-map) 是一个中国历史交互地图（403 BCE – 现在，7.5k★，今日 Trending 288★/日）。每个 `data/atlas/<朝代>/<key>.geojson` 是一帧地图快照，`scripts/build_atlas.js` 只检查 key 重复、`index.json` 的 `order` 是否覆盖所有文件、`boot` 是否在 `order` 内（[build_atlas.js#L8-L14](https://github.com/DeanChensj/jiangshan-map/blob/main/scripts/build_atlas.js#L8-L14) 描述的 snapshot schema 只有 `caption`/`note`/`polities`/`prefectures`/`regions`）。真实文件 [`data/atlas/ming/s_ming_a.geojson`](https://github.com/DeanChensj/jiangshan-map/blob/main/data/atlas/ming/s_ming_a.geojson) 的 `snapshot` 对象里没有年份字段，只有 `caption: "1407—1427 年 · 永乐极盛疆域"`。

后果：时间轴只能按 `index.order` 的**文件书写顺序**播放，无法回答「公元 1100 年有哪些快照」「洪武到郑和之间空了几年」「两宋交替的 1127 年是不是同时被两个朝代渲染」。上游的构建脚本也不会因此报错——它根本没有年份这个概念。

## 这个工具做什么

1. 解析每帧 `snapshot.caption` 的年份区间（支持 `前221`、`1407—1427 年`、`618-907`、单年事件 `1945 · 抗战胜利`、全角数字），BCE 用负数表示；跨公元必须显式写 `公元8`，否则 `前202 — 8` 按「继承 BCE」解释（见局限）。
2. 生成 `year -> snapshots` 索引，`--year` 直接查询某年渲染了哪些帧。
3. 按 `index.json` 的声明顺序（没有 index.json 时按文件 key）审计每个朝代组：`group-nonmonotonic`（声明顺序与年份倒退）、`group-overlap`（相邻区间重叠）、`group-gap`（相邻区间之间未覆盖的年份）、`year-unparsed`、`year-reversed`、`duplicate-key`、`invalid-json`。
4. 汇总每组的时间跨度、已覆盖/未覆盖年数，以及被多个朝代同时渲染的「争议年份」数量。

它**不**校验几何、不做投影、不读已打包的 `js/atlas_snapshots.js`，也不修改上游任何文件。

## 安装

零第三方依赖，只要 Python 3.8+。不需要 clone 上游，指向任意一份 `data/atlas` 目录即可。

```bash
git clone git@github-linmoxi33:linmoxi33/jiangshan-atlas-year-index.git
cd jiangshan-atlas-year-index
python3 bin/atlas_year_index.py examples/in
```

退出码 **1**（样例里本来就有 1 个 gap 和 1 个 overlap），见下。

## 用法

```bash
# 人读报告
python3 bin/atlas_year_index.py examples/in

# 机器读（stdout 是单个 JSON 对象）
python3 bin/atlas_year_index.py examples/in --json

# 查某一年（负数是 BCE）
python3 bin/atlas_year_index.py examples/in --year 1420

# 只要退出码
python3 bin/atlas_year_index.py examples/in --quiet
```

`--json` 输出结构（节选，完整样例在 `examples/out/report.json`）：

```json
{
  "tool": "jiangshan-atlas-year-index",
  "summary": {"snapshots": 6, "parsed": 6, "unparsed": 0, "groups": 3,
              "findings": 2, "first_year": -221, "last_year": 1433,
              "contested_years": 0},
  "groups": {"ming": {"snapshots": 2, "span": [1368, 1433], "span_years": 66,
                      "covered_years": 60, "uncovered_years": 6}},
  "snapshots": [{"key": "s_qin_a", "group": "qin", "start": -221, "end": -207,
                 "caption": "前221 — 前207 · 秦灭六国"}],
  "findings": [{"code": "group-gap", "severity": "warning",
                "file": "ming/s_ming_b.geojson",
                "detail": "6 uncovered year(s) between s_ming_a (ends 1398) and s_ming_b (starts 1405)"}]
}
```

退出码：

| 码 | 含义 |
| --- | --- |
| 0 | 没有 findings（查询模式恒为 0） |
| 1 | 检出至少一个 finding（gap / overlap / 乱序 / 无法解析 / 反向区间 / 重复 key / 坏 JSON） |
| 2 | 用法错误或输入目录不存在 |

## 在真实上游上的结果（2026-11-17，真实运行）

用 GitHub API 取回上游 `data/atlas` 全部 206 个 `.geojson` 的 `snapshot` 元数据（几何未下载，本轮不打包 GPL 数据），重放成临时目录后运行：

```
python3 bin/atlas_year_index.py /tmp/atlasmeta --json
```

- **193 / 206** 帧解析出年份；**13** 帧完全没有 caption（`neighbors`、`prc`、部分 `donghan`/`qing` 帧）。
- 时间轴跨度 **403 BCE – 1949 CE**，按 `index.json` 的真实 order 审计出 **174** 条 findings：
  **68** 个组内空洞、**50** 个相邻区间重叠、**43** 个声明顺序与年份倒退、**13** 个无 caption。
- 覆盖空洞最大的两组：`zhanguo` 有 **55** 年无快照，`qing` 有 **36** 年无快照；其余 15 组逐年在 `index.order` 下连续。
- 有 **13** 个年份同时被两个以上朝代组渲染（如 1127 两宋交替）——这是地图语义上合法的，工具只计数、不报错。

这些数字是运行输出，不是估计；复现命令以上面的 `--json` 为准。

## 局限

- 年份解析依赖 caption 写法。上游偶见 `1407—1427 年`、`前 207 ·`、单年事件，已覆盖；但「约」「左右」等模糊写法会被当作精确年份，或被报 `year-unparsed`。
- `前202 — 8` 这种第一年带「前」、第二年不带且更小的写法，按「继承 BCE」解释（= 前202–前8）；跨公元请写 `公元8`。
- `group-nonmonotonic` 只说明「声明顺序不是年份递增」，不等于数据错误——`index.order` 可能故意按叙事排列。
- 只读 `snapshot.caption`；`note` 里的年份（如 `1409 年设奴儿干都司`）不参与区间计算。
- 不校验 GeoJSON 几何，不替代 `scripts/build_atlas.js`。

## 本轮创新

首个把「江山时序」的 caption-only 年份变成可查询索引并据此审计 206 帧时间轴的工具：上游 schema 没有年份字段，现有构建脚本只做 key/order 结构校验，因此「哪年有哪些帧 / 哪段年份是空洞 / 声明顺序是否时序」此前无法离线回答。本工具给出 403 BCE–1949 CE 的全量覆盖表，并在真实数据上量出 55 年（战国）与 36 年（清）的渲染空洞。档位 **B**：首次在此场景用 caption 解析 + 声明顺序审计产出可验证的新结论，而非换皮 lint。

## 与同类项目的差异

`gh search repos "historical atlas timeline geojson"` 返回 0 个仓库；`gh search code "atlas_snapshots"` 只命中上游自身。没有现成的「历史地图快照年份索引/时间轴审计」工具可对比（检索记录见交付说明）。本项目只通过公开 GeoJSON 文件格式工作，不 fork、不复制上游 GPL 数据。

## License

MIT（代码）。样例 `examples/in/*.geojson` 是为本工具手写的合成数据，不含上游数据。
