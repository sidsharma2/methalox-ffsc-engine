"""Drawing sheet template and drafting primitives (ezdxf, units mm, plotted 1:1 by AutoCAD).

The template follows the owner's drawing standard (EM-P220 series) without the logo:
ISO 5457 sheet with filing margin, zone grid and centring marks; ISO 7200 title block
(180 mm); a two-row standards strip above it; ISO 3098 type B lettering (ISOCPEUR);
ISO 128-20 line widths (0.5 / 0.25 / 0.18 mm) via layer lineweights and ISO line types;
ISO 128-50 section hatching; ISO 129-1 dimensions; balloons and parts lists after
ISO 6433 / ISO 7573.
"""

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment

SIZES = {"A3": (420.0, 297.0, 8, 6), "A2": (594.0, 420.0, 12, 8)}
ISO_FONT = "isocpeur.ttf"
SANS_FONT = "arial.ttf"

LAYERS = {
    # name: (lineweight in 1/100 mm, linetype)
    "FRAME": (70, "CONTINUOUS"),
    "VISIBLE": (50, "CONTINUOUS"),
    "THIN": (25, "CONTINUOUS"),
    "HIDDEN": (25, "ISO_HIDDEN"),
    "CENTER": (25, "ISO_CENTER"),
    "PHANTOM": (25, "ISO_PHANTOM"),
    "CUTPLANE": (25, "ISO_CENTER"),
    "CUTPLANE_THICK": (50, "CONTINUOUS"),
    "HATCH": (18, "CONTINUOUS"),
    "DIM": (18, "CONTINUOUS"),
    "TEXT": (25, "CONTINUOUS"),
    "TITLE": (35, "CONTINUOUS"),
    "TABLE": (35, "CONTINUOUS"),
    "TABLE_THIN": (18, "CONTINUOUS"),
    "BALLOON": (25, "CONTINUOUS"),
    "PROCESS": (70, "CONTINUOUS"),        # P&ID main process lines
    "PROCESS_MINOR": (35, "CONTINUOUS"),
    "SIGNAL": (25, "ISO_SIGNAL"),         # ISA-5.1 electrical signal (dashed)
    "SYMBOL": (35, "CONTINUOUS"),
    "SYMBOL_THIN": (25, "CONTINUOUS"),
    "BOUNDARY": (25, "ISO_PHANTOM"),
}

LINETYPES = {
    # ISO 128-20 style patterns for 0.25 mm lines, mm on paper
    "ISO_HIDDEN": [4.0, 3.0, -1.0],
    "ISO_CENTER": [18.0, 12.0, -2.0, 2.0, -2.0],
    "ISO_PHANTOM": [22.0, 12.0, -2.0, 2.0, -2.0, 2.0, -2.0],
    "ISO_SIGNAL": [3.0, 2.0, -1.0],
}


@dataclass
class TitleInfo:
    dwg_no: str
    title: list                      # up to 3 lines
    doc_type: str = "ASSEMBLY DRAWING"
    status: str = "PRELIMINARY"
    rev: str = "A"
    date: str = "2026-10-31"
    sheet: str = "1/1"
    dept: str = "PROP"
    tech_ref: str = "FREECAD v1.1, IT. 1"
    created_by: str = "Siddharth Sharma"
    approved_by: str = ""
    scale: str = "AS NOTED"
    projection: str = "THIRD-ANGLE PROJECTION"
    strip: list = field(default_factory=lambda: [
        "GENERAL TOL. ISO 2768-m   GEOMETRY ISO 22081   TOLERANCING ISO 8015   mm",
        "( ) = REFERENCE   SURFACE ISO 21920-1   EDGES ISO 13715   3RD ANGLE"])


class Sheet:
    def __init__(self, size="A3"):
        self.W, self.H, self.ncol, self.nrow = SIZES[size]
        self.size = size
        self.doc = ezdxf.new("R2018", setup=True)
        self.doc.units = ezdxf.units.MM
        self.doc.header["$MEASUREMENT"] = 1
        self.doc.header["$LTSCALE"] = 1.0
        self.doc.header["$LWDISPLAY"] = 1
        for name, pat in LINETYPES.items():
            if name not in self.doc.linetypes:
                self.doc.linetypes.add(name, pattern=pat, description=name)
        for name, (lw, lt) in LAYERS.items():
            self.doc.layers.add(name, lineweight=lw, linetype=lt, color=7)
        self.doc.styles.add("ISO", font=ISO_FONT)
        self.doc.styles.add("SANS", font=SANS_FONT)
        ds = self.doc.dimstyles.new("ISO25")
        ds.dxf.dimtxsty = "ISO"
        for k, v in {"dimtxt": 2.5, "dimasz": 2.5, "dimexe": 1.25, "dimexo": 0.8, "dimgap": 0.8, "dimtad": 1,
                     "dimtih": 0, "dimtoh": 0, "dimdec": 1, "dimzin": 8, "dimdsep": 46, "dimlwd": 18, "dimlwe": 18,
                     "dimclrd": 7, "dimclre": 7, "dimclrt": 7, "dimtofl": 1, "dimatfit": 3, "dimtmove": 0}.items():
            ds.set_dxf_attrib(k, v)
        self.msp = self.doc.modelspace()
        self.fx0, self.fy0 = 20.0, 10.0
        self.fx1, self.fy1 = self.W - 10.0, self.H - 10.0
        self.images = []                 # raster placements, see image() / embed_images()

    # ------------------------------------------------------------------ primitives
    def line(self, p, q, layer="THIN"):
        return self.msp.add_line(p, q, dxfattribs={"layer": layer})

    def poly(self, pts, layer="VISIBLE", closed=False):
        return self.msp.add_lwpolyline(pts, close=closed, dxfattribs={"layer": layer})

    def rect(self, x, y, w, h, layer="THIN"):
        return self.poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], layer, closed=True)

    def circle(self, c, r, layer="THIN"):
        return self.msp.add_circle(c, r, dxfattribs={"layer": layer})

    def arc(self, c, r, a0, a1, layer="THIN"):
        return self.msp.add_arc(c, r, a0, a1, dxfattribs={"layer": layer})

    def text(self, s, p, h=2.5, align="BOTTOM_LEFT", style="ISO", layer="TEXT", rot=0.0, width=1.0):
        t = self.msp.add_text(s, height=h, rotation=rot, dxfattribs={"style": style, "layer": layer, "width": width})
        t.set_placement(p, align=getattr(TextEntityAlignment, align))
        return t

    def solid_tri(self, a, b, c, layer="THIN"):
        h = self.msp.add_hatch(dxfattribs={"layer": layer})
        h.set_solid_fill(color=7)
        h.paths.add_polyline_path([a, b, c], is_closed=True)
        return h

    def arrowhead(self, tip, frm, length=2.5, width=0.85, layer="THIN"):
        dx, dy = tip[0] - frm[0], tip[1] - frm[1]
        L = math.hypot(dx, dy) or 1.0
        ux, uy = dx / L, dy / L
        bx, by = tip[0] - ux * length, tip[1] - uy * length
        return self.solid_tri(tip, (bx - uy * width / 2, by + ux * width / 2), (bx + uy * width / 2, by - ux * width / 2), layer)

    def dot(self, c, r=0.6, layer="THIN"):
        h = self.msp.add_hatch(dxfattribs={"layer": layer})
        h.set_solid_fill(color=7)
        h.paths.add_edge_path().add_arc(c, r, 0, 360)
        return h

    def hatch(self, loops, angle=45.0, spacing=2.5, layer="HATCH", solid=False):
        """ISO 128-50 hatching of closed loops (nested loops become islands)."""
        h = self.msp.add_hatch(dxfattribs={"layer": layer})
        if solid:
            h.set_solid_fill(color=7)
        else:
            h.set_pattern_fill("ANSI31", scale=spacing / 3.175, angle=angle - 45.0, color=7)
        for lp in loops:
            if len(lp) >= 3:
                h.paths.add_polyline_path(lp, is_closed=True)
        return h

    # ------------------------------------------------------------------ annotation
    def view_title(self, x, y, title, sub=None):
        """View heading as on the EM-P220 sheets: 5 mm title, 3.5 mm scale/plane line below."""
        self.text(title, (x, y), 5.0, "TOP_LEFT", width=1.15)
        if sub:
            self.text(sub, (x, y - 7.5), 3.0, "TOP_LEFT")

    def balloon(self, c, label, target, r=4.25, terminator="arrow"):
        """ISO 6433 item reference: circle with item number, thin leader to the part."""
        self.circle(c, r, "BALLOON")
        self.text(str(label), c, 3.5, "MIDDLE_CENTER", layer="BALLOON")
        dx, dy = target[0] - c[0], target[1] - c[1]
        L = math.hypot(dx, dy)
        if L <= r:
            return
        start = (c[0] + dx / L * r, c[1] + dy / L * r)
        self.line(start, target, "BALLOON")
        if terminator == "arrow":
            self.arrowhead(target, start, layer="BALLOON")
        elif terminator == "dot":
            self.dot(target, 0.7, "BALLOON")

    def leader(self, target, text_pos, lines, h=2.5, terminator="arrow", align="left"):
        """Leader line with an arrow (on an outline) or a dot (inside a surface), ISO 128-22."""
        shelf = 3.0 if align == "left" else -3.0
        self.line(target, text_pos, "THIN")
        self.line(text_pos, (text_pos[0] + shelf, text_pos[1]), "THIN")
        if terminator == "arrow":
            self.arrowhead(target, text_pos)
        elif terminator == "dot":
            self.dot(target, 0.7)
        if isinstance(lines, str):
            lines = [lines]
        x = text_pos[0] + (shelf + 1.0 if align == "left" else shelf - 1.0)
        for i, s in enumerate(lines):
            self.text(s, (x, text_pos[1] + 0.8 - i * (h + 1.5)), h, "BOTTOM_LEFT" if align == "left" else "BOTTOM_RIGHT")

    def table(self, x, y_top, columns, rows, title=None, row_h=5.0, text_h=2.2, header=True):
        """Parts list / data table. columns: [(header, width)]. Returns the bottom y."""
        if title:
            self.text(title, (x, y_top + 1.8), 3.6, "BOTTOM_LEFT", width=1.1)
        W = sum(w for _, w in columns)
        all_rows = ([[c for c, _ in columns]] if header else []) + rows
        H = row_h * len(all_rows)
        self.rect(x, y_top - H, W, H, "TABLE")
        for i in range(1, len(all_rows)):
            self.line((x, y_top - i * row_h), (x + W, y_top - i * row_h), "TABLE" if (header and i == 1) else "TABLE_THIN")
        xx = x
        for _, w in columns[:-1]:
            xx += w
            self.line((xx, y_top), (xx, y_top - H), "TABLE_THIN")
        for i, row in enumerate(all_rows):
            xx = x
            for (_, w), cell in zip(columns, row):
                self.text(str(cell), (xx + 1.2, y_top - (i + 0.5) * row_h), text_h, "MIDDLE_LEFT", width=0.9)
                xx += w
        return y_top - H

    def notes(self, x, y_top, lines, h=2.2, gap=1.6, numbered=True):
        for i, s in enumerate(lines):
            self.text(f"{i + 1}. {s}" if numbered else s, (x, y_top - i * (h + gap)), h, "TOP_LEFT", width=0.9)
        return y_top - len(lines) * (h + gap)

    def boxed_note(self, x, y, w, text, h=2.5, pad=2.2):
        self.rect(x, y, w, h + 2 * pad, "TABLE")
        self.text(text, (x + pad, y + pad + h / 2), h, "MIDDLE_LEFT")

    def cut_plane(self, p, q, letter, toward, ext=7.0):
        """Cutting plane per ISO 128-44: thick ends, thin chain between, arrows with letters.
        toward: unit vector of the viewing direction (arrows point that way)."""
        dx, dy = q[0] - p[0], q[1] - p[1]
        L = math.hypot(dx, dy)
        ux, uy = dx / L, dy / L
        self.line(p, q, "CUTPLANE")
        for end, s in ((p, 1), (q, -1)):
            a = end
            b = (end[0] + s * ux * ext, end[1] + s * uy * ext)
            self.line(a, b, "CUTPLANE_THICK")
            tail = (end[0] - s * ux * 0.0, end[1] - s * uy * 0.0)
            head = (tail[0] + toward[0] * 8.0, tail[1] + toward[1] * 8.0)
            self.line(tail, head, "THIN")
            self.arrowhead(head, tail, 3.5, 1.2)
            self.text(letter, (head[0] + toward[0] * 3.5 - s * ux * 2.0, head[1] + toward[1] * 3.5 - s * uy * 2.0),
                      5.0, "MIDDLE_CENTER")

    def detail_circle(self, c, r, letter):
        self.circle(c, r, "THIN")
        a = math.radians(45)
        p = (c[0] + r * math.cos(a), c[1] + r * math.sin(a))
        self.line(p, (p[0] + 5, p[1] + 5), "THIN")
        self.text(letter, (p[0] + 6.5, p[1] + 6.5), 5.0, "BOTTOM_LEFT")

    def centerline(self, p, q, ext=4.0):
        dx, dy = q[0] - p[0], q[1] - p[1]
        L = math.hypot(dx, dy)
        ux, uy = dx / L, dy / L
        self.line((p[0] - ux * ext, p[1] - uy * ext), (q[0] + ux * ext, q[1] + uy * ext), "CENTER")

    def dim_linear(self, p1, p2, base, angle=0.0, scale=1.0, text="<>", override=None):
        ov = {"dimlfac": scale}
        if override:
            ov.update(override)
        d = self.msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dimstyle="ISO25", text=text,
                                    override=ov, dxfattribs={"layer": "DIM"})
        d.render()
        return d

    def dim_aligned(self, p1, p2, distance, scale=1.0, text="<>"):
        d = self.msp.add_aligned_dim(p1=p1, p2=p2, distance=distance, dimstyle="ISO25", text=text,
                                     override={"dimlfac": scale}, dxfattribs={"layer": "DIM"})
        d.render()
        return d

    def dim_diameter(self, center, radius, angle_deg, scale=1.0, text="Ø<>"):
        d = self.msp.add_diameter_dim(center=center, radius=radius, angle=angle_deg, dimstyle="ISO25", text=text,
                                      override={"dimlfac": scale}, dxfattribs={"layer": "DIM"})
        d.render()
        return d

    def projection_symbol(self, x, y, s=1.0):
        """ISO 5456-2 third-angle symbol: circles on the left, truncated cone on the right
        with its small end towards the circles."""
        d_big, d_small, L = 10.0 * s, 5.0 * s, 10.0 * s
        c = (x + d_big / 2, y + d_big / 2)
        self.circle(c, d_big / 2, "VISIBLE")
        self.circle(c, d_small / 2, "VISIBLE")
        self.centerline((c[0] - d_big / 2, c[1]), (c[0] + d_big / 2, c[1]), 1.5)
        self.centerline((c[0], c[1] - d_big / 2), (c[0], c[1] + d_big / 2), 1.5)
        x0 = x + d_big + 5.0 * s
        yc = c[1]
        self.poly([(x0, yc - d_small / 2), (x0 + L, yc - d_big / 2), (x0 + L, yc + d_big / 2), (x0, yc + d_small / 2)],
                  "VISIBLE", closed=True)
        self.centerline((x0, yc), (x0 + L, yc), 1.5)

    # ------------------------------------------------------------------ sheet frame and title block
    def frame(self, info: TitleInfo):
        W, H = self.W, self.H
        x0, y0, x1, y1 = self.fx0, self.fy0, self.fx1, self.fy1
        self.rect(x0, y0, x1 - x0, y1 - y0, "FRAME")
        # ISO 5457 grid: 50 mm zones counted from the centre of the drawing frame
        xc0, yc0 = (x0 + x1) / 2, (y0 + y1) / 2
        xs = sorted({x0, x1} | {xc0 + k * 50.0 for k in range(-self.ncol // 2 + 1, self.ncol // 2)})
        ys = sorted({y0, y1} | {yc0 + k * 50.0 for k in range(-self.nrow // 2 + 1, self.nrow // 2)})
        for xx in xs[1:-1]:
            self.line((xx, y1), (xx, H), "THIN")
            self.line((xx, 0), (xx, y0), "THIN")
        for yy in ys[1:-1]:
            self.line((0, yy), (x0, yy), "THIN")
            self.line((x1, yy), (W, yy), "THIN")
        for i in range(len(xs) - 1):
            xc = (xs[i] + xs[i + 1]) / 2
            self.text(str(i + 1), (xc, (y1 + H) / 2), 3.5, "MIDDLE_CENTER")
            self.text(str(i + 1), (xc, y0 / 2), 3.5, "MIDDLE_CENTER")
        for j in range(len(ys) - 1):
            yc = (ys[-1 - j] + ys[-2 - j]) / 2
            letter = "ABCDEFGHJK"[j]
            self.text(letter, (x0 / 2 + 3, yc), 3.5, "MIDDLE_CENTER")
            self.text(letter, ((x1 + W) / 2, yc), 3.5, "MIDDLE_CENTER")
        self.zones_x, self.zones_y = xs, ys
        # centring marks on the frame centre lines
        self.line((xc0, H), (xc0, y1 - 5), "FRAME")
        self.line((xc0, 0), (xc0, y0 + 5), "FRAME")
        self.line((0, yc0), (x0 + 5, yc0), "FRAME")
        self.line((W, yc0), (x1 - 5, yc0), "FRAME")
        self.title_block(info)

    def title_block(self, t: TitleInfo):
        """ISO 7200 block, 180 x 47 mm, laid out as on the EM-P220 sheets."""
        x1, y0 = self.fx1, self.fy0
        X = x1 - 180.0
        c1, c2, c3 = X + 24.0, X + 58.0, X + 119.0      # Dept | Tech ref | Created by | Approved by
        top = y0 + 47.0
        r_top1 = top - 10.0                              # first row: Dept / Tech ref / Created / Approved
        r_type = r_top1 - 9.4                            # Document type / Document status
        r_dwg = y0 + 10.7                                # Rev / Date / Sheet row
        # standards strip (two rows) on top of the block
        s1, s2 = top + 8.5, top + 17.0
        self.rect(X, top, 180.0, 17.0, "TITLE")
        self.line((X, s1), (x1, s1), "TABLE_THIN")
        self.text(t.strip[0], (X + 2.5, (s1 + s2) / 2), 2.5, "MIDDLE_LEFT")
        self.text(t.strip[1], (X + 2.5, (top + s1) / 2), 2.5, "MIDDLE_LEFT")
        # block outline and cell lines
        self.rect(X, y0, 180.0, 47.0, "FRAME")
        self.line((X, r_top1), (x1, r_top1), "TITLE")
        self.line((c1, top), (c1, r_top1), "TITLE")
        self.line((c2, top), (c2, y0), "TITLE")
        self.line((c3, top), (c3, y0), "TITLE")
        self.line((c2, r_type), (x1, r_type), "TITLE")
        self.line((c3, r_dwg), (x1, r_dwg), "TITLE")
        r_no = r_dwg
        cRev, cDate = c3 + 9.5, c3 + 9.5 + 36.8
        self.line((cRev, r_dwg), (cRev, y0), "TITLE")
        self.line((cDate, r_dwg), (cDate, y0), "TITLE")

        def field(xl, ytop, label, value, h=3.5, width=1.0, dy=8.4):
            self.text(label, (xl + 1.0, ytop - 0.8), 1.6, "TOP_LEFT", style="SANS")
            if value:
                self.text(value, (xl + 1.0, ytop - dy), h, "BOTTOM_LEFT", style="SANS", width=width)

        field(X, top, "Dept.", t.dept)
        field(c1, top, "Technical reference", t.tech_ref, h=2.6, width=0.82)
        field(c2, top, "Created by", t.created_by)
        field(c3, top, "Approved by", t.approved_by)
        field(c2, r_top1, "Document type", t.doc_type, dy=8.0)
        field(c3, r_top1, "Document status", t.status, dy=8.0)
        self.text("Title", (c2 + 1.0, r_type - 0.8), 1.6, "TOP_LEFT", style="SANS")
        for i, s in enumerate(t.title[:3]):
            self.text(s, (c2 + 1.0, r_type - 8.4 - i * 6.6), 3.5, "BOTTOM_LEFT", style="SANS", width=0.95)
        self.text("DWG No.", (c3 + 1.0, r_type - 0.8), 1.6, "TOP_LEFT", style="SANS")
        self.text(t.dwg_no, ((c3 + x1) / 2, (r_no + r_type) / 2 - 1.0), 3.6, "MIDDLE_CENTER", style="SANS")
        field(c3, r_dwg, "Rev.", t.rev, h=4.0, dy=9.0)
        field(cRev, r_dwg, "Date of issue", t.date, h=4.0, dy=9.0)
        field(cDate, r_dwg, "Sheet", t.sheet, h=3.6, dy=9.0)
        # left block: scale, projection method and the third-angle symbol (no logo)
        self.text(f"SCALE: {t.scale}", (X + 2.0, r_top1 - 3.0), 2.5, "TOP_LEFT")
        self.text(t.projection, (X + 2.0, r_top1 - 7.0), 2.5, "TOP_LEFT")
        if "THIRD" in t.projection:
            self.projection_symbol(X + 14.0, y0 + 7.0, 1.2)

    # ------------------------------------------------------------------ raster images
    def image(self, path, x, y, w=None, h=None):
        """Raster image (PNG) with its lower-left corner at (x, y), width w or height h in mm, aspect kept.

        Only recorded here. render.publish attaches it natively in AutoCAD (accoreconsole cannot
        resolve IMAGE entities read from a DXF) and embed_images() writes it to the DXF."""
        from PIL import Image
        px, py = Image.open(path).size
        if w is None:
            w = h * px / py
        h = w * py / px
        self.images.append({"path": Path(path).resolve(), "x": x, "y": y, "w": w, "h": h, "px": (px, py)})
        return w, h

    def embed_images(self, dxf_dir):
        """Write the recorded images as IMAGEDEF / IMAGE entities, paths relative to dxf_dir, drawn first."""
        if not self.images:
            return
        if "IMAGE" not in self.doc.layers:
            self.doc.layers.add("IMAGE", lineweight=18, color=7)
        self.doc.set_raster_variables(frame=0, quality=1, units="mm")
        order = []
        for k, im in enumerate(self.images):
            rel = os.path.relpath(im["path"], dxf_dir)
            idef = self.doc.add_image_def(filename=rel, size_in_pixel=im["px"], name=im["path"].stem)
            e = self.msp.add_image(idef, insert=(im["x"], im["y"]), size_in_units=(im["w"], im["h"]), rotation=0,
                                   dxfattribs={"layer": "IMAGE"})
            order.append((e.dxf.handle, f"{k + 1:X}"))
        self.msp.set_redraw_order(order)      # low sort handles: images behind every vector entity

    # ------------------------------------------------------------------ output
    def save(self, path_dxf):
        self.doc.saveas(path_dxf)
