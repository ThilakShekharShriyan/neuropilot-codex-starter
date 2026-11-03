import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import * as THREE from "three";
import "./styles.css";

type Neuron = { root_id: string; primary_type: string | null };
type Edge = { pre_root_id: string; post_root_id: string; neuropil: string; synapse_count: number; nt_type: string | null };
type ConnectionResponse = { nodes: Neuron[]; edges: Edge[]; truncated: boolean; next_cursor: string | null; provenance_ref: string };
type SearchResponse = { neurons: Neuron[]; provenance_ref: string };

const dataset = import.meta.env.VITE_DATASET_ID ?? "flywire-fafb";
const snapshot = import.meta.env.VITE_SNAPSHOT ?? "783";
const apiBase = import.meta.env.VITE_API_BASE ?? "";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`API request failed (${response.status})`);
  return (await response.json()) as T;
}

function GraphCanvas({ nodes, edges }: { nodes: Neuron[]; edges: Edge[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || nodes.length === 0) return;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#10131a");
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    camera.position.z = 8;
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    const group = new THREE.Group();
    const positions = new Map<string, THREE.Vector3>();
    nodes.forEach((node, index) => {
      const angle = (index / Math.max(nodes.length, 1)) * Math.PI * 2;
      const position = new THREE.Vector3(Math.cos(angle) * 2.2, Math.sin(angle) * 2.2, 0);
      positions.set(node.root_id, position);
      const material = new THREE.MeshBasicMaterial({ color: index === 0 ? "#f4c95d" : "#78b7ff" });
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.16, 16, 16), material);
      mesh.position.copy(position);
      group.add(mesh);
    });
    edges.forEach((edge) => {
      const from = positions.get(edge.pre_root_id);
      const to = positions.get(edge.post_root_id);
      if (!from || !to) return;
      const geometry = new THREE.BufferGeometry().setFromPoints([from, to]);
      group.add(new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: "#b8c6df" })));
    });
    scene.add(group);
    const resize = () => {
      const width = canvas.clientWidth || 640;
      const height = canvas.clientHeight || 420;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    let frame = 0;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const render = () => {
      if (!reducedMotion) group.rotation.z += 0.0008;
      renderer.render(scene, camera);
      frame = requestAnimationFrame(render);
    };
    render();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh || object instanceof THREE.Line) {
          object.geometry.dispose();
          const material = object.material;
          if (Array.isArray(material)) material.forEach((item) => item.dispose());
          else material.dispose();
        }
      });
      renderer.dispose();
    };
  }, [nodes, edges]);

  return <canvas ref={canvasRef} className="graph-canvas" aria-label="Abstract graph layout" />;
}

function App() {
  const [rootId, setRootId] = useState("");
  const [direction, setDirection] = useState<"incoming" | "outgoing" | "both">("both");
  const [connections, setConnections] = useState<ConnectionResponse | null>(null);
  const [matches, setMatches] = useState<Neuron[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  const loadGraph = async () => {
    if (!/^\d+$/.test(rootId)) {
      setError("Enter a source-backed neuron root ID.");
      setStatus("error");
      return;
    }
    setStatus("loading");
    setError(null);
    try {
      const query = new URLSearchParams({ direction, limit: "50", min_synapses: "5", aggregate: "false" });
      const result = await getJson<ConnectionResponse>(`/api/v1/datasets/${dataset}/${snapshot}/neurons/${rootId}/connections?${query.toString()}`);
      setConnections(result);
      setStatus("idle");
    } catch (reason) {
      setConnections(null);
      setError(reason instanceof Error ? reason.message : "Unable to reach local graph service.");
      setStatus("error");
    }
  };

  const search = async () => {
    setStatus("loading");
    setError(null);
    try {
      const result = await getJson<SearchResponse>(`/api/v1/datasets/${dataset}/${snapshot}/neurons?root_id=${encodeURIComponent(rootId)}&limit=10`);
      setMatches(result.neurons);
      setStatus("idle");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Search failed.");
      setStatus("error");
    }
  };

  return (
    <main className="app-shell">
      <header className="topbar"><div><span className="eyebrow">NEUROPILOT / M1</span><h1>Connectome Explorer</h1></div><span className="badge">{dataset} · v{snapshot}</span></header>
      <section className="control-panel" aria-label="Neuron controls">
        <label>Neuron root ID<input value={rootId} onChange={(event) => setRootId(event.target.value)} placeholder="Enter source-backed ID" /></label>
        <button onClick={search} disabled={status === "loading"}>Search</button><button onClick={loadGraph} disabled={status === "loading"}>Expand graph</button>
        <div className="direction-group" role="group" aria-label="Connection direction">{(["incoming", "outgoing", "both"] as const).map((value) => <button className={direction === value ? "selected" : ""} key={value} onClick={() => setDirection(value)}>{value}</button>)}</div>
      </section>
      {status === "loading" && <p className="notice" role="status">Loading source-backed records…</p>}
      {error && <p className="notice error" role="alert">{error}</p>}
      {matches.length > 0 && <section className="matches"><h2>Source matches</h2>{matches.map((neuron) => <button key={neuron.root_id} onClick={() => setRootId(neuron.root_id)}>{neuron.root_id} · {neuron.primary_type ?? "unannotated"}</button>)}</section>}
      <section className="graph-panel"><div className="panel-heading"><div><span className="eyebrow">DIRECTED SUBGRAPH</span><h2>{connections ? `${connections.edges.length} edges` : "Awaiting a local artifact"}</h2></div><span className="legend"><i className="dot selected-dot" /> selected <i className="dot edge-dot" /> edge weight</span></div>
        {connections ? <><GraphCanvas nodes={connections.nodes} edges={connections.edges} /><p className="provenance">Graph layout coordinates are abstract, not anatomical. Provenance: {connections.provenance_ref}{connections.truncated ? " · graph cap applied" : ""}</p></> : <div className="empty-state"><strong>No graph loaded</strong><span>Run the local Rust service with a normalized artifact to inspect real FAFB records.</span></div>}
      </section>
      <footer>Observed records only · no biological coordinates · credentials never enter the browser</footer>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
