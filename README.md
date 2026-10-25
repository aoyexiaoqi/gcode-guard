# gcode-guard

CNC G 代码（.nc / .gcode）静态检查工具：逐行解析程序，跟踪模态状态（单位、距离模式、进给、主轴、当前位置），按一组带稳定编号的规则检查常见编程错误——切削前没给进给、主轴没开就切削、超行程、圆弧半径不一致、快移高度过低等。纯 Python 标准库实现，无第三方依赖。与 [cadguard](https://github.com/aoyexiaoqi/cadguard)（DXF 图纸检查）是同系列的姊妹工具。

## 安装

```bash
pip install .            # 从源码安装
pip install -e .[test]    # 开发模式（含 pytest）
```

要求 Python ≥ 3.9。

## 使用

命令行：

```bash
gcode-guard program.nc                          # 文本输出
gcode-guard program.nc --config limits.json     # 带行程等配置
gcode-guard program.nc --format json            # JSON 输出
python -m gcode_guard program.nc                # 等价写法
```

退出码：`0` = 无 error（可以有 warning）；`1` = 至少一条 error；`2` = 文件/参数错误。

Python API：

```python
from gcode_guard import check_text, check_file, Config

findings = check_text(source_text)                       # list[Finding]
findings = check_file("program.nc", Config(x_max=300))   # 带行程限制

for f in findings:
    print(f.line, f.rule, f.severity, f.message)
```

每条 Finding 包含：规则编号（GG001–GG008）、严重级别（`error` / `warning`）、行号（从 1 开始）、说明文本。

## 配置文件

`--config` 接受一个 JSON 文件，全部字段可选：

```json
{
  "x_min": -100, "x_max": 100,
  "y_min": -100, "y_max": 100,
  "z_min": -50,  "z_max": 50,
  "safe_z": 5.0,
  "arc_tolerance": 0.05
}
```

- 行程上下限只对写进配置的轴生效（GG005）；不写就不查该轴。
- `safe_z`：快移安全高度（GG008），默认 `5.0`（程序自身单位）。
- `arc_tolerance`：圆弧半径允许偏差（GG006），默认 `0.05`。
- 出现未知字段会直接报错，防止把 `x_mx` 之类的拼写错误静默吞掉。

## 规则一览

| 编号 | 级别 | 含义 |
|---|---|---|
| GG001 | error | 切削移动（G1/G2/G3）之前从未设置过进给速度 F |
| GG002 | error | 主轴未启动（无 M3/M4，或 M5 之后）时执行切削移动 |
| GG003 | warning | 程序结束时没有 M2/M30 |
| GG004 | warning | 程序结束时主轴仍在转（没有 M5） |
| GG005 | error | 移动目标超出配置的机床行程范围 |
| GG006 | error | 圆弧（G2/G3）起点半径与终点半径不一致（超出容差） |
| GG007 | warning | 第一次移动之前没有声明单位（G20/G21） |
| GG008 | warning | Z 低于安全高度时执行带 X/Y 的快移（G0） |

### GG001 切削前未设进给

触发：

```gcode
M3 S1000
G1 X10        <- 从未出现过 F
```

通过：进给是模态量，设一次即可，后续切削行可省略；写在同一行也算已设置：

```gcode
M3 S1000
G1 X10 F200
G1 X20        <- 沿用 F200，不再报警
```

### GG002 主轴未开就切削

触发：

```gcode
G1 X10 F200   <- 主轴从未启动
```

```gcode
M3 S1000
M5
G1 X10 F200   <- M5 之后主轴已停
```

通过：切削前有有效的 M3/M4；中途停过主轴后，重新 M3 再切削即可。

### GG003 程序没有结束代码

触发：文件到最后一行都没有 M2 或 M30（在最后一行报警）。通过：以 `M30`（或 `M2`）收尾。

### GG004 程序结束时主轴未停

触发：

```gcode
M3 S1000
G1 X10 F200
M30           <- 主轴还开着
```

通过：结束前先 `M5` 再 `M30`。

### GG005 超出行程范围

需要配置，如 `{"x_max": 100}`。触发（绝对模式）：

```gcode
G1 X150 F200  <- X 目标 150 > 100
```

G91 增量模式下按累积位置判定：连续两行 `G1 X60` 后 X=120，同样超限。未在配置中给出的轴不检查；完全不给配置则本规则不生效。通过：所有移动目标都落在配置范围内。

### GG006 圆弧半径不一致

仅检查带圆心偏移（I/J/K）的圆弧：圆心 = 起点 + 偏移，比较起点→圆心与终点→圆心的距离，差值超过 `arc_tolerance`（默认 0.05）报警。触发（当前点在 (20, 0)）：

```gcode
G2 X10 Y5 I-10 J0   <- 圆心 (10,0)：起点半径 10，终点半径 5
```

通过：

```gcode
G2 X10 Y10 I-10 J0  <- 两端半径都是 10
```

按当前平面取轴：G17 用 I/J，G18 用 I/K，G19 用 J/K。用 R 指定半径的圆弧文本里没有显式圆心，**不检查**（见下方语义说明）。

### GG007 未声明单位

触发：第一次移动之前没出现 G20/G21（只在第一次移动处报警一次）：

```gcode
M3 S1000
G1 X10 F200   <- 不知道这是英寸还是毫米
```

通过：程序头先写 `G21`（或 `G20`）。

### GG008 低位快移

近似语义（见下方说明）：一行 G0 同时带 X/Y 移动，且该行执行后 Z 低于 `safe_z`（默认 5.0），报警。触发：

```gcode
G1 Z-1 F200   <- 已下刀到 Z-1
G0 X20 Y20    <- 在 Z-1 高度快移，容易撞料/擦伤表面
```

通过：先抬刀再快移：

```gcode
G0 Z10
G0 X20 Y20
```

只动 Z 的快移（如 `G0 Z-2`）不报警——定位下刀是正常动作。

## 语义与局限（请先读）

- **静态检查，不是仿真**：不执行程序、不考虑刀补（G41/G42）、工件坐标系偏移（G54 等）、子程序调用（M98）和宏变量。机床起始位置假定为原点 (0, 0, 0)，主轴初始为停转、进给未设置。
- **模态处理**：运动代码（G0–G3）、进给 F、距离模式（G90/G91）、平面（G17/G18/G19）均按模态跟踪；一行内的状态字（F、M3、G21 等）在该行移动判定之前生效，与常见控制器的处理一致。
- **注释**：括号注释 `( ... )` 与分号注释 `; ...` 都会在解析前剥离，注释里的代码不生效。
- **GG005** 只判定移动目标点，不做路径插补检查；两点之间穿过限位区但终点在范围内不会报警。
- **GG006** 只支持圆心格式（I/J/K）；R 格式圆弧跳过。螺旋插补时只按当前平面内的两轴计算半径。
- **GG008** 是启发式近似：它不知道工件实际占据的 XY 区域，只能以「带 XY 的快移 + Z 低于安全高度」作为风险近似；夹具/虎钳高度等因素请结合现场情况判断，或通过 `safe_z` 调整阈值。

## 开发

```bash
pip install -e .[test]
pytest
```

## 许可证

MIT

---

# gcode-guard (English)

A static checker for CNC G-code programs (.nc / .gcode). It parses a program
line by line, tracks the modal machine state (units, distance mode, feed
rate, spindle state/speed, current position) and applies a small set of
rules with stable IDs: cutting before a feed rate is set, cutting with the
spindle off, moves outside the configured machine envelope, inconsistent arc
radii, rapids below the safe height, and more. Pure Python standard library,
no third-party dependencies. Sibling of
[cadguard](https://github.com/aoyexiaoqi/cadguard) (DXF drawing checker).

## Install & usage

```bash
pip install .
gcode-guard program.nc [--config limits.json] [--format text|json]
```

Exit codes: `0` = no errors (warnings allowed), `1` = at least one error,
`2` = usage/file error. Python API: `check_text(source)` /
`check_file(path, config)` returning `Finding` objects with `rule`,
`severity`, `line` and `message`.

## Rules

| ID | Severity | Meaning |
|---|---|---|
| GG001 | error | Cutting move (G1/G2/G3) before any feed rate (F) has been set |
| GG002 | error | Cutting move while the spindle is off (no M3/M4, or after M5) |
| GG003 | warning | Program ends without M2/M30 |
| GG004 | warning | Program ends with the spindle still on (no M5) |
| GG005 | error | Move target outside the configured machine envelope |
| GG006 | error | Arc (G2/G3) start/end radius mismatch beyond tolerance |
| GG007 | warning | Units not declared (no G20/G21) before the first move |
| GG008 | warning | Rapid (G0) move in X/Y while Z is below the safe-Z height |

The config JSON accepts optional `x_min/x_max/y_min/y_max/z_min/z_max`
envelope limits (only configured axes are checked), `safe_z` (default 5.0)
and `arc_tolerance` (default 0.05), all in the program's own units.

## Semantics and limitations

This is a static checker, not a simulator: no tool compensation, work
offsets, subprogram calls or macros are evaluated; the machine is assumed to
start at the origin with the spindle off and no feed rate set. Comments
(`( ... )` and `; ...`) are stripped before parsing. GG005 checks move
targets only, not the interpolated path. GG006 covers center-format arcs
(I/J/K) in the active plane; R-format arcs are skipped. GG008 is a heuristic:
it cannot know the part's XY footprint, so any X/Y rapid below `safe_z` is
flagged for review. See the Chinese sections above for a trigger/pass example
of every rule.

## License

MIT
