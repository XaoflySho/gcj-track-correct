# GCJ 轨迹纠偏

检测一生足迹导出 CSV 中驾车轨迹混入的 **GCJ-02（火星坐标）** 点，并用公开库转回 **WGS-84**。日常轨迹与干净驾车段不修改。

## 环境（必须使用虚拟环境）

```bash
cd /Users/shaoxiaofei/Developer/Cursor/correct
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

**推荐：纯网页，无需起服务器。** 用浏览器打开仓库根目录的 [`track_viewer.html`](track_viewer.html)：原始 / 纠偏 CSV **任选其一或都选**；再填起止 **日期**（时分可选；不填时分则整天），跨度不超过 31 天，点「显示」。灰色=原始，蓝色=纠偏；两边都有时显示橙色改动点。底图为 **OpenStreetMap（WGS-84）**。

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

也可用 `--day 2025-01-04`。全年点过多，CLI 与网页都建议按天或更短窗口查看。

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
- 标注偏保守：
  - 成对 `W→G`/`G→W` 仅在短且内部连续的闭区间填充；两端尖峰、中间仍是 WGS 的长跨度（如 1/16）不会整段误转
  - 不会因段首一次 `G→W` 就把从起点起的整段都标成 GCJ（如 6/12）
  - 每个 GCJ 子段整段保留或整段丢弃；并检查边界连续性与路径是否改善
