import os
import time
from PIL import Image, ImageDraw, ImageFont

RENDERS_DIR = "app/static/renders"

_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",
]


def _font(size: int):
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _draw_dim(draw, x1, y1, x2, y2, label, offset, font, color=(20, 20, 20)):
    """Extension + arrowhead dimension line at a perpendicular offset."""
    dx, dy = x2 - x1, y2 - y1
    length = (dx * dx + dy * dy) ** 0.5
    if length == 0:
        return
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    ox, oy = px * offset, py * offset
    ax, ay = x1 + ox, y1 + oy
    bx, by = x2 + ox, y2 + oy
    draw.line([(ax, ay), (bx, by)], fill=color, width=1)
    for tx, ty in ((x1, y1), (x2, y2)):
        draw.line([(tx, ty), (tx + ox * 0.8, ty + oy * 0.8)], fill=color, width=1)
    # arrowheads
    def arrow(tx, ty, forward):
        tip = (tx + ox, ty + oy)
        base = (tx - ox * 0.35, ty - oy * 0.35)
        mx = base[0] - ux * 8, base[1] - uy * 8
        draw.polygon([tip, mx, (mx[0] + px * 4, mx[1] + py * 4)], fill=color)
    arrow(x1, y1, True)
    arrow(x2, y2, True)
    draw.text(((ax + bx) / 2 - 12, (ay + by) / 2 - 8), str(label), font=font, fill=color)


def _draw_view(draw, x, y, w, h, label, font_title, font_dim, cylinder_top=False):
    """Draws a rectangle (or circle for cylinder top view) at (x, y), w wide h tall."""
    if cylinder_top:
        r = min(w, h) / 2
        cx, cy = x + w / 2, y + h / 2
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(10, 10, 10), width=2)
        draw.line([(cx - r, cy), (cx + r, cy)], fill=(10, 10, 10), width=1)
    else:
        draw.rectangle([x, y, x + w, y + h], outline=(10, 10, 10), width=2)
    draw.text((x - 4, y - 18), label, font=font_title, fill=(60, 60, 60))


class DrawingService:
    def render_sheet(self, session: dict, parts: list, measurements: list) -> list:
        """
        Generate a 2D technical drawing sheet (front / top / side orthographic
        projections + title block + BOM) for the verified assembly. Returns
        list of {view, url, file}.
        """
        os.makedirs(RENDERS_DIR, exist_ok=True)
        tb = session.get("initial_eval", {}).get("title_block", {})
        bbox = [session.get("assembly_bbox_mm") or [0, 0, 0]][0]
        L, W, H = bbox[0], bbox[1], bbox[2]
        if L <= 0:
            L, W, H = 400.0, 260.0, 100.0

        # scale geometry to fit the canvas
        canvas = Image.new("RGB", (1750, 1200), "white")
        draw = ImageDraw.Draw(canvas)
        f_small = _font(14)
        f_mid = _font(18)
        f_big = _font(26)

        scale = min(700.0 / L, 420.0 / H, 700.0 / W)
        px = lambda mm: int(mm * scale)

        # --- Title block (bottom right) ---
        tx, ty = 950, 1000
        draw.rectangle([tx, ty, tx + 750, ty + 150], outline=(0, 0, 0), width=2)
        rows = [
            ("PART / PARÇA", tb.get("part_name", "Assembly")),
            ("DRAWING NO", tb.get("drawing_number", "N/A")),
            ("MATERIAL", session.get("material", "St37-2")),
            ("SCALE / THICKNESS", f"1:2  /  {session.get('thickness', '-')} mm"),
            ("MASS / AĞIRLIK", f"{session.get('total_mass_g', 0):.1f} g"),
            ("TOLERANCES / DESIGNER", f"{tb.get('tolerances', 'ISO 2768-m')}  /  {tb.get('designer', 'N/A')}"),
        ]
        y = ty + 8
        for label, value in rows:
            draw.text((tx + 10, y), label, font=f_small, fill=(90, 90, 90))
            draw.text((tx + 260, y), str(value), font=f_mid, fill=(0, 0, 0))
            y += 24
        draw.text((tx + 260, ty + 8 + 6 * 24 + 4), f"Zoo The API Makeathon - Agentic Engine Loop  |  {time.strftime('%d/%m/%Y')}",
                  font=f_small, fill=(120, 120, 120))

        # --- Orthographic views ---
        ox, oy = 120, 300
        # TOP VIEW (XY)
        _draw_view(draw, ox, oy - px(H) - 120, px(L), px(W), "TOP / ÜST GÖRÜNÜŞ", f_big, f_small)
        _draw_dim(draw, ox, oy - px(H) - 120 + px(W) + 10, ox + px(L), oy - px(H) - 120 + px(W) + 10,
                  f"{L:.0f} mm", 28, f_mid)
        _draw_dim(draw, ox - 30, oy - px(H) - 120, ox - 30, oy - px(H) - 120 + px(W),
                  f"{W:.0f} mm", -18, f_mid)
        # FRONT VIEW (XZ)
        _draw_view(draw, ox, oy, px(L), px(H), "FRONT / ÖN GÖRÜNÜŞ", f_big, f_small)
        _draw_dim(draw, ox, oy + px(H) + 20, ox + px(L), oy + px(H) + 20, f"{L:.0f} mm", 0, f_mid)
        _draw_dim(draw, ox - 30, oy, ox - 30, oy + px(H), f"{H:.0f} mm", -18, f_mid)
        # RIGHT VIEW (YZ)
        rx = ox + px(L) + 260
        _draw_view(draw, rx, oy, px(W), px(H), "SIDE / YAN GÖRÜNÜŞ", f_big, f_small)
        _draw_dim(draw, rx, oy + px(H) + 20, rx + px(W), oy + px(H) + 20, f"{W:.0f} mm", 0, f_mid)

        # --- BOM ---
        by = 60
        draw.text((40, by - 8), f"ASSEMBLY:  {tb.get('part_name', 'Assembly')}   |   BOUNDING BOX: {L:.0f} x {W:.0f} x {H:.0f} mm",
                  font=f_big, fill=(0, 0, 0))
        by = 130
        headers = ["POZ", "PART NAME", "SHAPE", "GEOMETRY (mm)", "QTY", "MASS (g)", "ENGINE"]
        col_x = [40, 100, 260, 360, 720, 800, 940]
        for hx, h in zip(col_x, headers):
            draw.text((hx, by), h, font=f_small, fill=(90, 90, 90))
        draw.line([(35, by + 22), (1150, by + 22)], fill=(0, 0, 0), width=1)
        by += 30
        for i, (p, m) in enumerate(zip(parts, measurements)):
            if p.get("shape") == "cylinder":
                geom = f"R={p['radius_mm']:.0f} T={p['T_mm']:.0f}"
            else:
                geom = f"{p['L_mm']:.0f}x{p['W_mm']:.0f}x{p['T_mm']:.0f}"
            vals = [p.get("id", f"POZ-{i+1:02d}"), p.get("name", ""), p.get("shape", ""),
                    geom, str(p.get("qty", 1)), f"{m['mass_grams']:.1f}",
                    "REAL" if m.get("engine_real") else "EST"]
            for hx, v in zip(col_x, vals):
                draw.text((hx, by), str(v)[:34], font=f_mid, fill=(0, 0, 0))
            by += 30
            if by > 900:
                break
        draw.line([(35, by + 6), (1150, by + 6)], fill=(0, 0, 0), width=1)
        draw.text((35, by + 14),
                  f"TOTAL MASS: {session.get('total_mass_g', 0):.1f} g  |  MATERIAL: {session.get('material', 'St37-2')}  |  ENGINE-PROVEN: {sum(1 for m in measurements if m.get('engine_real'))}/{len(measurements)} parts",
                  font=f_mid, fill=(10, 10, 10))

        ts = int(time.time())
        urls = []
        filename = f"technical_drawing_{ts}.png"
        path = os.path.join(RENDERS_DIR, filename)
        canvas.save(path)
        urls.append({"view": "sheet", "url": f"/static/renders/{filename}", "file": path})

        return urls


drawing_service = DrawingService()