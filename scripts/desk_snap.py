# /// script
# requires-python = ">=3.10"
# dependencies = ["opencv-python", "numpy"]
# ///
"""Capture a paper diagram from the MacBook Desk View camera, auto-crop and clean it.

Two modes:

  Live (recommended):
      uv run desk_snap.py --live [-o OUTDIR]
    Opens a preview window of the Desk View feed with the detected sheet outlined
    in green. SPACE captures and processes a frame (results open in Preview);
    Q or ESC quits. Capture as many as you like per session.

  One-shot:
      uv run desk_snap.py [-o OUTDIR] [--stem NAME]
    ffmpeg grabs ~45 successive frames (auto-exposure warm-up, last frame wins),
    then the same processing runs on that single frame.

Processing pipeline:
  1. Detect the sheet: largest convex quadrilateral from Canny contours, falling
     back to the largest bright region's min-area rectangle.
  2. Perspective-warp the sheet to a straight-on rectangle.
  3. Clean up: flatten illumination (divide by large-kernel blur), stretch contrast.

Outputs <stem>_raw.jpg (full frame), <stem>_crop.png (color crop),
<stem>_clean.png (flattened grayscale) in the output directory.
"""

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

WARMUP_FRAMES = 45  # ~1.5 s at 30 fps for auto-exposure to settle (one-shot mode)


def resolve_device(name_hint: str = "Desk View") -> int:
    """Find the AVFoundation video device whose name contains name_hint.

    Device indices are NOT stable across machines (an external camera shifts
    everything down), so resolve by name at runtime.
    """
    res = subprocess.run(
        ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True, text=True,
    )
    devices = re.findall(r"\[(\d+)\] ([^\n]+)", res.stderr.split(
        "AVFoundation audio devices")[0])
    for idx, name in devices:
        if name_hint.lower() in name.lower():
            return int(idx)
    listing = "\n".join(f"  [{i}] {n}" for i, n in devices)
    sys.exit(f"no camera matching {name_hint!r} found. Video devices:\n{listing}")


def probe_size(device: int) -> tuple[int, int]:
    """Ask the device for its supported modes and pick the largest."""
    res = subprocess.run(
        ["ffmpeg", "-f", "avfoundation", "-framerate", "30",
         "-video_size", "1x1", "-i", str(device)],
        capture_output=True, text=True,
    )
    modes = re.findall(r"(\d{3,})x(\d{3,})@", res.stderr)
    if not modes:
        return 1920, 1440  # sensible default for Desk View
    return max(((int(w), int(h)) for w, h in modes), key=lambda wh: wh[0] * wh[1])


def order_corners(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as top-left, top-right, bottom-right, bottom-left."""
    pts = pts.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array(
        [pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]],
        dtype=np.float32,
    )


def hull_quad(contour: np.ndarray) -> np.ndarray:
    """Approximate a contour's convex hull down to exactly 4 corners."""
    hull = cv2.convexHull(contour)
    for eps_frac in np.arange(0.01, 0.15, 0.01):
        approx = cv2.approxPolyDP(hull, eps_frac * cv2.arcLength(hull, True), True)
        if len(approx) == 4:
            return order_corners(approx)
        if len(approx) < 4:
            break
    return order_corners(cv2.boxPoints(cv2.minAreaRect(contour)))


def quad_area(q: np.ndarray) -> float:
    return cv2.contourArea(q.astype(np.float32).reshape(-1, 1, 2))


def find_papers(img: np.ndarray, _achro_floor: float = 0.6) -> list[np.ndarray]:
    """Return corner sets for ALL paper-like regions, largest first.

    Generalized "uniform hue + four edges" detector (validated on 60 frames of
    a sheet being moved/held/tilted plus white-sheet + green-post-it scenes):
    the frame is segmented into 12 wrap-aware hue bins (saturated pixels) plus
    an achromatic-bright bin (white paper, incl. its blue tint in shadow —
    measured hue ~109 at S up to ~80). Any color of paper/post-it forms a
    candidate; each must pass shape gates — area, aspect, the convex hull
    reducing to ~4 corners (quad/hull area ≥ 0.8; the 4-corner fit inscribes
    the hull, so real rounded-corner sheets score 0.85-0.91), the region
    filling that quad, and scene-relative brightness. Warm (skin-range) hues
    pass stricter gates since hands/arms live there, and small border-touching
    regions are rejected (forearm slivers beyond the watch, rug corners) —
    real sheets at the border are much larger. Edge/Canny approaches fail
    whenever a hand touches the sheet (1/60 frames); the hull fills
    finger-shaped occlusion bites.
    """
    blur = cv2.GaussianBlur(img, (9, 9), 0)
    hsv = cv2.cvtColor(blur, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    frame_area = img.shape[0] * img.shape[1]
    fh, fw = img.shape[:2]
    v_ref = np.percentile(v, 99)
    min_area = 0.012 * frame_area

    bins = []
    sat = s > 60
    for b in range(12):
        lo, hi = b * 15, (b + 1) * 15
        m = sat & (h >= lo) & (h < hi)
        if b == 0:  # wrap: merge the top sliver so red/pink isn't split
            m = m | (sat & (h >= 172))
        bins.append((m, lo < 25 or lo >= 165))
    bins.append(((s <= 90) & (v > _achro_floor * v_ref), False))

    results = []
    for m, warm in bins:
        if np.count_nonzero(m) < min_area:
            continue
        mask = m.astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            if area < min_area:
                continue
            rect = cv2.minAreaRect(c)
            rw, rh = rect[1]
            if min(rw, rh) == 0 or max(rw, rh) / min(rw, rh) > 6:
                continue
            bx, by, bw, bh = cv2.boundingRect(c)
            touches = (bx <= 2 or by <= 2
                       or bx + bw >= fw - 2 or by + bh >= fh - 2)
            if touches and area < 0.03 * frame_area:
                continue
            q = hull_quad(c)
            qa = quad_area(q)
            if qa <= 0:
                continue
            quad_fill = area / qa
            hull_a = cv2.contourArea(cv2.convexHull(c))
            quad_vs_hull = qa / max(hull_a, 1)
            mm = np.zeros(img.shape[:2], np.uint8)
            cv2.drawContours(mm, [c], -1, 255, -1)
            mean_v = cv2.mean(v, mask=mm)[0]
            # overexposed skin desaturates into the achromatic bin; unlike a
            # real sheet, such patches are SURROUNDED by more skin — reject
            # candidates whose neighborhood band is mostly warm-hued
            band = cv2.dilate(mm, np.ones((31, 31), np.uint8)) & ~mm
            warm_px = ((h < 24) | (h > 165)) & (s > 60)
            band_n = np.count_nonzero(band)
            skin_frac = (np.count_nonzero(warm_px & (band > 0)) / band_n
                         if band_n else 0.0)
            if skin_frac > 0.35:
                continue
            if warm:
                ok = (quad_vs_hull >= 0.88 and quad_fill >= 0.85
                      and mean_v >= 0.65 * v_ref)
            else:
                # thick post-it pads show side faces (pentagon-ish hull) —
                # allow a weaker quad fit when the region is clearly bright
                quad_ok = (quad_vs_hull >= 0.80
                           or (quad_vs_hull >= 0.72 and mean_v >= 0.70 * v_ref))
                ok = (quad_ok and quad_fill >= 0.65
                      and mean_v >= 0.55 * v_ref)
            results.append((q, area, mean_v / v_ref, ok))

    passing = [(q, a) for q, a, vr, ok in results if ok]
    if not passing and results:
        # nothing passed the strict gates — usually the sheet merged with a
        # screen-glow patch. Re-segment with a stricter brightness floor to
        # split the merge; if that still fails, take the best bright candidate.
        if _achro_floor < 0.75:
            resegmented = find_papers(img, _achro_floor=0.78)
            if resegmented:
                return resegmented
        results.sort(key=lambda r: -(r[1] * r[2] ** 2))
        passing = [(results[0][0], results[0][1])]

    # non-max suppression: the same region can surface from adjacent hue bins
    passing.sort(key=lambda r: -r[1])
    kept = []
    for q, area in passing:
        dup = False
        for kq, _ in kept:
            inter, _ = cv2.intersectConvexConvex(
                q.reshape(-1, 1, 2), kq.reshape(-1, 1, 2))
            if inter > 0.5 * min(quad_area(q), quad_area(kq)):
                dup = True
                break
        if not dup:
            kept.append((q, area))
    return [q for q, _ in kept]


def warp(img: np.ndarray, corners: np.ndarray) -> np.ndarray:
    (tl, tr, br, bl) = corners
    w = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    h = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(img, m, (w, h))


def clean(img: np.ndarray) -> np.ndarray:
    """Flatten uneven lighting, then aggressive stretch + gamma.

    Chosen over adaptive threshold / CLAHE / sigmoid alternatives: keeps faint
    pencil strokes (dashed lines survive) while pushing paper to clean white.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bg = cv2.GaussianBlur(gray, (0, 0), sigmaX=25)
    flat = cv2.divide(gray, bg, scale=255)
    black = np.percentile(flat, 0.1)
    x = np.clip((flat.astype(np.float32) - black) / max(248 - black, 1), 0, 1)
    return (np.power(x, 3.0) * 255).astype(np.uint8)


def rotate_if_needed(img: np.ndarray, rotate: int) -> np.ndarray:
    if not rotate:
        return img
    rot = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
           270: cv2.ROTATE_90_COUNTERCLOCKWISE}[rotate]
    return cv2.rotate(img, rot)


def process_frame(img: np.ndarray, outdir: Path, stem: str,
                  open_results: bool = False) -> list[Path]:
    """Detect all sheets, warp + clean each, save. Returns clean paths."""
    raw_path = outdir / f"{stem}_raw.jpg"
    cv2.imwrite(str(raw_path), img)

    regions = find_papers(img)
    if not regions:
        print(f"no paper found; raw frame at {raw_path}")
        if open_results:
            subprocess.run(["open", str(raw_path)])
        return []

    print(f"raw:   {raw_path}")
    to_open, clean_paths = [], []
    for i, corners in enumerate(regions, 1):
        cropped = warp(img, corners)
        crop_path = outdir / f"{stem}_crop{i}.png"
        clean_path = outdir / f"{stem}_clean{i}.png"
        cv2.imwrite(str(crop_path), cropped)
        cv2.imwrite(str(clean_path), clean(cropped))
        print(f"  [{i}] crop: {crop_path}\n  [{i}] clean: {clean_path}")
        to_open += [str(crop_path), str(clean_path)]
        clean_paths.append(clean_path)
    if open_results:
        subprocess.run(["open", *to_open])
    return clean_paths


def capture_oneshot(device: int, size: tuple[int, int], out_path: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-f", "avfoundation",
        "-framerate", "30", "-video_size", f"{size[0]}x{size[1]}",
        "-i", str(device),
        "-frames:v", str(WARMUP_FRAMES), "-update", "1",
        str(out_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not out_path.exists():
        sys.exit(f"ffmpeg capture failed:\n{res.stderr[-2000:]}")


def live(device: int, size: tuple[int, int], outdir: Path, stem: str,
         rotate: int, once: bool = False) -> None:
    # OpenCV's AVFoundation backend can't see the virtual Desk View camera,
    # so ffmpeg does the capture and pipes raw BGR frames to us.
    cap_w, cap_h = size
    frame_bytes = cap_w * cap_h * 3
    proc = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "avfoundation", "-framerate", "30",
         "-video_size", f"{cap_w}x{cap_h}", "-i", str(device),
         "-vf", "fps=15", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    def read_frame() -> np.ndarray | None:
        buf = b""
        while len(buf) < frame_bytes:
            chunk = proc.stdout.read(frame_bytes - len(buf))
            if not chunk:
                return None
            buf += chunk
        return np.frombuffer(buf, np.uint8).reshape(cap_h, cap_w, 3)

    win = "Desk View  |  SPACE = capture   R = flip 180   Q/ESC = quit"
    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
    shot = 0
    flash_until = 0.0
    rot = rotate  # current rotation; R toggles an extra 180 at runtime
    print("Live preview running. Green outline = detected sheet. "
          "SPACE captures, R flips 180, Q/ESC quits.")

    while True:
        frame = read_frame()
        if frame is None:
            err = proc.stderr.read().decode(errors="replace")[-2000:]
            cv2.destroyAllWindows()
            sys.exit(f"camera stream ended unexpectedly:\n{err}")
        frame = rotate_if_needed(frame, rot)

        disp = cv2.resize(frame, None, fx=0.5, fy=0.5,
                          interpolation=cv2.INTER_AREA)
        for corners in find_papers(disp):
            cv2.polylines(disp, [corners.astype(int)], True, (0, 255, 0), 2)
        if time.monotonic() < flash_until:
            cv2.putText(disp, f"captured #{shot}", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        cv2.imshow(win, disp)

        k = cv2.waitKey(1) & 0xFF
        if k in (27, ord("q")):
            break
        if k == ord("r"):
            rot = (rot + 180) % 360
            print(f"rotation now {rot} deg")
        if k == 32:  # space
            shot += 1
            ts = time.strftime("%H%M%S")
            clean_paths = process_frame(frame, outdir, f"{stem}_{ts}",
                                        open_results=not once)
            flash_until = time.monotonic() + 1.5
            if once:
                print(f"CAPTURED {len(clean_paths)} region(s)")
                break

    proc.terminate()
    cv2.destroyAllWindows()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Capture and clean paper diagrams from the Desk View camera")
    ap.add_argument("-o", "--outdir", type=Path, default=Path.cwd())
    ap.add_argument("--stem", default="desk")
    ap.add_argument("--device", type=int, default=None,
                    help="camera device index; default auto-detects the "
                         "device named 'Desk View'")
    ap.add_argument("--rotate", type=int, default=0, choices=[0, 90, 180, 270],
                    help="starting rotation; in live mode the R key toggles "
                         "an extra 180 at any time (crops match the preview)")
    ap.add_argument("--live", action="store_true",
                    help="live preview window; SPACE to capture")
    ap.add_argument("--once", action="store_true",
                    help="with --live: SPACE captures once and closes the "
                         "preview; results are not opened in Preview "
                         "(paths on stdout instead)")
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    device = args.device if args.device is not None else resolve_device()
    size = probe_size(device)

    if args.live:
        live(device, size, args.outdir, args.stem, args.rotate,
             once=args.once)
        return

    raw_path = args.outdir / f"{args.stem}_raw.jpg"
    capture_oneshot(device, size, raw_path)
    img = cv2.imread(str(raw_path))
    if img is None:
        sys.exit(f"could not read captured frame {raw_path}")
    process_frame(rotate_if_needed(img, args.rotate), args.outdir, args.stem)


if __name__ == "__main__":
    main()
