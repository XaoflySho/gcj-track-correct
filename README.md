# GCJ 轨迹纠偏

检测轨迹导出 CSV 中驾车段混入的 **GCJ-02（火星坐标）** 点，转回 **WGS-84**。日常轨迹与干净驾车段不改。两种导出共用一套判定；表头只决定读入列名，以及人生点点是否再删侧向野点。

- **网页（推荐）**：<https://xaoflysho.github.io/gcj-track-correct/> — 本地选 CSV → 纠偏 → 下载，文件不离开浏览器
- **一生足迹 CLI**：`correct_tracks.py`（列含 `dataTime`）
- **人生点点 / DoL**：`correct_dol.py`（列含 `timestamp`）

## 网页

选 CSV，点「开始纠偏」，再点「下载结果」，得到 `*_corrected.csv` 与 `*_report.md`。一生足迹默认去掉转换后几乎重合的点；人生点点默认不去近重，可删侧向野点。

同页用 OpenStreetMap（WGS-84）对比原始/纠偏轨迹：默认整份文件，超过 31 天则从开头截取 31 天。可点轨迹或空心删除点，用底部工具改点、删除或恢复。

本地预览（不要用 `file://` 直接打开）：

```bash
cd docs
python3 -m http.server 8000
```

浏览器打开 <http://127.0.0.1:8000/>。

## 命令行

需要虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

之后每次先 `source .venv/bin/activate`。

```bash
python correct_tracks.py --input 2026.01.01-2026.12.31.csv --output-dir output/
python correct_dol.py --input DoL_261017_7052pt.csv --output-dir output/
```

输出（不覆盖原文件）：

- `output/<原文件名>_corrected.csv`
- `output/<原文件名>_report.md` — 行程表；有转换块、删除点或残留警告时再追加

`--no-dedupe` 可保留转换后几乎重合的点。`qa_tracks.py` 与地图预览同时支持 `dataTime` 和 `timestamp`。

## 自动 QA

对比原始与纠偏结果：日常段是否被误改、常驻点（家/公司，自动发现，可搬家多址）是否外漂、路径是否变差。残留的模糊跳变只警告，不导致失败。

```bash
python qa_tracks.py \
  --original 2026.01.01-2026.12.31.csv \
  --corrected output/2026.01.01-2026.12.31_corrected.csv \
  --output-dir output/
```

输出 `output/<stem>_qa_report.md`。通过 → exit `0`，失败 → exit `1`。可选 `--home lon,lat` 追加锚点，`--no-auto-home` 关闭自动发现。

## 地图

网页纠偏后即可同页预览。也可打开 [`track_viewer.html`](track_viewer.html)，选原始和/或纠偏 CSV，填起止日期（跨度不超过 31 天）。灰色=原始，蓝色=纠偏；橙色为改动点，空心为删除点。

**请勿用高德/腾讯网页直接贴 WGS 点**（其底图是 GCJ，会整轨假偏移）。底图需能访问 OSM 与 Leaflet CDN。跨度太大时建议按天查看。

按时间窗导出静态 HTML：

```bash
python view_tracks.py \
  --original 2025.01.01-2025.12.31.csv \
  --corrected output/2025.01.01-2025.12.31_corrected.csv \
  --from "2025-01-04 10:50" --to "2025-01-04 11:20" \
  --out output/preview_20250104.html
```

也可用 `--day 2025-01-04`。

## 说明

主体按 **WGS-84** 处理，只把判定为 GCJ 的点做 `gcj02_to_wgs84`。转换用 [`coordTransform`](https://pypi.org/project/coordtransform/)（按点计算，非固定偏移）。

对比 Python / JS 纠偏结果（开发用）：

```bash
python scripts/compare_parity.py \
  --python output/foo_corrected.csv \
  --js output/foo_js_corrected.csv
```
