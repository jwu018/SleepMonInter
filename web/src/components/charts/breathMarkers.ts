import type uPlot from "uplot";

// Draws a small marker on every detected breath: a down-triangle at each inhale peak and an
// up-triangle at each exhale trough, at (seconds since start, signal value).

export interface BreathPoint {
  x: number;
  y: number;
}

export function breathMarkersPlugin(peaks: BreathPoint[], troughs: BreathPoint[], color: string): uPlot.Plugin {
  const drawTriangle = (ctx: CanvasRenderingContext2D, cx: number, cy: number, size: number, down: boolean) => {
    ctx.beginPath();
    const dir = down ? -1 : 1;
    ctx.moveTo(cx - size, cy + dir * size);
    ctx.lineTo(cx + size, cy + dir * size);
    ctx.lineTo(cx, cy);
    ctx.closePath();
    ctx.fill();
  };
  return {
    hooks: {
      draw: (u) => {
        const { ctx } = u;
        const { left, top, width, height } = u.bbox;
        const size = 4 * (window.devicePixelRatio || 1);
        const xMin = u.scales.x.min ?? -Infinity;
        const xMax = u.scales.x.max ?? Infinity;
        ctx.save();
        ctx.beginPath();
        ctx.rect(left, top, width, height);
        ctx.clip();
        ctx.fillStyle = color;
        for (const [list, down] of [[peaks, true], [troughs, false]] as const) {
          for (const p of list) {
            if (p.x < xMin || p.x > xMax || !Number.isFinite(p.y)) continue;
            drawTriangle(ctx, u.valToPos(p.x, "x", true), u.valToPos(p.y, "y", true), size, down);
          }
        }
        ctx.restore();
      },
    },
  };
}
