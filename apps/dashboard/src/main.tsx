import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import * as THREE from "three";
import "./styles.css";

type Neuron = { root_id: string; primary_type: string | null };
type Edge = { pre_root_id: string; post_root_id: string; neuropil: string; synapse_count: number; nt_type: string | null };
type ProductProvenance = { name: string; filename: string; sha256: string; row_count: number; source_product: string };
type SourceProvenance = { source_manifest_sha256: string; license: string; citations: string[]; products: ProductProvenance[] };
type ConnectionResponse = { nodes: Neuron[]; edges: Edge[]; truncated: boolean; next_cursor: string | null; provenance_ref: string; provenance: SourceProvenance };
type SearchResponse = { neurons: Neuron[]; provenance_ref: string; provenance: SourceProvenance };
type SimulationState = { data_kind: "simulated-live"; session_id: string; status: "live" | "closed"; step_count: number; step_latency_ms: number | null; time: number; joint_angles: number[]; joint_velocities: number[]; body_positions: number[][] };
type SimulationMetrics = { data_kind: "simulated-live"; session_id: string; status: "live" | "closed"; request_count: number; error_count: number; reset_count: number; step_count: number; last_step_latency_ms: number | null };
type ControlStatus = { schema_version: 1; data_kind: "simulated-live"; control_session_id: string; simulator_session_id: string; status: "paused" | "active" | "stopped" | "disconnected"; simulator_status: "live" | "closed"; control_authority: number; watchdog_timeout_ms: number; queue_capacity: number; channels: ["forward", "lateral", "turn"]; actuator_count: number; sequence: number; watchdog_trips: number; stop_count: number; pause_count: number; resume_count: number; neutralization_count: number; last_control_sequence: number; last_control_latency_ms: number | null };
type ControlChannels = { forward: number; lateral: number; turn: number };
type ControlResponse = { control_session_id: string; sequence: number; forwarded: boolean; state?: SimulationState };

const dataset = import.meta.env.VITE_DATASET_ID ?? "flywire-fafb";
const snapshot = import.meta.env.VITE_SNAPSHOT ?? "783";
const apiBase = import.meta.env.VITE_API_BASE ?? "";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`API request failed (${response.status})`);
  return (await response.json()) as T;
}

async function postJson<T>(path: string, body: unknown = {}): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`Simulation request failed (${response.status})`);
  return (await response.json()) as T;
}

function layoutGraph(nodes: Neuron[], edges: Edge[]): Map<string, THREE.Vector3> {
  const positions = new Map(nodes.map((node, index) => [node.root_id, new THREE.Vector3(
    Math.cos(index * 2.4) * 2.2,
    Math.sin(index * 2.4) * 2.2,
    ((index * 17) % 11) / 10 - 0.5,
  )]));
  for (let iteration = 0; iteration < 48; iteration += 1) {
    const delta = new Map(nodes.map((node) => [node.root_id, new THREE.Vector3()]));
    nodes.forEach((left) => nodes.forEach((right) => {
      if (left.root_id === right.root_id) return;
      const a = positions.get(left.root_id)!;
      const b = positions.get(right.root_id)!;
      const direction = a.clone().sub(b);
      const distance = Math.max(direction.length(), 0.08);
      delta.get(left.root_id)!.add(direction.normalize().multiplyScalar(0.018 / distance));
    }));
    edges.forEach((edge) => {
      const a = positions.get(edge.pre_root_id);
      const b = positions.get(edge.post_root_id);
      if (!a || !b) return;
      const direction = b.clone().sub(a);
      delta.get(edge.pre_root_id)!.add(direction.multiplyScalar(0.002));
      delta.get(edge.post_root_id)!.sub(direction.multiplyScalar(0.002));
    });
    nodes.forEach((node) => positions.get(node.root_id)!.add(delta.get(node.root_id)!));
  }
  return positions;
}

function GraphCanvas({ nodes, edges, selectedId }: { nodes: Neuron[]; edges: Edge[]; selectedId: string }) {
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
    const positions = layoutGraph(nodes, edges);
    nodes.forEach((node) => {
      const position = positions.get(node.root_id)!;
      const material = new THREE.MeshBasicMaterial({ color: node.root_id === selectedId ? "#f4c95d" : (node.primary_type ? "#78b7ff" : "#7e8798") });
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.16, 16, 16), material);
      mesh.position.copy(position);
      group.add(mesh);
    });
    edges.forEach((edge) => {
      const from = positions.get(edge.pre_root_id);
      const to = positions.get(edge.post_root_id);
      if (!from || !to) return;
      const geometry = new THREE.BufferGeometry().setFromPoints([from, to]);
      const color = edge.pre_root_id === selectedId ? "#ff9f68" : "#7cb7ff";
      group.add(new THREE.Line(geometry, new THREE.LineBasicMaterial({ color })));
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
  }, [nodes, edges, selectedId]);

  return <canvas ref={canvasRef} className="graph-canvas" aria-label="Abstract graph layout" />;
}

function App() {
  const [rootId, setRootId] = useState("");
  const [direction, setDirection] = useState<"incoming" | "outgoing" | "both">("both");
  const [connections, setConnections] = useState<ConnectionResponse | null>(null);
  const [matches, setMatches] = useState<Neuron[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [simulation, setSimulation] = useState<SimulationState | null>(null);
  const [metrics, setMetrics] = useState<SimulationMetrics | null>(null);
  const [simulationStatus, setSimulationStatus] = useState<"idle" | "loading" | "closed" | "error">("idle");
  const [control, setControl] = useState<ControlStatus | null>(null);
  const [controlError, setControlError] = useState<string | null>(null);
  const controlStatusRef = useRef<ControlStatus["status"]>("disconnected");
  const controlSequenceRef = useRef(0);
  const controlChannelsRef = useRef<ControlChannels>({ forward: 0, lateral: 0, turn: 0 });
  controlStatusRef.current = control?.status ?? "disconnected";

  const updateControl = (value: ControlStatus) => {
    setControl(value);
    controlStatusRef.current = value.status;
    controlSequenceRef.current = value.last_control_sequence;
  };

  const controlAction = async (action: "session" | "resume" | "pause" | "stop" | "heartbeat" | "reset") => {
    setControlError(null);
    try {
      const current = action === "session"
        ? await postJson<ControlStatus>("/api/v1/control/session")
        : action === "reset"
          ? await postJson<ControlStatus>("/api/v1/control/reset")
          : await postJson<ControlStatus>(`/api/v1/control/${action}`, { control_session_id: control?.control_session_id ?? "" });
      updateControl(current);
      if (action === "reset" && current.simulator_status === "live") {
        const latest = await getJson<SimulationState>("/api/v1/simulation/state");
        setSimulation(latest);
      }
    } catch (reason) {
      setControlError(reason instanceof Error ? reason.message : "Control service unavailable.");
    }
  };

  const sendControl = async (channels: ControlChannels, mode: "active" | "neutral") => {
    if (controlStatusRef.current !== "active" || !control?.control_session_id) return;
    controlChannelsRef.current = channels;
    const sequence = controlSequenceRef.current + 1;
    controlSequenceRef.current = sequence;
    try {
      const result = await postJson<ControlResponse>("/api/v1/control/input", {
        schema_version: 1,
        control_session_id: control.control_session_id,
        sequence,
        issued_at_ms: Date.now(),
        control: channels,
        source: "keyboard",
        mode,
      });
      if (result.state) setSimulation(result.state);
    } catch (reason) {
      setControlError(reason instanceof Error ? reason.message : "Control input failed.");
    }
  };

  const sendControlRef = useRef(sendControl);
  sendControlRef.current = sendControl;

  useEffect(() => {
    const keyMap: Record<string, keyof ControlChannels> = { ArrowUp: "forward", w: "forward", ArrowDown: "forward", s: "forward", ArrowLeft: "turn", a: "turn", ArrowRight: "turn", d: "turn", q: "lateral", e: "lateral" };
    const pressed = new Set<string>();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLElement && ["INPUT", "TEXTAREA", "BUTTON"].includes(event.target.tagName)) return;
      const channel = keyMap[event.key];
      if (!channel || controlStatusRef.current !== "active") return;
      event.preventDefault();
      if (pressed.has(event.key)) return;
      pressed.add(event.key);
      const direction = ["ArrowDown", "s", "ArrowLeft", "a", "q"].includes(event.key) ? -1 : 1;
      const next = { ...controlChannelsRef.current, [channel]: direction * 1 };
      void sendControlRef.current(next, "active");
    };
    const onKeyUp = (event: KeyboardEvent) => {
      const channel = keyMap[event.key];
      if (!channel) return;
      pressed.delete(event.key);
      if (controlStatusRef.current !== "active") return;
      const next = { ...controlChannelsRef.current, [channel]: 0 };
      void sendControlRef.current(next, "neutral");
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, []);

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

  const simulationAction = async (action: "state" | "metrics" | "reset" | "restart" | "step" | "close") => {
    setSimulationStatus("loading");
    try {
      const result = action === "state"
        ? await getJson<SimulationState>("/api/v1/simulation/state")
        : action === "metrics"
          ? await getJson<SimulationMetrics>("/api/v1/simulation/metrics")
        : action === "close"
          ? await postJson<{ status: "closed" }>("/api/v1/simulation/close")
          : await postJson<SimulationState>(`/api/v1/simulation/${action}`);
      if (action === "metrics") setMetrics(result as SimulationMetrics);
      if (action !== "metrics") setSimulation(action === "close" ? null : result as SimulationState);
      setSimulationStatus(action === "close" ? "closed" : "idle");
    } catch (reason) {
      setSimulationStatus("error");
      setError(reason instanceof Error ? reason.message : "Simulation service unavailable.");
    }
  };

  useEffect(() => {
    if (!simulation || simulationStatus === "closed") return undefined;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const latest = await getJson<SimulationState>("/api/v1/simulation/state");
        if (!cancelled) {
          setSimulation(latest);
          setSimulationStatus("idle");
        }
      } catch {
        if (!cancelled) setSimulationStatus("error");
      }
    }, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [simulation?.session_id, simulationStatus]);

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
      <section className={`simulation-panel ${simulationStatus === "error" ? "degraded" : ""}`} aria-label="CPU simulation controls"><div><span className="eyebrow">M2 / SIMULATED LIVE</span><h2>NeuroMechFly CPU session</h2><p>{simulation ? `session ${simulation.session_id} · ${simulation.status} · t = ${simulation.time.toFixed(4)} s · ${simulation.step_count} steps · last step ${simulation.step_latency_ms?.toFixed(2) ?? "—"} ms` : simulationStatus === "closed" ? "Session closed" : simulationStatus === "error" ? "Simulation disconnected or invalid" : "No simulation state loaded"}</p>{metrics && <small>Requests {metrics.request_count} · errors {metrics.error_count} · resets {metrics.reset_count}</small>}</div><div className="simulation-actions"><button onClick={() => simulationAction("state")} disabled={simulationStatus === "loading"}>State</button><button onClick={() => simulationAction("metrics")} disabled={simulationStatus === "loading"}>Telemetry</button><button onClick={() => simulationAction("reset")} disabled={simulationStatus === "loading"}>Reset</button><button onClick={() => simulationAction("restart")} disabled={simulationStatus === "loading"}>Restart</button><button onClick={() => simulationAction("step")} disabled={simulationStatus === "loading" || simulationStatus === "closed"}>Step</button><button onClick={() => simulationAction("close")} disabled={simulationStatus === "loading" || simulationStatus === "closed"}>Close</button></div><small>Observed state from the CPU simulator; not connectome activity or anatomical coordinates.</small></section>
      <section className="control-panel m4-control" aria-label="M4 simulated keyboard control"><div><span className="eyebrow">M4 / SIMULATED CONTROL</span><h2>Keyboard input</h2><p>{control ? `control ${control.status} · session ${control.control_session_id} · watchdog ${control.watchdog_timeout_ms} ms` : "No control session attached"}</p><small>W/S or ↑/↓: forward · A/D or ←/→: turn · Q/E: lateral</small>{controlError && <p className="notice error" role="alert">{controlError}</p>}</div><div className="simulation-actions"><button onClick={() => void controlAction("session")} disabled={control?.status === "active"}>Connect</button><button onClick={() => void controlAction("resume")} disabled={!control || control.status === "active" || control.status === "disconnected"}>Resume</button><button onClick={() => void controlAction("pause")} disabled={!control || control.status !== "active"}>Pause</button><button className="danger" onClick={() => void controlAction("stop")} disabled={!control || control.status === "stopped" || control.status === "disconnected"}>Emergency stop</button><button onClick={() => void controlAction("reset")} disabled={!control}>Reset control</button><button onClick={() => void controlAction("heartbeat")} disabled={!control || control.status !== "active"}>Heartbeat</button></div><small>Engineering control only · no connectome or biological motor mapping · stop requires reset before resume.</small></section>
      <section className="graph-panel"><div className="panel-heading"><div><span className="eyebrow">DIRECTED SUBGRAPH</span><h2>{connections ? `${connections.edges.length} edges` : "Awaiting a local artifact"}</h2></div><span className="legend"><i className="dot selected-dot" /> selected <i className="dot edge-dot" /> edge weight</span></div>
        {connections ? <><GraphCanvas nodes={connections.nodes} edges={connections.edges} selectedId={rootId} /><p className="provenance">Graph layout coordinates are abstract, not anatomical. Orange edges are outgoing; blue edges are incoming. Provenance: {connections.provenance_ref} · source manifest {connections.provenance.source_manifest_sha256.slice(0, 12)}… · {connections.provenance.products.length} source files{connections.truncated ? " · graph cap applied" : ""}</p></> : <div className="empty-state"><strong>No graph loaded</strong><span>Run the local Rust service with a normalized artifact to inspect real FAFB records.</span></div>}
      </section>
      <footer>Observed records only · no biological coordinates · credentials never enter the browser</footer>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
