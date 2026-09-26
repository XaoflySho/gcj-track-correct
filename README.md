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

## 其它年份

只要 CSV 列名与一生足迹导出一致（含 `dataTime,longitude,latitude,speed,...`），即可：

```bash
python correct_tracks.py --input 2023.01.01-2023.12.31.csv --output-dir output/
```

## 说明

- 主体坐标系按 **WGS-84** 处理；仅将判定为 GCJ 的点做 `gcj02_to_wgs84`
- 转换使用 PyPI 包 [`coordTransform`](https://pypi.org/project/coordtransform/)（按点计算，非固定偏移）
- 检测覆盖：逐点交错、短时整段切换，以及高置信度的长间歇切换（停车后再以另一数据源恢复）
- 标注偏保守：
  - 成对 `W→G`/`G→W` 仅在短且内部连续的闭区间填充；两端尖峰、中间仍是 WGS 的长跨度（如 1/16）不会整段误转
  - 不会因段首一次 `G→W` 就把从起点起的整段都标成 GCJ（如 6/12）
  - 每个 GCJ 子段整段保留或整段丢弃；并检查边界连续性与路径是否改善
