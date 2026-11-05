"""The practice dashboard: one HTML page that your browser reloads by itself."""

import html
from datetime import datetime, timezone

from . import config

COLORS = {"you": "#2a78d6", "simple strategy": "#eb6834", "market": "#8a897f"}


def _chart(series, width=720, height=260, pad=44):
    points = [(t, v) for values in series.values() for t, v in values]
    if len(points) < 1:
        return '<p class="muted">The chart appears after the first round is settled (about 20 minutes).</p>'
    times = sorted({t for t, _ in points})
    lo = min(min(v for _, v in points), config.START_BALANCE)
    hi = max(max(v for _, v in points), config.START_BALANCE)
    span = (hi - lo) or 1.0
    lo, hi = lo - 0.08 * span, hi + 0.08 * span
    x = lambda t: pad + (times.index(t) / max(1, len(times) - 1)) * (width - 2 * pad)  # noqa: E731
    y = lambda v: height - pad + (lo - v) / (hi - lo) * (height - 2 * pad)  # noqa: E731
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Account values">']
    for frac in (0, 0.5, 1):
        v = lo + frac * (hi - lo)
        parts.append(f'<line x1="{pad}" x2="{width - pad}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                     f'<text x="{pad - 6}" y="{y(v) + 4:.1f}" text-anchor="end" class="tick">{v:,.0f}</text>')
    for name, values in series.items():
        if not values:
            continue
        path = " ".join(f"{'M' if i == 0 else 'L'}{x(t):.1f},{y(v):.1f}" for i, (t, v) in enumerate(values))
        t_last, v_last = values[-1]
        parts.append(f'<path d="{path}" fill="none" stroke="{COLORS[name]}" stroke-width="2"/>'
                     f'<circle cx="{x(t_last):.1f}" cy="{y(v_last):.1f}" r="4" fill="{COLORS[name]}"/>')
    parts.append(f'<text x="{pad}" y="{height - 12}" class="tick">{times[0]:%H:%M}</text>'
                 f'<text x="{width - pad}" y="{height - 12}" text-anchor="end" class="tick">{times[-1]:%H:%M} UTC</text>')
    parts.append("</svg>")
    return "".join(parts)


def write(path, practice, next_event):
    latest = {name: (values[-1][1] if values else config.START_BALANCE) for name, values in practice.values.items()}
    rows = "".join(
        f'<tr><td><span class="dot" style="background:{COLORS[n]}"></span>{html.escape(n)}</td>'
        f'<td class="num">{v:,.1f} TAO</td><td class="num">{100 * (v / config.START_BALANCE - 1):+.1f}%</td></tr>'
        for n, v in sorted(latest.items(), key=lambda item: -item[1]))
    weights = practice.sent.get("you") or {}
    picks = ", ".join(f"{k}: {v:.2f}" for k, v in sorted(weights.items())) or "none yet"
    target = next_event.isoformat() if next_event else ""
    page = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="refresh" content="20">
<title>Practice game</title><style>
:root {{ --bg:#fbfbf9; --ink:#1a1a19; --muted:#6b6a63; --grid:#e4e3dd; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#1a1a19; --ink:#f0efec; --muted:#c3c2b7; --grid:#3a3a37; }} }}
body {{ background:var(--bg); color:var(--ink); font:15px/1.45 system-ui, sans-serif; margin:0 auto; max-width:760px; padding:16px; }}
h1 {{ font-size:20px; margin:8px 0 4px; }} .muted, .tick {{ color:var(--muted); fill:var(--muted); font-size:12px; }}
.grid {{ stroke:var(--grid); }} table {{ border-collapse:collapse; width:100%; margin:12px 0; }}
td {{ padding:6px 4px; border-bottom:1px solid var(--grid); }} .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.dot {{ display:inline-block; width:10px; height:10px; border-radius:5px; margin-right:8px; }} svg {{ width:100%; height:auto; }}
</style></head><body>
<h1>Practice game</h1>
<p class="muted">Live subnet prices, the event's rules. Next step <b id="next">{html.escape(target[11:16]) if target else "-"}</b>
<span id="left"></span>. This page reloads every 20 seconds.</p>
<table>{rows}</table>
{_chart(practice.values)}
<p><b>Your latest weights:</b> {html.escape(picks)}</p>
<p class="muted">Rounds settled: {len(practice.rounds)}. Updated {datetime.now(timezone.utc):%H:%M:%S} UTC.</p>
<script>const t = "{target}"; if (t) {{ const s = Math.max(0, Math.round((new Date(t) - new Date()) / 1000));
document.getElementById("left").textContent = "(in " + Math.floor(s / 60) + " min " + (s % 60) + " s)"; }}</script>
</body></html>"""
    with open(path, "w") as handle:
        handle.write(page)
