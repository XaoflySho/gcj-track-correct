# GCJ 轨迹纠偏

检测轨迹导出 CSV 中驾车段混入的 **GCJ-02（火星坐标）** 点，并用公开库转回 **WGS-84**。日常轨迹与干净驾车段不修改。

- **网页（推荐）**：打开静态站，本地选 CSV → 纠偏 → 下载，文件不离开浏览器
- **一生足迹 CLI**：`correct_tracks.py`（列含 `dataTime`）
- **人生点点 / DoL**：`correct_dol.py`（列含 `timestamp`）

两种导出共用一套判定：驾车段上的 WGS/GCJ 切换检测，加上「距离已等于速度×时间则不标成换坐标系」的否决。表头只决定读入列名、报告文案，以及人生点点是否再删侧向野点。

## 网页纠偏

站点：<https://xaoflysho.github.io/gcj-track-correct/>

在页面上选择 CSV，点「开始纠偏」，再点「下载结果」得到 zip（内含 `*_corrected.csv` 与 `*_report.md`）。按表头自动识别：

- **一生足迹**：含 `dataTime`，默认去掉转换后几乎重合的点
- **人生点点 / DoL**：含 `timestamp`，同一套判定；默认不去近重，可删侧向野点

可在 OpenStreetMap（WGS-84）上对比原始/纠偏轨迹：默认显示整份文件，超过 31 天则从开头截取 31 天。点击轨迹或空心删除点，可用底部工具手动改点、删除或恢复。

**文件仅在本机处理，不会上传到任何服务器。**

本地预览（ES modules 不能用 `file://` 直接打开）：

```bash
cd docs
python3 -m http.server 8000
```

浏览器打开 <http://127.0.0.1:8000/>。

网页版不做完整 QA 硬门禁；纠偏后仍可用下面的 `qa_tracks.py` 做回归。对比 Python / JS 输出：

```bash
python scripts/compare_parity.py \
  --python output/foo_corrected.csv \
  --js output/foo_js_corrected.csv
```

## 环境（必须使用虚拟环境）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

之后每次运行前先激活：

```bash
source .venv/bin/activate
```

## 运行

```bash
python correct_tracks.py \
  --input 2026.01.01-2026.12.31.csv \
  --output-dir output/
```

输出：

- `output/<原文件名>_corrected.csv` — 纠偏后的轨迹（不覆盖原文件）
- `output/<原文件名>_report.md` — 修改摘要

可选：`--no-dedupe` 保留转换后与邻点几乎重合的点。

## 人生点点 / DoL 导出

DoL CSV 列名为 `timestamp,longitude,latitude,...`（不是 `dataTime`）。判定与一生足迹相同，入口按列名选择：

```bash
python correct_dol.py \
  --input DoL_261017_7052pt.csv \
  --output-dir output/
```

输出：

- `output/<原文件名>_corrected.csv` — 保留全部原列，仅改判定为 GCJ 的经纬度；可删除侧向野点
- `output/<原文件名>_report.md` — 行程摘要、GCJ 块起止、转换/删除点数、残留警告

`qa_tracks.py` 与地图预览（网页或 `view_tracks.py`）同时支持 `timestamp` 与 `dataTime`。

## 自动 QA（推荐纠偏后跑）

对比原始与纠偏结果，检查误伤、路径回退，并跑固定回归日；**常驻点（家/公司）从数据自动发现，支持搬家多址**，无需写死家坐标。

```bash
python qa_tracks.py \
  --original 2026.01.01-2026.12.31.csv \
  --corrected output/2026.01.01-2026.12.31_corrected.csv \
  --output-dir output/
```

可选：`--home lon,lat` 可重复追加人工锚点；`--no-auto-home` 关闭自动发现。

输出：`output/<stem>_qa_report.md`（中文）。全部硬检查通过 → exit `0`；失败 → exit `1`。残留的模糊 GCJ 跳变以 **警告** 列出，不导致失败（硬门禁为日常零改、常驻不外漂、位移形态、路径质量与回归用例）。

## 地图预览（目视验偏）

纠偏完成后可直接在网页同页预览（默认整份文件，超过 31 天则截取前 31 天）。也可继续用仓库根目录的 [`track_viewer.html`](track_viewer.html) 对比两份已有 CSV：原始 / 纠偏 **任选其一或都选**；再填起止 **日期**（时分可选；不填时分则整天），跨度不超过 31 天，点「显示」。灰色=原始，蓝色=纠偏；橙色为改动点，空心为删除点。底图为 **OpenStreetMap（WGS-84）**。

注意：

- 浏览器不能自动读磁盘路径，需手动选文件；选一次后换时间段不必重选
- **请勿用高德/腾讯网页直接贴 WGS 点**（其底图是 GCJ，会整轨假偏移）
- 打开页面时需能访问 OSM 瓦片与 Leaflet CDN
- 时间跨度过大时点数可能很多，浏览器会变卡，建议按天或更短窗口查看

备选：脚本按时间窗导出静态 HTML

```bash
python view_tracks.py \
  --original 2025.01.01-2025.12.31.csv \
  --corrected output/2025.01.01-2025.12.31_corrected.csv \
  --from "2025-01-04 10:50" --to "2025-01-04 11:20" \
  --out output/preview_20250104.html
```

也可用 `--day 2025-01-04`。点数过多时浏览器会变卡，可缩小时间范围。

## 其它年份

只要 CSV 列名与一生足迹导出一致（含 `dataTime,longitude,latitude,speed,...`），即可：

```bash
python correct_tracks.py --input 2023.01.01-2023.12.31.csv --output-dir output/
python qa_tracks.py \
  --original 2023.01.01-2023.12.31.csv \
  --corrected output/2023.01.01-2023.12.31_corrected.csv \
  --output-dir output/
```

## 说明

- 主体坐标系按 **WGS-84** 处理；仅将判定为 GCJ 的点做 `gcj02_to_wgs84`
- 转换使用 PyPI 包 [`coordTransform`](https://pypi.org/project/coordtransform/)（按点计算，非固定偏移）
- 检测覆盖：逐点交错、短时整段切换，以及高置信度的长间歇切换（停车后再以另一数据源恢复）
- 相邻点在 40 秒内且原始距离已等于 `速度×时间`（约 40 m 以内）时，不把这一步当成换坐标系
- 人生点点在共用判定之后，会把相邻 GCJ 块之间漏标的点按速度×时间补上，并删除侧向野点
- 标注偏保守：
  - 成对 `W→G`/`G→W` 仅在短且内部连续的闭区间填充；两端尖峰、中间仍是 WGS 的长跨度（如 1/16）不会整段误转
  - 不会因段首一次 `G→W` 就把从起点起的整段都标成 GCJ（如 6/12）
  - 每个 GCJ 子段整段保留或整段丢弃；并检查边界连续性与路径是否改善
