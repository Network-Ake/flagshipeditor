import React, { useState, useMemo } from "react";
import { getAvailableStyles } from "../lib/styles";

interface Props {
  selected: string;
  onSelect: (style: string) => void;
}

const STYLE_DESCRIPTIONS: Record<string, string> = {
  lyrical_lemonade: "Colorful, chaotic, cartoon explosions — Cole Bennett energy.",
  ninetive: "Fast cuts, RGB splits, and aggressive trap transitions.",
  jack_rottier: "Cinematic, slow push-ins, film grain, emotional pacing.",
  worldwide_films: "Dark trap / drill with masked transitions and strobe.",
  cmd_command_drill: "UK drill: command-line overlays, glitch, strobe on 808s.",
  custom: "Build your own look with full manual control.",
};

const STYLE_GRADIENTS: Record<string, string> = {
  lyrical_lemonade: "linear-gradient(135deg, #f59e0b, #ec4899, #6366f1)",
  ninetive: "linear-gradient(135deg, #ef4444, #8b5cf6)",
  jack_rottier: "linear-gradient(135deg, #10b981, #3b82f6)",
  worldwide_films: "linear-gradient(135deg, #1f2937, #6366f1)",
  cmd_command_drill: "linear-gradient(135deg, #6366f1, #ec4899)",
  custom: "linear-gradient(135deg, #71717a, #a1a1aa)",
};

const StyleSelector: React.FC<Props> = ({ selected, onSelect }) => {
  const styles = getAvailableStyles();
  const [filter, setFilter] = useState("");

  const filtered = useMemo(() => {
    const q = filter.toLowerCase();
    return styles.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        (STYLE_DESCRIPTIONS[s.id] || "").toLowerCase().includes(q)
    );
  }, [styles, filter]);

  return (
    <div className="style-selector">
      <div className="style-search">
        <span className="style-search-icon">🔍</span>
        <input
          type="text"
          className="search-input"
          placeholder="Search styles..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>

      <div className="style-grid">
        {filtered.map((style) => (
          <div
            key={style.id}
            className={`style-card ${selected === style.id ? "selected" : ""}`}
            onClick={() => onSelect(style.id)}
            role="button"
            aria-pressed={selected === style.id}
          >
            <div
              className="style-preview"
              style={{ backgroundImage: STYLE_GRADIENTS[style.id] }}
            />
            <div className="style-name">{style.name}</div>
            <div className="style-desc">
              {STYLE_DESCRIPTIONS[style.id] || "Custom editing style."}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default StyleSelector;
