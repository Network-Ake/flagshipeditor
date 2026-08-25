// The waveform strip — the hero element of the review and analysis tabs.
//
// It is drawn in real pixels rather than a stretched viewBox: a CEP panel is
// resized constantly and `preserveAspectRatio="none"` would squash every beat
// tick and cut marker by a different factor at every width. The container is
// measured, the SVG uses a 1:1 coordinate space, and every mark lands on a
// whole pixel.
//
// Five lanes, top to bottom:
//   cut markers · waveform (mirrored RMS) · beat ticks · bass onsets · section ribbon

import React, { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { BeatAnalysis, BeatSection } from "../lib/python";
import { sectionColor } from "../lib/sections";

export interface WaveformCut {
  beatTime: number;
  endTime: number;
  sectionType: string;
}

interface Props {
  analysis?: BeatAnalysis | null;
  cuts?: WaveformCut[];
  height?: number;
  selected?: number | null;
  playhead?: number | null;
  onSelectCut?: (index: number) => void;
  onSeek?: (time: number) => void;
  label?: string;
}

const BAR_PITCH = 2; // 1px bar, 1px gutter
const MARKER_LANE = 9;
const RIBBON_LANE = 4;
const BASS_LANE = 5;
const BEAT_LANE = 8;
const MIN_TICK_GAP = 2; // px — below this, ticks smear into a solid block

/** Container width in CSS pixels, kept current across panel resizes. */
function useMeasuredWidth(): [React.RefObject<HTMLDivElement>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return undefined;
    const measure = () => setWidth(node.clientWidth);
    measure();

    // CEF 64+ has ResizeObserver; older CEP hosts fall back to window resize,
    // which a panel drag still fires.
    const Observer = (window as unknown as { ResizeObserver?: typeof ResizeObserver }).ResizeObserver;
    if (Observer) {
      const observer = new Observer(measure);
      observer.observe(node);
      return () => observer.disconnect();
    }
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  return [ref, width];
}

/** Peak-per-bucket downsample: keeps transients that an average would erase. */
function buildPeaks(energy: number[] | undefined, buckets: number): number[] {
  if (!energy || energy.length === 0 || buckets <= 0) return [];
  const perBucket = energy.length / buckets;
  const peaks: number[] = [];
  let maximum = 0;
  for (let index = 0; index < buckets; index += 1) {
    const start = Math.floor(index * perBucket);
    const end = Math.max(start + 1, Math.floor((index + 1) * perBucket));
    let peak = 0;
    for (let sample = start; sample < end && sample < energy.length; sample += 1) {
      const value = energy[sample];
      if (Number.isFinite(value) && value > peak) peak = value;
    }
    peaks.push(peak);
    if (peak > maximum) maximum = peak;
  }
  if (maximum <= 0) return [];
  // A mild gamma lifts verse-level detail without clipping the drop.
  return peaks.map((peak) => Math.pow(peak / maximum, 0.8));
}

/** Section spans inferred from the cut list, for the no-analysis case. */
function sectionsFromCuts(cuts: WaveformCut[]): BeatSection[] {
  const spans: BeatSection[] = [];
  for (const cut of cuts) {
    const last = spans[spans.length - 1];
    if (last && last.type === cut.sectionType) {
      last.end = Math.max(last.end, cut.endTime);
      continue;
    }
    spans.push({ type: cut.sectionType, start: cut.beatTime, end: cut.endTime });
  }
  return spans;
}

/** Drop ticks that would land on a pixel already covered by the previous one. */
function thinTicks(times: number[], toX: (time: number) => number, width: number): number[] {
  const kept: number[] = [];
  let previous = -Infinity;
  for (const time of times) {
    const x = toX(time);
    if (x < 0 || x > width) continue;
    if (x - previous < MIN_TICK_GAP) continue;
    kept.push(Math.round(x) + 0.5);
    previous = x;
  }
  return kept;
}

const Waveform: React.FC<Props> = ({
  analysis,
  cuts,
  height = 80,
  selected = null,
  playhead = null,
  onSelectCut,
  onSeek,
  label = "Track waveform",
}) => {
  const [ref, width] = useMeasuredWidth();
  const cutList = cuts || [];

  const duration = useMemo(() => {
    if (analysis && analysis.duration > 0) return analysis.duration;
    let end = 0;
    for (const cut of cutList) if (cut.endTime > end) end = cut.endTime;
    return end > 0 ? end : 1;
  }, [analysis, cutList]);

  const geometry = useMemo(() => {
    const waveTop = MARKER_LANE;
    const waveBottom = height - RIBBON_LANE - BASS_LANE - BEAT_LANE;
    const waveHeight = Math.max(8, waveBottom - waveTop);
    return {
      waveTop,
      waveBottom,
      center: waveTop + waveHeight / 2,
      half: waveHeight / 2,
      beatTop: waveBottom,
      bassTop: waveBottom + BEAT_LANE,
      ribbonTop: height - RIBBON_LANE,
    };
  }, [height]);

  const toX = useCallback(
    (time: number) => (Math.max(0, Math.min(duration, time)) / duration) * width,
    [duration, width]
  );

  const peaks = useMemo(
    () => buildPeaks(analysis?.energy, Math.max(1, Math.floor(width / BAR_PITCH))),
    [analysis, width]
  );

  const sections = useMemo(() => {
    if (analysis && analysis.sections.length > 0) return analysis.sections;
    return sectionsFromCuts(cutList);
  }, [analysis, cutList]);

  const beatTicks = useMemo(
    () => (width > 0 && analysis ? thinTicks(analysis.beats, toX, width) : []),
    [analysis, toX, width]
  );
  const downbeatTicks = useMemo(
    () => (width > 0 && analysis ? thinTicks(analysis.downbeats, toX, width) : []),
    [analysis, toX, width]
  );
  const bassTicks = useMemo(
    () => (width > 0 && analysis ? thinTicks(analysis.bass_onsets, toX, width) : []),
    [analysis, toX, width]
  );

  const nearestCut = useCallback(
    (time: number) => {
      let best = -1;
      let bestGap = Infinity;
      for (let index = 0; index < cutList.length; index += 1) {
        const gap = Math.abs(cutList[index].beatTime - time);
        if (gap < bestGap) {
          bestGap = gap;
          best = index;
        }
      }
      return best;
    },
    [cutList]
  );

  const handleSurfaceClick = (event: React.MouseEvent<SVGSVGElement>) => {
    if (width <= 0) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const time = ((event.clientX - bounds.left) / bounds.width) * duration;
    if (onSeek) onSeek(Math.max(0, Math.min(duration, time)));
    if (onSelectCut) {
      const index = nearestCut(time);
      if (index >= 0) onSelectCut(index);
    }
  };

  const hasData = peaks.length > 0 || cutList.length > 0 || sections.length > 0;

  return (
    <div className="waveform" ref={ref} style={{ height }}>
      {width > 0 && hasData && (
        <svg
          className="waveform-svg"
          width={width}
          height={height}
          role="img"
          aria-label={label}
          onClick={handleSurfaceClick}
        >
          {/* Section bands sit behind the wave so the structure reads at a glance. */}
          {sections.map((section) => {
            const x = toX(section.start);
            const bandWidth = Math.max(1, toX(section.end) - x);
            return (
              <rect
                key={`band-${section.type}-${section.start}`}
                x={x}
                y={geometry.waveTop}
                width={bandWidth}
                height={geometry.waveBottom - geometry.waveTop}
                fill={sectionColor(section.type)}
                opacity={0.1}
              />
            );
          })}

          {/* Mirrored RMS — the shape an editor recognises as "the track". */}
          <g className="waveform-bars">
            {peaks.map((peak, index) => {
              const barHeight = Math.max(1, peak * geometry.half);
              return (
                <rect
                  key={`bar-${index}`}
                  x={index * BAR_PITCH}
                  y={geometry.center - barHeight}
                  width={1}
                  height={barHeight * 2}
                />
              );
            })}
          </g>
          {peaks.length === 0 && (
            <line
              className="waveform-baseline"
              x1={0}
              x2={width}
              y1={geometry.center}
              y2={geometry.center}
            />
          )}

          {/* Beat grid: every beat short, every downbeat full and brighter. */}
          <g className="waveform-beats">
            {beatTicks.map((x) => (
              <line key={`beat-${x}`} x1={x} x2={x} y1={geometry.beatTop + 4} y2={geometry.beatTop + 8} />
            ))}
          </g>
          <g className="waveform-downbeats">
            {downbeatTicks.map((x) => (
              <line key={`down-${x}`} x1={x} x2={x} y1={geometry.beatTop} y2={geometry.beatTop + 8} />
            ))}
          </g>

          {/* 808 / bass onsets — what the cutting engine syncs hard cuts to. */}
          <g className="waveform-bass">
            {bassTicks.map((x) => (
              <line key={`bass-${x}`} x1={x} x2={x} y1={geometry.bassTop} y2={geometry.bassTop + 4} />
            ))}
          </g>

          {/* Section ribbon: a solid, unambiguous read of the song structure. */}
          {sections.map((section) => {
            const x = toX(section.start);
            const bandWidth = Math.max(1, toX(section.end) - x);
            return (
              <rect
                key={`ribbon-${section.type}-${section.start}`}
                x={x}
                y={geometry.ribbonTop}
                width={bandWidth}
                height={RIBBON_LANE}
                fill={sectionColor(section.type)}
                opacity={0.85}
              />
            );
          })}

          {/* Cut markers. The hit rect is wider than the glyph so a 7px triangle
              is still clickable in a 320px panel. */}
          <g className="waveform-cuts">
            {cutList.map((cut, index) => {
              const x = Math.round(toX(cut.beatTime)) + 0.5;
              const isSelected = selected === index;
              const half = isSelected ? 4.5 : 3.5;
              const tip = isSelected ? MARKER_LANE : MARKER_LANE - 2;
              return (
                <g key={`cut-${index}-${cut.beatTime}`}>
                  <polygon
                    className={`cut-marker${isSelected ? " selected" : ""}`}
                    points={`${x - half},0 ${x + half},0 ${x},${tip}`}
                    fill={isSelected ? "var(--accent-primary)" : sectionColor(cut.sectionType)}
                  />
                  {onSelectCut && (
                    <rect
                      className="cut-marker-hit"
                      x={x - 5}
                      y={0}
                      width={10}
                      height={MARKER_LANE + 4}
                      onClick={(event) => {
                        event.stopPropagation();
                        onSelectCut(index);
                      }}
                    >
                      <title>{`Cut ${index + 1} · ${cut.sectionType}`}</title>
                    </rect>
                  )}
                </g>
              );
            })}
          </g>

          {playhead !== null && playhead >= 0 && (
            <line
              className="waveform-playhead"
              x1={Math.round(toX(playhead)) + 0.5}
              x2={Math.round(toX(playhead)) + 0.5}
              y1={0}
              y2={height}
            />
          )}
        </svg>
      )}
    </div>
  );
};

export default Waveform;
