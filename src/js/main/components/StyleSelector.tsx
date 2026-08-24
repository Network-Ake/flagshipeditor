import React, { useEffect, useMemo, useState } from "react";
import {
  StyleConfig,
  describeStyleEffects,
  getAvailableStyles,
  parseStyleJson,
  styleToJson,
} from "../lib/styles";

interface Props {
  selected: string;
  style: StyleConfig;
  customized: boolean;
  onSelect: (styleId: string) => void;
  onCustomize: (styleId: string, style: StyleConfig) => void;
  onResetCustomization: (styleId: string) => void;
}

const StyleSelector: React.FC<Props> = ({
  selected,
  style,
  customized,
  onSelect,
  onCustomize,
  onResetCustomization,
}) => {
  const styles = useMemo(() => getAvailableStyles(), []);
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => styleToJson(style));
  const [editError, setEditError] = useState("");

  useEffect(() => {
    setDraft(styleToJson(style));
    setEditError("");
  }, [style, selected]);

  const filtered = useMemo(() => {
    const query = filter.trim().toLowerCase();
    if (!query) return styles;
    return styles.filter(
      (entry) =>
        entry.name.toLowerCase().includes(query) || entry.description.toLowerCase().includes(query)
    );
  }, [styles, filter]);

  const effects = useMemo(() => describeStyleEffects(style), [style]);

  const handleSave = () => {
    try {
      onCustomize(selected, parseStyleJson(draft));
      setEditError("");
      setEditing(false);
    } catch (error) {
      setEditError((error as Error).message);
    }
  };

  return (
    <div className="style-selector">
      <div className="style-search">
        <span className="style-search-icon">🔍</span>
        <input
          type="text"
          className="search-input"
          placeholder="Search styles..."
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
      </div>

      {filtered.length === 0 ? (
        <div className="empty-state">No style matches “{filter}”.</div>
      ) : (
        <div className="style-grid">
          {filtered.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={`style-card ${selected === entry.id ? "selected" : ""}`}
              onClick={() => onSelect(entry.id)}
              aria-pressed={selected === entry.id}
            >
              <div className="style-preview" style={{ backgroundImage: entry.accent }} />
              <div className="style-name">{entry.name}</div>
              <div className="style-desc">{entry.description}</div>
            </button>
          ))}
        </div>
      )}

      <div className="param-section">
        <div className="param-section-title">
          <span>✨</span> Effects in {style.display_name}
          {customized && <span className="badge badge-warning">edited</span>}
        </div>
        {effects.on.length === 0 ? (
          <div className="empty-state">
            This preset enables no effect on its own — switch effects on in the Params tab.
          </div>
        ) : (
          <div className="chip-row">
            {effects.on.map((label) => (
              <span key={label} className="chip chip-on">
                {label}
              </span>
            ))}
          </div>
        )}
        {effects.available.length > 0 && (
          <>
            <div className="param-hint">Declared but off — enable them in Params:</div>
            <div className="chip-row">
              {effects.available.map((label) => (
                <span key={label} className="chip">
                  {label}
                </span>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="param-section">
        <div className="param-section-title">
          <span>🧾</span> Preset source
          <button className="link-btn" onClick={() => setEditing((value) => !value)}>
            {editing ? "Close" : "Edit JSON"}
          </button>
        </div>
        {editing && (
          <div className="style-editor">
            <textarea
              className="code-editor"
              spellCheck={false}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />
            {editError && <div className="alert alert-error alert-inline">{editError}</div>}
            <div className="editor-actions">
              <button className="btn btn-sm" onClick={handleSave}>
                Apply to this session
              </button>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => {
                  onResetCustomization(selected);
                  setEditError("");
                }}
                disabled={!customized}
              >
                Reset to shipped preset
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default StyleSelector;
