"""Rich Menu（圖文選單）設定腳本。

三欄式設計，預設收起（selected=False），點底部「選單」可拉出：
  左欄：我的資料 / 修改資料
  中欄：新增寶寶 / 切換寶寶
  右欄（整高）：官方網站（URI 連結）

TODO: 取得網站網址後，更新 _WEBSITE_URI 再執行一次 python rich_menu.py

    python rich_menu.py
"""

import logging
import os

import requests
from linebot.v3.messaging import (
    ApiClient, Configuration, MessagingApi,
    RichMenuRequest, RichMenuSize, RichMenuArea, RichMenuBounds,
    MessageAction, URIAction,
)

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

IMAGE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Static", "img", "rich_menu.png")
WIDTH, HEIGHT = 2500, 843

_COL_W  = 833                  # 左、中欄寬度（833×2 + 834 = 2500）
_COL3_W = WIDTH - _COL_W * 2  # 右欄寬度 = 834
_HALF_H = HEIGHT // 2          # 上半高 = 421
_BOT_H  = HEIGHT - _HALF_H    # 下半高 = 422

# ── TODO: 拿到網站網址後換掉 "https://example.com" 再重新執行 ──────────────
_WEBSITE_URI = "https://example.com"

# ── 顏色 ─────────────────────────────────────────────────────────────────────
_C_PAGE    = (245, 246, 250)   # 頁面底色（淡藍灰）
_C_CELL    = (255, 255, 255)   # 功能格白色背景
_C_DIV     = (218, 220, 232)   # 格線顏色
_C_ICON    = (52,  86,  160)   # 功能格圖示 + 文字（深藍）
_C_ICON_S  = (120, 140, 180)   # 功能格副標文字（淡藍灰）
_C_WEB_BG  = (255, 143, 171)   # 官網格背景（品牌粉紅）
_C_WEB_FG  = (255, 255, 255)   # 官網格圖示 + 文字（白）

# ── 按鈕定義 (label, subtitle, icon_type, x, y, w, h, is_uri) ───────────────
_BUTTONS = [
    ("我的資料", "查看個人資料", "person",   0,          0,       _COL_W,  _HALF_H, False),
    ("修改資料", "更新任意欄位", "edit",     0,          _HALF_H, _COL_W,  _BOT_H,  False),
    ("新增寶寶", "新增第二位起", "add_baby", _COL_W,     0,       _COL_W,  _HALF_H, False),
    ("切換寶寶", "切換孩子頁面", "switch",   _COL_W,     _HALF_H, _COL_W,  _BOT_H,  False),
    ("官方網站", "前往完整服務", "globe",    _COL_W * 2, 0,       _COL3_W, HEIGHT,  True),
]


# ── 字型 ─────────────────────────────────────────────────────────────────────

def _load_font(size: int):
    from PIL import ImageFont
    for fp in [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        try:
            return ImageFont.truetype(fp, size)
        except OSError:
            continue
    return None


# ── 圖示繪製 ─────────────────────────────────────────────────────────────────

def _draw_icon(draw, icon_type: str, cx: int, cy: int, sz: int, color: tuple) -> None:
    """在 (cx, cy) 為中心、sz 為半徑的區域內繪製線稿圖示。"""
    lw = 10   # 固定線寬，比例適合 2500px 尺寸
    r  = sz   # 最大半徑

    if icon_type == "person":
        # 頭部圓形
        hr  = sz * 2 // 5
        hcy = cy - sz * 3 // 5
        draw.ellipse([cx - hr, hcy - hr, cx + hr, hcy + hr], outline=color, width=lw)
        # 肩膀弧線（下半弧 = U 字形）
        bx, by = cx - r, hcy + hr
        draw.arc([bx, by, bx + r * 2, by + r], start=0, end=180, fill=color, width=lw)

    elif icon_type == "edit":
        # 鉛筆：斜線主體
        s = sz * 4 // 5
        draw.line([cx - s, cy + s, cx + s, cy - s], fill=color, width=lw + 2)
        # 筆尖三角（底端小 V）
        draw.line([cx - s, cy + s, cx - s - 12, cy + s + 18], fill=color, width=lw)
        draw.line([cx - s - 12, cy + s + 18, cx - s + 14, cy + s + 10], fill=color, width=lw)
        draw.line([cx - s + 14, cy + s + 10, cx - s, cy + s], fill=color, width=lw)
        # 筆蓋（頂端短橫線）
        angle_offset = sz // 5
        draw.line([cx + s - angle_offset, cy - s - angle_offset,
                   cx + s + angle_offset, cy - s + angle_offset], fill=color, width=lw + 4)

    elif icon_type == "add_baby":
        # 寶寶頭部
        hr  = sz * 2 // 5
        hcy = cy - sz // 2
        draw.ellipse([cx - hr, hcy - hr, cx + hr, hcy + hr], outline=color, width=lw)
        # 加號（新增意象）
        py = cy + sz // 3
        arm = sz * 2 // 5
        draw.line([cx, py - arm, cx, py + arm], fill=color, width=lw)
        draw.line([cx - arm, py, cx + arm, py], fill=color, width=lw)

    elif icon_type == "switch":
        # 雙向箭頭
        arm = sz * 4 // 5
        gap = sz // 3
        ah  = lw * 2  # 箭頭尖端高度
        # 向右箭頭（上）
        y1 = cy - gap
        draw.line([cx - arm, y1, cx + arm, y1], fill=color, width=lw)
        draw.line([cx + arm - arm // 3, y1 - ah, cx + arm, y1, cx + arm - arm // 3, y1 + ah],
                  fill=color, width=lw)
        # 向左箭頭（下）
        y2 = cy + gap
        draw.line([cx + arm, y2, cx - arm, y2], fill=color, width=lw)
        draw.line([cx - arm + arm // 3, y2 - ah, cx - arm, y2, cx - arm + arm // 3, y2 + ah],
                  fill=color, width=lw)

    elif icon_type == "globe":
        # 外圓
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=lw)
        # 中央經線橢圓（縱向窄橢圓）
        draw.ellipse([cx - r // 2, cy - r, cx + r // 2, cy + r], outline=color, width=lw - 2)
        # 赤道橫線
        draw.line([cx - r, cy, cx + r, cy], fill=color, width=lw - 2)
        # 緯線（上下各一）
        sp = int(r * 0.87)
        draw.line([cx - sp, cy - r // 2, cx + sp, cy - r // 2], fill=color, width=max(3, lw - 3))
        draw.line([cx - sp, cy + r // 2, cx + sp, cy + r // 2], fill=color, width=max(3, lw - 3))


# ── 圖片生成 ─────────────────────────────────────────────────────────────────

def _build_image(path: str) -> None:
    from PIL import Image, ImageDraw

    img  = Image.new("RGB", (WIDTH, HEIGHT), color=_C_PAGE)
    draw = ImageDraw.Draw(img)

    font_label = _load_font(80)   # 主標文字
    font_sub   = _load_font(38)   # 副標文字

    for label, sub, icon_type, bx, by, bw, bh, is_uri in _BUTTONS:
        bg      = _C_WEB_BG if is_uri else _C_CELL
        fg      = _C_WEB_FG if is_uri else _C_ICON
        fg_sub  = _C_WEB_FG if is_uri else _C_ICON_S

        # 填色
        draw.rectangle([bx, by, bx + bw - 1, by + bh - 1], fill=bg)

        cx = bx + bw // 2
        # 圖示中心：格子高度 38%；主標：60%；副標動態計算（主標下方 10px）
        icon_cy  = by + bh * 38 // 100
        text_y   = by + bh * 60 // 100
        icon_sz  = min(bw, bh) * 20 // 100   # 圖示半徑 ≈ 格子短邊的 20%

        _draw_icon(draw, icon_type, cx, icon_cy, icon_sz, fg)

        label_h = 0
        if font_label:
            bbox = draw.textbbox((0, 0), label, font=font_label)
            label_h = bbox[3] - bbox[1]
            draw.text((cx - (bbox[2] - bbox[0]) / 2, text_y), label,
                      fill=fg, font=font_label)

        if font_sub:
            bbox2 = draw.textbbox((0, 0), sub, font=font_sub)
            # 副標緊接在主標下方，不依賴固定百分比
            actual_sub_y = text_y + label_h + 10
            draw.text((cx - (bbox2[2] - bbox2[0]) / 2, actual_sub_y), sub,
                      fill=fg_sub, font=font_sub)

    # 格線（繪在最上層）
    draw.line([(0, _HALF_H), (_COL_W * 2, _HALF_H)], fill=_C_DIV, width=2)   # 橫向（左、中欄）
    for col_x in [_COL_W, _COL_W * 2]:
        draw.line([(col_x, 0), (col_x, HEIGHT)], fill=_C_DIV, width=2)       # 縱向

    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    logger.info("已產生選單圖片：%s（%dx%d）", path, WIDTH, HEIGHT)


# ── LINE Rich Menu 建立 ───────────────────────────────────────────────────────

def setup_rich_menu() -> str:
    """建立 Rich Menu、上傳圖片，並設為所有使用者的預設選單。"""
    conf = Configuration(access_token=config.LINE_CHANNEL_ACCESS_TOKEN)

    areas = []
    for label, sub, icon_type, bx, by, bw, bh, is_uri in _BUTTONS:
        action = URIAction(label=label, uri=_WEBSITE_URI) if is_uri \
                 else MessageAction(label=label, text=label)
        areas.append(RichMenuArea(
            bounds=RichMenuBounds(x=bx, y=by, width=bw, height=bh),
            action=action,
        ))

    menu_req = RichMenuRequest(
        size=RichMenuSize(width=WIDTH, height=HEIGHT),
        selected=False,          # 預設收起，使用者點底部「選單」展開
        name="育兒小幫手主選單",
        chat_bar_text="選單",
        areas=areas,
    )

    # 每次執行都重新產生圖片
    _build_image(IMAGE_PATH)

    with ApiClient(conf) as client:
        api = MessagingApi(client)
        rich_menu_id = api.create_rich_menu(menu_req).rich_menu_id
        logger.info("已建立 Rich Menu：%s", rich_menu_id)

        with open(IMAGE_PATH, "rb") as f:
            resp = requests.post(
                f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
                headers={
                    "Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}",
                    "Content-Type": "image/png",
                },
                data=f.read(),
            )
            resp.raise_for_status()
        logger.info("已上傳選單圖片")

        api.set_default_rich_menu(rich_menu_id)
        logger.info("已設為預設選單")

    return rich_menu_id


if __name__ == "__main__":
    setup_rich_menu()
