import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

declare global {
  interface Window {
    __flagshipBooted?: boolean;
    __flagshipShowFatal?: (message: string, detail?: string) => void;
  }
}

function reportFatal(message: string, detail: string): void {
  if (typeof window.__flagshipShowFatal === "function") {
    window.__flagshipShowFatal(message, detail);
    return;
  }
  const container = document.getElementById("root");
  if (container) container.textContent = `${message} ${detail}`;
}

interface BoundaryState {
  message: string;
}

/**
 * A React failure inside CEP renders as a blank panel, so the boundary hands
 * the message to the startup fallback that is already on the page.
 */
class PanelErrorBoundary extends React.Component<{ children: React.ReactNode }, BoundaryState> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { message: "" };
  }

  static getDerivedStateFromError(error: unknown): BoundaryState {
    return { message: error instanceof Error ? error.message : String(error) };
  }

  componentDidCatch(error: unknown): void {
    reportFatal(
      "FlagshipEditor hit an unrecoverable error.",
      error instanceof Error ? error.message : String(error)
    );
  }

  render(): React.ReactNode {
    if (this.state.message) return null;
    return this.props.children;
  }
}

const container = document.getElementById("root");
if (!container) {
  reportFatal("FlagshipEditor could not start.", "The panel document has no root element.");
} else {
  try {
    createRoot(container).render(
      <PanelErrorBoundary>
        <App />
      </PanelErrorBoundary>
    );
    window.__flagshipBooted = true;
  } catch (error) {
    reportFatal(
      "FlagshipEditor could not start.",
      error instanceof Error ? error.message : String(error)
    );
  }
}
