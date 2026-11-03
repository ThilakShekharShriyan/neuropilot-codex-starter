import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

function App() {
  return <main><h1>NeuroPilot</h1><p>Milestone 0 dashboard scaffold ready.</p></main>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode><App /></StrictMode>,
);
