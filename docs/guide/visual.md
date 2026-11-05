# 图像判定

截图和基准图比对。

## 图像判定

```shell
pip install intellipandora[visual]
```

```python
from ipandora.core.assertion import assert_all
from ipandora.core.assertion import that

def test_checkout_looks_right(page):
    page.goto('/checkout')
    assert_all(
        that(page.screenshot(), '结算页').matches_golden('checkout', mask=[(0, 0, 200, 40)]),
        that(page.locator('#price').screenshot(), '价格区').matches_golden('price'),
    )
```

截图可以是 PNG 字节、文件路径或 PIL 图片，所以 Web 以外的截图同样能用。

**基准图**放在用例旁边的 `__goldens__/<名字>-<浏览器>-<平台>.png`，和用例一起提交。同一个页面在 macOS 和 Linux 上渲染不一样，所以按平台分开存放。**请在 CI 运行的环境里生成基准图**，本地生成的基准图到了 CI 上会失败。

```shell
ipandora run tests --update-baseline     # 写入基准图，同时更新判定基线
```

- **没有基准图**：判定失败，提示用 `--update-baseline` 生成。不会自动生成一张再判为通过。
- **失败时**：报告里并排展示基准图、实际截图、差异图，差异图上用红框标出变化的位置。
- **换图会被拦下**：基准图的内容哈希写在判定里，比如 `结算页 matches golden 'checkout' 3fa9…`。有人重新录制基准图，把回归"修绿"，`--fail-on-weakened` 会把它当作"判定改变"拦下。放宽容差、改成更宽松的模式、加遮罩，同样会被识别。

**它能看见什么、看不见什么**（在 Chromium 截图上实测）：

| 变化 | 不同的像素 | 默认设置下 |
|---|---|---|
| 按钮换颜色 | 约 900–13000 | 失败，差异图标出位置 |
| 同一页面再渲染一次 | 0 | 通过 |
| 抗锯齿差异、轻微色差 | 151–290，都是一两像素宽的边缘 | 通过 |
| 一段文字平移 0.4px | 本机 0；GitHub runner 上 18（0.0075%），中文笔画密，3×3 过滤后仍有小块 | **取决于机器**；`tolerance=0.001` 可吸收，按钮换色（0.39%）仍会失败 |
| 金额 100.50 → 100.60 | **7** | 通过（看不出来） |

最后一行很关键：文字变化在像素上几乎看不出来，pixelmatch 会把字形边缘当作抗锯齿。所以**图像判定只管"长得对不对"**，比如颜色、色块、图标、布局；**文字请用 `expect(locator).to_have_text(...)` 或 `that()` 判断**。

参数：

- `mask=[(x, y, 宽, 高)]`：忽略会变的区域，比如时钟、头像、广告。Web 截图也可以直接用 Playwright 自带的 `page.screenshot(mask=[locator])`。
- `noise='edges'`（默认）：只有成块（至少 3×3）的差异才算数，抗锯齿和子像素偏移留下的细线不算。`noise='strict'`：所有不同的像素都算，适合要求像素级一致的图标，代价是渲染上的细微差别也会报错。
- `tolerance`：允许差异像素占整张图的比例，默认 0。整页截图里有大段文字时，建议 `tolerance=0.001`（0.1%），可以吸收不同机器上字形栅格化的细微差别；单个元素的截图保持 0。
- `threshold`：单个像素的色差阈值（0–1），默认 0.1。

**已知限制**：纯粹 1 像素的位置平移，pixelmatch 会当作抗锯齿，不计入差异。
