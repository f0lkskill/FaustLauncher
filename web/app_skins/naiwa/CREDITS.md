# 素材来源与许可

## 角色形象（奶蛙 / 变异奶龙）

奶蛙不是一个"有作者的角色"，而是 2024 年秋天从儿童向 IP「奶龙」衍生出来的
互联网迷因 / 集体创作形象（与"美团老鼠""牛来"并称黄色三幻神）：

- 官方原型「奶龙」是**大头、短粗的幼龙**；网络上流传的奶蛙则是 AI 生成的
  **小头、大肚、四肢纤细扭曲**的黄色胖青蛙，是"可爱的解体"式故障艺术变体。
- 标志动作是**捧腹大笑**，标志音是**"齁齁齁"**（直播连麦笑声变声后成了符号）。
- 因此奶蛙**没有单一作者可以署名**，本皮肤也不自绘角色，全部使用社区整理的
  官方素材仓库。

## 图片素材

- 仓库：<https://github.com/Nailong-Studio/wallpaper>（"奶蛙艺术圣殿" 素材仓库）
- 许可：**MIT License**
- 本皮肤用到的文件与去向：

  | 仓库路径 | 本皮肤用途 |
  | --- | --- |
  | `4k/奶蛙-4K-捶头大笑-01.jpg` | `assets/launcher/background/naiwa_1.jpg` |
  | `4k/奶蛙-4K-抱头震惊-02.jpg` | `assets/launcher/background/naiwa_2.jpg` |
  | `4k/奶蛙-4K-叉腰指点-03.jpg` | `assets/launcher/background/naiwa_3.jpg` |
  | `4k/奶蛙-4K-托腮沉思-04.jpg` | `assets/launcher/background/naiwa_4.jpg` |
  | `4k/奶蛙-4K-张臂平衡-05.jpg` | `assets/launcher/background/naiwa_5.jpg` + `profile.jpg` |
  | `emotes/奶蛙-姿态-露肚.png`（透明底） | `assets/web/icon/icon.png` |

- 原图已随皮肤放在 `source/`（长边缩到 2560，控制体积），重新拉取：
  在本目录执行 `python tools/make_assets.py fetch`（需要能访问 GitHub）。

## 本皮肤生成的图片

`assets/launcher/background/naiwa_1..5.jpg`、`profile.jpg`、`assets/web/icon/icon.png`
全部由 `tools/make_assets.py`（仅用 PIL）从上述原图合成：

- **背景**：官方 4K 壁纸接近正方形，直接裁 16:9 只能留下 56% 的高度、头必然被切掉。
  所以改为把原图按**高度**缩满 1080（角色完整不裁切）居中放置，两侧空白用**边缘
  像素向外复制**填满 —— 官方是浅灰白影棚底，边缘列本身就是均匀底色，复制出去与
  原图浑然一体。**没有添加任何文字或水印**，画面内容就是官方原图本身。
- **图标**：取透明底姿态图，按 alpha 外框裁切、留 8% 边距后缩进 256×256。
- **卡片图**：同源壁纸按 700×977 居中裁切。

重新生成：在本目录执行 `python tools/make_assets.py`。

## 配色

橙黄全部取自奶蛙本体：奶蛙黄 `#F5C542`、主橙 `#F5A524`、深橙 `#E07B00`；
底色用奶油白 `#FFF6E6` / 蛋奶 `#FFEFD8`，正文焦糖棕 `#4A2F10`。
