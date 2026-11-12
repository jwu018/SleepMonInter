import type uPlot from "uplot";

// Draws annotation markers on top of a uPlot chart: a vertical line for a moment, a shaded
// band for a stretch, and a small numbered flag at the top so markers match the list.
// x values are in the chart's own x units (unix seconds on the night view, seconds since
// start on uploads).

export interface ChartMarker {
  x_start: number;
  x_end: number | null;
  label: string; // usually the number shown in the list
  /** Highlight the marker currently being edited or previewed. */
  active?: boolean;
}

export function markerPlugin(markers: ChartMarker[], color: string): uPlot.Plugin {
  return {
    hooks: {
      draw: (u) => {
        if (markers.length === 0) return;
        const { ctx } = u;
        const { top, height, left, width } = u.bbox;
        const dpr = window.devicePixelRatio || 1;
        ctx.save();
        ctx.beginPath();
        ctx.rect(left, top, width, height); // don't draw outside the plot area
        ctx.clip();
        for (const m of markers) {
          const x0 = u.valToPos(m.x_start, "x", true);
          const x1 = m.x_end === null ? x0 : u.valToPos(m.x_end, "x", true);
          if (x1 < left || x0 > left + width) continue;

          ctx.fillStyle = color;
          if (m.x_end !== null) {
            ctx.globalAlpha = m.active ? 0.25 : 0.14;
            ctx.fillRect(x0, top, Math.max(1, x1 - x0), height);
          }
          ctx.globalAlpha = 1;
          ctx.strokeStyle = color;
          ctx.lineWidth = (m.active ? 3 : 2) * dpr;
          ctx.beginPath();
          ctx.moveTo(x0, top);
          ctx.lineTo(x0, top + height);
          ctx.stroke();

          // Numbered flag.
          const fontPx = 11 * dpr;
          ctx.font = `600 ${fontPx}px system-ui, sans-serif`;
          const pad = 3 * dpr;
          const w = ctx.measureText(m.label).width + pad * 2;
          ctx.fillRect(x0, top, w, fontPx + pad * 2);
          ctx.fillStyle = "#ffffff";
          ctx.textBaseline = "top";
          ctx.fillText(m.label, x0 + pad, top + pad);
        }
        ctx.restore();
      },
    },
  };
}
