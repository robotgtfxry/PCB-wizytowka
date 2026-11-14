"""Tiny 2-layer grid maze router (A*) for pcbnew boards built by kc.Board.

Obstacles are rasterised with clearance inflation, so any path found on the
grid keeps the requested clearance. Paths are then simplified with
line-of-sight checks. Good enough for a handful of nets on a business card.
"""
import heapq
import math
from array import array

import numpy as np
import pcbnew

LAYERS = (pcbnew.F_Cu, pcbnew.B_Cu)
EMPTY, BLOCK = -1, -2


class Router:
    def __init__(self, kb, x1, y1, x2, y2, corner_r=3.0, res=0.1, clearance=0.15,
                 margin=0.04, edge_clear=0.35, widths=(0.15, 0.2, 0.3), via=(0.5, 0.3)):
        self.kb = kb
        self.res = res
        self.x0, self.y0 = x1, y1
        self.nx = int(round((x2 - x1) / res)) + 1
        self.ny = int(round((y2 - y1) / res)) + 1
        self.cl = clearance
        self.margin = margin
        self.widths = widths
        self.via_d, self.via_drill = via
        xs = x1 + np.arange(self.nx) * res
        ys = y1 + np.arange(self.ny) * res
        self.X, self.Y = np.meshgrid(xs, ys)
        shape = (self.ny, self.nx)
        # track-centre grids per width, per layer
        self.T = {w: [np.full(shape, EMPTY, np.int32) for _ in LAYERS] for w in widths}
        self.Vg = [np.full(shape, EMPTY, np.int32) for _ in LAYERS]   # via-centre grid
        self.C = [np.full(shape, EMPTY, np.int32) for _ in LAYERS]    # copper itself
        self.H = np.zeros(shape, bool)                                 # near drilled holes
        self.netid = {}
        self.netname = {}
        self.segs = {}      # net -> list of (layer, x1,y1,x2,y2)
        self.anchors = {}   # net -> list of (layerset, x, y) of pads/vias
        self._edge(x1, y1, x2, y2, corner_r, edge_clear)

    # ------------------------------------------------------------------ nets
    def nid(self, name):
        if name is None or name == "":
            return BLOCK
        if name not in self.netid:
            i = len(self.netid)
            self.netid[name] = i
            self.netname[i] = name
        return self.netid[name]

    # ------------------------------------------------------------- geometry
    def _window(self, bx1, by1, bx2, by2, infl):
        r = self.res
        i1 = max(0, int(math.floor((bx1 - infl - self.x0) / r)))
        i2 = min(self.nx, int(math.ceil((bx2 + infl - self.x0) / r)) + 1)
        j1 = max(0, int(math.floor((by1 - infl - self.y0) / r)))
        j2 = min(self.ny, int(math.ceil((by2 + infl - self.y0) / r)) + 1)
        return slice(j1, j2), slice(i1, i2)

    @staticmethod
    def _dist_seg(X, Y, x1, y1, x2, y2):
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        if L2 == 0:
            return np.hypot(X - x1, Y - y1)
        t = np.clip(((X - x1) * dx + (Y - y1) * dy) / L2, 0, 1)
        return np.hypot(X - (x1 + t * dx), Y - (y1 + t * dy))

    def _dist(self, prim, X, Y):
        kind = prim[0]
        if kind == "seg":
            _, x1, y1, x2, y2, hw = prim
            return self._dist_seg(X, Y, x1, y1, x2, y2) - hw
        if kind == "circle":
            _, cx, cy, r = prim
            return np.hypot(X - cx, Y - cy) - r
        if kind == "poly":
            pts = prim[1]
            d = np.full(X.shape, np.inf)
            inside = np.zeros(X.shape, bool)
            n = len(pts)
            for i in range(n):
                ax, ay = pts[i]
                bx, by = pts[(i + 1) % n]
                d = np.minimum(d, self._dist_seg(X, Y, ax, ay, bx, by))
                cond = ((ay > Y) != (by > Y))
                with np.errstate(divide="ignore", invalid="ignore"):
                    xint = ax + (Y - ay) * (bx - ax) / (by - ay)
                inside ^= cond & (X < xint)
            d[inside] = 0.0
            return d
        raise ValueError(kind)

    @staticmethod
    def _bbox(prim):
        if prim[0] == "seg":
            _, x1, y1, x2, y2, hw = prim
            return min(x1, x2) - hw, min(y1, y2) - hw, max(x1, x2) + hw, max(y1, y2) + hw
        if prim[0] == "circle":
            _, cx, cy, r = prim
            return cx - r, cy - r, cx + r, cy + r
        xs = [p[0] for p in prim[1]]
        ys = [p[1] for p in prim[1]]
        return min(xs), min(ys), max(xs), max(ys)

    @staticmethod
    def _mark(g, mask, net):
        if net == BLOCK:
            g[mask] = BLOCK
            return
        empty = mask & (g == EMPTY)
        other = mask & (g != EMPTY) & (g != net)
        g[empty] = net
        g[other] = BLOCK

    def add_prim(self, prim, layers, net):
        """Register copper `prim` on `layers` (indices 0/1) for net id `net`."""
        bb = self._bbox(prim)
        big = self.cl + max(self.widths) / 2 + self.margin + self.via_d / 2 + 0.2
        sl = self._window(*bb, big)
        X, Y = self.X[sl], self.Y[sl]
        d = self._dist(prim, X, Y)
        for li in layers:
            for w in self.widths:
                self._mark(self.T[w][li][sl], d < self.cl + w / 2 + self.margin, net)
            self._mark(self.Vg[li][sl], d < self.cl + self.via_d / 2 + self.margin, net)
            self._mark(self.C[li][sl], d < 0.02, net)

    def add_hole(self, x, y, drill):
        prim = ("circle", x, y, drill / 2)
        sl = self._window(x - drill, y - drill, x + drill, y + drill, 1.0)
        d = self._dist(prim, self.X[sl], self.Y[sl])
        self.H[sl] |= d < 0.25 + self.via_drill / 2 + self.margin

    def _edge(self, x1, y1, x2, y2, r, ec):
        X, Y = self.X, self.Y
        # distance to the inside of a rounded rectangle
        cx = np.clip(X, x1 + r, x2 - r)
        cy = np.clip(Y, y1 + r, y2 - r)
        d_in = r - np.hypot(X - cx, Y - cy)       # >0 inside
        for li in range(2):
            for w in self.widths:
                self.T[w][li][d_in < ec + w / 2] = BLOCK
            self.Vg[li][d_in < ec + self.via_d / 2] = BLOCK
        self.T_edge = d_in

    # ------------------------------------------------------------ importing
    def import_board(self):
        b = self.kb.b
        for f in b.GetFootprints():
            for p in f.Pads():
                if not p.IsOnCopperLayer():
                    if p.HasHole():
                        x, y = self.kb.local(p.GetPosition())
                        self.add_hole(x, y, pcbnew.ToMM(p.GetDrillSize().x))
                        prim = ("circle", x, y, pcbnew.ToMM(p.GetDrillSize().x) / 2)
                        self.add_prim(prim, (0, 1), BLOCK)
                    continue
                self.add_pad(p)
        for t in b.GetTracks():
            if isinstance(t, pcbnew.PCB_VIA) or t.GetClass() == "PCB_VIA":
                v = t.Cast() if hasattr(t, "Cast") else t
                x, y = self.kb.local(v.GetPosition())
                self.add_via_obstacle(x, y, v.GetNetname(), pcbnew.ToMM(v.GetWidth(pcbnew.F_Cu)),
                                      pcbnew.ToMM(v.GetDrillValue()))
            else:
                self.add_track_obstacle(t)

    def add_pad(self, p):
        net = self.nid(p.GetNetname())
        layers = [i for i, L in enumerate(LAYERS) if p.IsOnLayer(L)]
        for li in layers:
            poly = p.GetEffectivePolygon(LAYERS[li], pcbnew.ERROR_INSIDE)
            ol = poly.COutline(0)
            pts = [self.kb.local(ol.CPoint(i)) for i in range(ol.PointCount())]
            self.add_prim(("poly", pts), (li,), net)
        x, y = self.kb.local(p.GetPosition())
        if p.HasHole():
            self.add_hole(x, y, pcbnew.ToMM(p.GetDrillSize().x))
        self.anchors.setdefault(net, []).append((tuple(layers), x, y))

    def add_via_obstacle(self, x, y, netname, dia, drill):
        net = self.nid(netname)
        self.add_prim(("circle", x, y, dia / 2), (0, 1), net)
        self.add_hole(x, y, drill)
        self.anchors.setdefault(net, []).append(((0, 1), x, y))

    def add_track_obstacle(self, t):
        net = self.nid(t.GetNetname())
        x1, y1 = self.kb.local(t.GetStart())
        x2, y2 = self.kb.local(t.GetEnd())
        li = 0 if t.GetLayer() == pcbnew.F_Cu else 1
        self.add_prim(("seg", x1, y1, x2, y2, pcbnew.ToMM(t.GetWidth()) / 2), (li,), net)
        self.segs.setdefault(net, []).append((li, x1, y1, x2, y2))

    def block_rect(self, x1, y1, x2, y2, layers):
        sl = self._window(x1, y1, x2, y2, 0)
        for li in layers:
            for w in self.widths:
                self.T[w][li][sl] = BLOCK
            self.Vg[li][sl] = BLOCK

    def block_mask(self, mask, layers):
        for li in layers:
            for w in self.widths:
                self.T[w][li][mask] = BLOCK
            self.Vg[li][mask] = BLOCK

    def block_circle(self, cx, cy, r, layers):
        sl = self._window(cx - r, cy - r, cx + r, cy + r, 0)
        m = np.hypot(self.X[sl] - cx, self.Y[sl] - cy) < r
        for li in layers:
            for w in self.widths:
                self.T[w][li][sl][m] = BLOCK
            self.Vg[li][sl][m] = BLOCK

    # --------------------------------------------------------------- search
    def _cell(self, x, y):
        return int(round((x - self.x0) / self.res)), int(round((y - self.y0) / self.res))

    def _xy(self, ix, iy):
        return self.x0 + ix * self.res, self.y0 + iy * self.res

    def route(self, netname, src_pad_xy, dst="net", width=0.2, via_cost=12.0,
              layer_bias=(1.0, 1.0), max_expand=3_000_000, exact=False):
        """Route from the copper under point src (x, y, layers) to either the
        copper under point dst or (dst='net') any other copper of the net that
        is not connected to the source blob."""
        net = self.nid(netname)
        self._exact = exact
        N = self.nx * self.ny
        T = self.T[width]
        passT = [((T[li] == EMPTY) | (T[li] == net)).ravel() for li in range(2)]
        passV = (((self.Vg[0] == EMPTY) | (self.Vg[0] == net)) &
                 ((self.Vg[1] == EMPTY) | (self.Vg[1] == net)) & ~self.H).ravel()
        own = [(self.C[li] == net) for li in range(2)]

        sx, sy, slayers = src_pad_xy
        src_mask = [np.zeros_like(own[0]) for _ in range(2)]
        for li in slayers:
            src_mask[li] = self._blob(own[li], sx, sy) if not exact else np.zeros_like(own[li])
            if not src_mask[li].any():
                ix, iy = self._cell(sx, sy)
                src_mask[li][iy, ix] = True
        if dst == "net":
            goal = [own[li] & ~src_mask[li] for li in range(2)]
            # remove other cells connected to source blob through own copper
        else:
            dx, dy, dlayers = dst
            goal = [np.zeros_like(own[0]) for _ in range(2)]
            for li in dlayers:
                goal[li] = self._blob(own[li], dx, dy) if not exact else np.zeros_like(own[li])
                if not goal[li].any():
                    ix, iy = self._cell(dx, dy)
                    goal[li][iy, ix] = True
        if not (goal[0].any() or goal[1].any()):
            raise RuntimeError(f"{netname}: no goal copper")
        gys, gxs = np.nonzero(goal[0] | goal[1])
        gx1, gx2, gy1, gy2 = gxs.min(), gxs.max(), gys.min(), gys.max()
        goalf = [g.ravel() for g in goal]
        srcf = [s.ravel() for s in src_mask]
        # allow walking inside own source/goal copper even if inflated grid blocks
        pT = [bytearray((passT[li] | srcf[li] | goalf[li]).astype(np.uint8).tobytes()) for li in range(2)]
        pV = bytearray(passV.astype(np.uint8).tobytes())
        gF = [bytearray(goalf[li].astype(np.uint8).tobytes()) for li in range(2)]
        nx = self.nx
        INF = float("inf")
        gs = [array("d", [INF]) * N, array("d", [INF]) * N]
        par = [array("i", [-1]) * N, array("i", [-1]) * N]
        heap = []
        SQ2 = math.sqrt(2)

        def h(idx):
            ix, iy = idx % nx, idx // nx
            ddx = 0 if gx1 <= ix <= gx2 else min(abs(ix - gx1), abs(ix - gx2))
            ddy = 0 if gy1 <= iy <= gy2 else min(abs(iy - gy1), abs(iy - gy2))
            return (max(ddx, ddy) + (SQ2 - 1) * min(ddx, ddy)) * min(layer_bias)

        for li in range(2):
            for idx in np.nonzero(srcf[li])[0]:
                idx = int(idx)
                gs[li][idx] = 0.0
                heapq.heappush(heap, (h(idx), 0.0, li, idx))
        moves = [(1, 1.0, 0, 0), (-1, 1.0, 0, 0), (nx, 1.0, 0, 0), (-nx, 1.0, 0, 0)]
        for sx_ in (1, -1):
            for sy_ in (1, -1):
                moves.append((sy_ * nx + sx_, SQ2, sx_, sy_ * nx))
        found = None
        expanded = 0
        while heap:
            f, g, li, idx = heapq.heappop(heap)
            if g > gs[li][idx]:
                continue
            if gF[li][idx]:
                found = (li, idx)
                break
            expanded += 1
            if expanded > max_expand:
                break
            pl = pT[li]
            bias = layer_bias[li]
            for d, c, o1, o2 in moves:
                j = idx + d
                if not pl[j]:
                    continue
                if o1 and not (pl[idx + o1] and pl[idx + o2]):
                    continue
                ng = g + c * bias
                if ng < gs[li][j]:
                    gs[li][j] = ng
                    par[li][j] = idx * 2 + li
                    heapq.heappush(heap, (ng + h(j), ng, li, j))
            if pV[idx]:
                lj = 1 - li
                if pT[lj][idx]:
                    ng = g + via_cost
                    if ng < gs[lj][idx]:
                        gs[lj][idx] = ng
                        par[lj][idx] = idx * 2 + li
                        heapq.heappush(heap, (ng + h(idx), ng, lj, idx))
        if found is None:
            import os as _os
            np.savez_compressed(_os.path.join(_os.environ.get("TMPDIR", "/tmp"), "route_fail.npz"),
                                pT0=np.frombuffer(bytes(pT[0]), np.uint8).reshape(self.ny, self.nx),
                                pT1=np.frombuffer(bytes(pT[1]), np.uint8).reshape(self.ny, self.nx),
                                pV=np.frombuffer(bytes(pV), np.uint8).reshape(self.ny, self.nx),
                                g0=goal[0], g1=goal[1], s0=src_mask[0], s1=src_mask[1])
            raise RuntimeError(f"route failed for {netname} from {src_pad_xy} (expanded {expanded})")
        # backtrack
        path = []
        li, idx = found
        while True:
            path.append((li, idx))
            p = par[li][idx]
            if p < 0:
                break
            idx, li = p // 2, p % 2
        path.reverse()
        return self._commit(netname, net, path, width, pT)

    def _blob(self, ownmask, x, y):
        """Cells of own copper connected (4-neigh) to the cell at (x,y)."""
        ix, iy = self._cell(x, y)
        m = np.zeros_like(ownmask)
        if not ownmask[iy, ix]:
            # search nearby
            sl = (slice(max(0, iy - 3), iy + 4), slice(max(0, ix - 3), ix + 4))
            ys, xs = np.nonzero(ownmask[sl])
            if len(xs) == 0:
                return m
            iy, ix = ys[0] + sl[0].start, xs[0] + sl[1].start
        stack = [(iy, ix)]
        ny, nx = ownmask.shape
        while stack:
            cy, cx = stack.pop()
            if m[cy, cx]:
                continue
            m[cy, cx] = True
            for ddy, ddx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                yy, xx = cy + ddy, cx + ddx
                if 0 <= yy < ny and 0 <= xx < nx and ownmask[yy, xx] and not m[yy, xx]:
                    stack.append((yy, xx))
        return m

    # --------------------------------------------------------------- output
    def _los(self, pT, a, b):
        (x1, y1), (x2, y2) = a, b
        L = math.hypot(x2 - x1, y2 - y1)
        n = max(2, int(L / (self.res * 0.5)) + 1)
        nx = self.nx
        for k in range(n + 1):
            t = k / n
            fx = (x1 + t * (x2 - x1) - self.x0) / self.res
            fy = (y1 + t * (y2 - y1) - self.y0) / self.res
            i0, j0 = int(math.floor(fx)), int(math.floor(fy))
            cells = {(i0, j0), (i0 + 1, j0), (i0, j0 + 1), (i0 + 1, j0 + 1)}
            if abs(fx - round(fx)) < 1e-6:
                cells = {c for c in cells if c[0] == int(round(fx))}
            if abs(fy - round(fy)) < 1e-6:
                cells = {c for c in cells if c[1] == int(round(fy))}
            for i, j in cells:
                if not pT[j * nx + i]:
                    return False
        return True

    def _simplify(self, pts, pT):
        if len(pts) <= 2:
            return pts
        out = [pts[0]]
        i = 0
        while i < len(pts) - 1:
            j = len(pts) - 1
            while j > i + 1 and not self._los(pT, pts[i], pts[j]):
                j -= 1
            out.append(pts[j])
            i = j
        return out

    def _commit(self, netname, net, path, width, pT):
        runs = []  # (layer, [points])
        cur_l = path[0][0]
        cur = []
        vias = []
        for li, idx in path:
            xy = self._xy(idx % self.nx, idx // self.nx)
            if li != cur_l:
                runs.append((cur_l, cur))
                vias.append(cur[-1])
                cur = [xy]
                cur_l = li
            else:
                cur.append(xy)
        runs.append((cur_l, cur))
        # snap free ends onto own-net track centre lines (KiCad connectivity)
        runs[0] = (runs[0][0], [self._snap(net, runs[0][0], runs[0][1][0])] + runs[0][1])
        runs[-1] = (runs[-1][0], runs[-1][1] + [self._snap(net, runs[-1][0], runs[-1][1][-1])])
        made = []
        for li, pts in runs:
            pts = self._simplify(pts, pT[li])
            if len(pts) >= 2:
                made += self.kb.track(pts, width, LAYERS[li], netname)
                for a, b in zip(pts[:-1], pts[1:]):
                    self.add_prim(("seg", a[0], a[1], b[0], b[1], width / 2), (li,), net)
                    self.segs.setdefault(net, []).append((li, a[0], a[1], b[0], b[1]))
        for x, y in vias:
            self.kb.via(x, y, netname, self.via_d, self.via_drill)
            self.add_prim(("circle", x, y, self.via_d / 2), (0, 1), net)
            self.add_hole(x, y, self.via_drill)
            self.anchors.setdefault(net, []).append(((0, 1), x, y))
        return made, vias

    def _snap(self, net, li, pt):
        x, y = pt
        best = None
        ix, iy = self._cell(x, y)
        on_own = (0 <= ix < self.nx and 0 <= iy < self.ny and self.C[li][iy, ix] == net
                  and not getattr(self, "_exact", False))
        for ls, ax, ay in self.anchors.get(net, []):
            d = math.hypot(ax - x, ay - y)
            if li in ls and d < 1.6 and on_own:
                if best is None or d < best[0]:
                    best = (d, (ax, ay), "anchor")
        if best is not None:
            # end the track exactly in the pad / via centre (robust connectivity)
            ax, ay = best[1]
            jx, jy = self._cell((x + ax) / 2, (y + ay) / 2)
            if self.C[li][jy, jx] == net:
                return best[1]
            return pt
        for sl, x1, y1, x2, y2 in self.segs.get(net, []):
            if sl != li:
                continue
            dx, dy = x2 - x1, y2 - y1
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / L2))
            px, py = x1 + t * dx, y1 + t * dy
            d = math.hypot(px - x, py - y)
            if d < 0.4 and (best is None or d < best[0]):
                best = (d, (px, py), "seg")
        return best[1] if best else pt
