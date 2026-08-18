import React from "react";
import { getAvailableStyles } from "../lib/styles";

interface Props {
  selected: string;
  onSelect: (style: string) => void;
}

const StyleSelector: React.FC<Props> = ({ selected, onSelect }) => {
  const styles = getAvailableStyles();
  return (
    <div>
      <div style={{ fontSize: 11, color: "#888", marginBottom: 8 }}>
        EDITING STYLE
      </div>
      {styles.map((style) => (
        <label
          key={style.id}
          style={{
            display: "flex",
            alignItems: "center",
            padding: "8px 10px",
            background: selected === style.id ? "#1a1a2e" : "#111122",
            borderRadius: 3,
            marginBottom: 4,
            cursor: "pointer",
            border: selected === style.id ? "1px solid #7c1629" : "1px solid transparent",
          }}
        >
          <input
            type="radio"
            name="style"
            checked={selected === style.id}
            onChange={() => onSelect(style.id)}
            style={{ marginRight: 8, accentColor: "#7c1629" }}
          />
          <span style={{ fontSize: 12 }}>{style.name}</span>
        </label>
      ))}
    </div>
  );
};

export default StyleSelector;