//! Minimal loopback HTTP transport for the typed graph contract.
//!
//! Credentials and acquisition are deliberately absent from this module. The
//! caller supplies an already validated, local `GraphService`.

use std::net::SocketAddr;
use std::sync::Arc;

use axum::{
    Json, Router,
    extract::{Path, Query, State},
    http::{HeaderValue, Request, StatusCode},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::get,
};
use serde::{Deserialize, Serialize};

use crate::{
    Direction, GraphService, Query as GraphQuery, QueryError,
    simulation::{GatewayError, SimulationGateway},
};

#[derive(Clone)]
pub struct AppState {
    pub graph: Arc<GraphService>,
    pub simulation: Option<Arc<SimulationGateway>>,
}

#[derive(Debug, Deserialize)]
pub struct ConnectionParams {
    pub direction: String,
    #[serde(default = "default_limit")]
    pub limit: usize,
    pub cursor: Option<String>,
    #[serde(default = "default_min_synapses")]
    pub min_synapses: u64,
    #[serde(default)]
    pub aggregate: bool,
}

#[derive(Debug, Deserialize)]
pub struct SearchParams {
    pub root_id: Option<String>,
    pub primary_type: Option<String>,
    #[serde(default = "default_limit")]
    pub limit: usize,
}

#[derive(Debug, Serialize)]
struct NeuronResponse {
    dataset: crate::DatasetRef,
    schema_version: u32,
    provenance_ref: String,
    provenance: crate::SourceProvenance,
    neuron: crate::Neuron,
}

#[derive(Debug, Serialize)]
struct ErrorResponse {
    code: &'static str,
    message: &'static str,
    request_id: &'static str,
}

#[derive(Debug, Serialize)]
struct SearchResponse {
    dataset: crate::DatasetRef,
    schema_version: u32,
    provenance_ref: String,
    provenance: crate::SourceProvenance,
    neurons: Vec<crate::Neuron>,
}

fn default_limit() -> usize {
    10
}

fn default_min_synapses() -> u64 {
    5
}

pub fn router(graph: Arc<GraphService>) -> Router {
    router_with_simulation(graph, None)
}

pub fn router_with_simulation(
    graph: Arc<GraphService>,
    simulation: Option<Arc<SimulationGateway>>,
) -> Router {
    Router::new()
        .route(
            "/api/v1/datasets/{dataset}/{snapshot}/neurons/{root_id}",
            get(get_neuron),
        )
        .route(
            "/api/v1/datasets/{dataset}/{snapshot}/neurons/{root_id}/connections",
            get(get_connections),
        )
        .route(
            "/api/v1/datasets/{dataset}/{snapshot}/neurons",
            get(search_neurons),
        )
        .route("/api/v1/simulation/state", get(simulation_state))
        .route(
            "/api/v1/simulation/reset",
            axum::routing::post(simulation_reset),
        )
        .route(
            "/api/v1/simulation/step",
            axum::routing::post(simulation_step),
        )
        .route(
            "/api/v1/simulation/close",
            axum::routing::post(simulation_close),
        )
        .with_state(AppState { graph, simulation })
        .layer(middleware::from_fn(local_boundary))
}

/// Serve the already validated graph on loopback only.
pub async fn serve_loopback(graph: Arc<GraphService>, port: u16) -> std::io::Result<()> {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let listener = tokio::net::TcpListener::bind(address).await?;
    axum::serve(listener, router(graph))
        .await
        .map_err(std::io::Error::other)
}

async fn local_boundary(request: Request<axum::body::Body>, next: Next) -> Response {
    if let Some(host) = request.headers().get("host") {
        let valid_host = host
            .to_str()
            .ok()
            .map(|value| {
                matches!(
                    value,
                    "127.0.0.1"
                        | "127.0.0.1:80"
                        | "127.0.0.1:3000"
                        | "127.0.0.1:5173"
                        | "127.0.0.1:8787"
                        | "127.0.0.1:8788"
                        | "localhost"
                        | "localhost:80"
                        | "localhost:3000"
                        | "localhost:5173"
                        | "localhost:8787"
                        | "localhost:8788"
                        | "[::1]"
                        | "[::1]:80"
                        | "[::1]:3000"
                        | "[::1]:5173"
                        | "[::1]:8787"
                        | "[::1]:8788"
                )
            })
            .unwrap_or(false);
        if !valid_host {
            return error(StatusCode::BAD_REQUEST, "invalid_host", "host is not local");
        }
    }
    let origin = request.headers().get("origin").cloned();
    if let Some(origin_value) = &origin {
        let valid_origin = matches!(
            origin_value.to_str().ok(),
            Some("http://localhost:5173") | Some("http://127.0.0.1:5173")
        );
        if !valid_origin {
            return error(
                StatusCode::FORBIDDEN,
                "invalid_origin",
                "origin is not allowed",
            );
        }
    }
    let mut response = next.run(request).await;
    if let Some(origin) = origin {
        if let Ok(value) = HeaderValue::from_bytes(origin.as_bytes()) {
            response
                .headers_mut()
                .insert("access-control-allow-origin", value);
            response
                .headers_mut()
                .insert("vary", HeaderValue::from_static("Origin"));
        }
    }
    response
}

async fn get_neuron(
    State(state): State<AppState>,
    Path((dataset, snapshot, root_id)): Path<(String, String, String)>,
) -> impl IntoResponse {
    if dataset != state.graph.dataset().id || snapshot != state.graph.dataset().snapshot {
        return error(
            StatusCode::NOT_FOUND,
            "dataset_not_found",
            "dataset is unavailable",
        );
    }
    match state.graph.neuron(&root_id) {
        Ok(neuron) => (
            StatusCode::OK,
            Json(NeuronResponse {
                dataset: state.graph.dataset().clone(),
                schema_version: 1,
                provenance_ref: state.graph.provenance_ref().to_string(),
                provenance: state.graph.source_provenance().clone(),
                neuron,
            }),
        )
            .into_response(),
        Err(error_value) => query_error(error_value),
    }
}

async fn get_connections(
    State(state): State<AppState>,
    Path((dataset, snapshot, root_id)): Path<(String, String, String)>,
    Query(params): Query<ConnectionParams>,
) -> impl IntoResponse {
    if dataset != state.graph.dataset().id || snapshot != state.graph.dataset().snapshot {
        return error(
            StatusCode::NOT_FOUND,
            "dataset_not_found",
            "dataset is unavailable",
        );
    }
    let Some(direction) = parse_direction(&params.direction) else {
        return error(
            StatusCode::BAD_REQUEST,
            "invalid_direction",
            "direction is invalid",
        );
    };
    let query = GraphQuery {
        root_id,
        direction,
        limit: params.limit,
        cursor: params.cursor,
        min_synapses: params.min_synapses,
        aggregate: params.aggregate,
    };
    match state.graph.query_connections(&query) {
        Ok(response) => (StatusCode::OK, Json(response)).into_response(),
        Err(error_value) => query_error(error_value),
    }
}

async fn search_neurons(
    State(state): State<AppState>,
    Path((dataset, snapshot)): Path<(String, String)>,
    Query(params): Query<SearchParams>,
) -> impl IntoResponse {
    if dataset != state.graph.dataset().id || snapshot != state.graph.dataset().snapshot {
        return error(
            StatusCode::NOT_FOUND,
            "dataset_not_found",
            "dataset is unavailable",
        );
    }
    match state.graph.search_neurons(
        params.root_id.as_deref(),
        params.primary_type.as_deref(),
        params.limit,
    ) {
        Ok(neurons) => (
            StatusCode::OK,
            Json(SearchResponse {
                dataset: state.graph.dataset().clone(),
                schema_version: 1,
                provenance_ref: state.graph.provenance_ref().to_string(),
                provenance: state.graph.source_provenance().clone(),
                neurons,
            }),
        )
            .into_response(),
        Err(error_value) => query_error(error_value),
    }
}

async fn simulation_state(State(state): State<AppState>) -> Response {
    let Some(simulation) = state.simulation else {
        return error(
            StatusCode::SERVICE_UNAVAILABLE,
            "simulation_unavailable",
            "simulation gateway is unavailable",
        );
    };
    match simulation.state().await {
        Ok(value) => (StatusCode::OK, Json(value)).into_response(),
        Err(error_value) => gateway_error(error_value),
    }
}

async fn simulation_reset(State(state): State<AppState>) -> Response {
    let Some(simulation) = state.simulation else {
        return error(
            StatusCode::SERVICE_UNAVAILABLE,
            "simulation_unavailable",
            "simulation gateway is unavailable",
        );
    };
    match simulation.reset().await {
        Ok(value) => (StatusCode::OK, Json(value)).into_response(),
        Err(error_value) => gateway_error(error_value),
    }
}

async fn simulation_step(
    State(state): State<AppState>,
    Json(request): Json<crate::simulation::StepRequest>,
) -> Response {
    let Some(simulation) = state.simulation else {
        return error(
            StatusCode::SERVICE_UNAVAILABLE,
            "simulation_unavailable",
            "simulation gateway is unavailable",
        );
    };
    match simulation.step(request.control).await {
        Ok(value) => (StatusCode::OK, Json(value)).into_response(),
        Err(error_value) => gateway_error(error_value),
    }
}

async fn simulation_close(State(state): State<AppState>) -> Response {
    let Some(simulation) = state.simulation else {
        return error(
            StatusCode::SERVICE_UNAVAILABLE,
            "simulation_unavailable",
            "simulation gateway is unavailable",
        );
    };
    match simulation.close().await {
        Ok(()) => (
            StatusCode::OK,
            Json(serde_json::json!({"status": "closed"})),
        )
            .into_response(),
        Err(error_value) => gateway_error(error_value),
    }
}

fn parse_direction(value: &str) -> Option<Direction> {
    match value {
        "incoming" => Some(Direction::Incoming),
        "outgoing" => Some(Direction::Outgoing),
        "both" => Some(Direction::Both),
        _ => None,
    }
}

fn query_error(error_value: QueryError) -> axum::response::Response {
    let (status, code, message) = match error_value {
        QueryError::UnknownNeuron => (StatusCode::NOT_FOUND, "unknown_neuron", "neuron not found"),
        QueryError::InvalidRootId => (
            StatusCode::BAD_REQUEST,
            "invalid_root_id",
            "root ID is invalid",
        ),
        QueryError::InvalidLimit => (StatusCode::BAD_REQUEST, "invalid_limit", "limit is invalid"),
        QueryError::InvalidThreshold => (
            StatusCode::BAD_REQUEST,
            "invalid_threshold",
            "threshold is invalid",
        ),
        QueryError::CursorMalformed => (
            StatusCode::BAD_REQUEST,
            "cursor_malformed",
            "cursor is malformed",
        ),
        QueryError::CursorMismatch => (
            StatusCode::BAD_REQUEST,
            "cursor_mismatch",
            "cursor does not match the query",
        ),
        QueryError::CursorOutOfRange => (
            StatusCode::BAD_REQUEST,
            "cursor_out_of_range",
            "cursor is out of range",
        ),
        QueryError::GraphCapExceeded => (
            StatusCode::BAD_REQUEST,
            "graph_cap_exceeded",
            "graph cap exceeded",
        ),
        QueryError::ArithmeticOverflow => (
            StatusCode::UNPROCESSABLE_ENTITY,
            "arithmetic_overflow",
            "graph arithmetic overflow",
        ),
        QueryError::InvalidConfiguration | QueryError::InvalidArtifactHash => (
            StatusCode::INTERNAL_SERVER_ERROR,
            "service_misconfigured",
            "service configuration is invalid",
        ),
    };
    error(status, code, message)
}

fn gateway_error(error_value: GatewayError) -> axum::response::Response {
    match error_value {
        GatewayError::InvalidControl => error(
            StatusCode::BAD_REQUEST,
            "invalid_control",
            "control is invalid",
        ),
        GatewayError::InvalidBaseUrl | GatewayError::InvalidResponse => error(
            StatusCode::BAD_GATEWAY,
            "simulation_protocol_error",
            "simulation response is invalid",
        ),
        GatewayError::Timeout => error(
            StatusCode::GATEWAY_TIMEOUT,
            "simulation_timeout",
            "simulation service timed out",
        ),
        GatewayError::Unavailable => error(
            StatusCode::SERVICE_UNAVAILABLE,
            "simulation_unavailable",
            "simulation service is unavailable",
        ),
        GatewayError::Remote(status) if status == StatusCode::CONFLICT => error(
            StatusCode::CONFLICT,
            "simulation_closed",
            "simulation is closed",
        ),
        GatewayError::Remote(status) if status == StatusCode::BAD_REQUEST => error(
            StatusCode::BAD_REQUEST,
            "invalid_control",
            "control is invalid",
        ),
        GatewayError::Remote(_) => error(
            StatusCode::BAD_GATEWAY,
            "simulation_error",
            "simulation service returned an error",
        ),
    }
}

fn error(
    status: StatusCode,
    code: &'static str,
    message: &'static str,
) -> axum::response::Response {
    (
        status,
        Json(ErrorResponse {
            code,
            message,
            request_id: "local",
        }),
    )
        .into_response()
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use tower::ServiceExt;

    fn graph() -> Arc<GraphService> {
        Arc::new(
            GraphService::new(
                crate::DatasetRef {
                    id: "synthetic".into(),
                    snapshot: "fixture-1".into(),
                },
                1,
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(),
                "manifest-sha256:fixture".into(),
                vec![crate::Neuron {
                    root_id: "100".into(),
                    primary_type: Some("source".into()),
                }],
                Vec::new(),
                crate::ServiceLimits {
                    page_limit_max: 10,
                    graph_cap: 10,
                },
            )
            .expect("fixture graph"),
        )
    }

    #[tokio::test]
    async fn neuron_lookup_returns_json_and_unknown_ids_are_stable_errors() {
        let app = router(graph());
        let response = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/datasets/synthetic/fixture-1/neurons/100")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);

        let response = app
            .oneshot(
                Request::builder()
                    .uri("/api/v1/datasets/synthetic/fixture-1/neurons/999")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn connection_endpoint_rejects_invalid_direction() {
        let response = router(graph())
            .oneshot(
                Request::builder()
                    .uri("/api/v1/datasets/synthetic/fixture-1/neurons/100/connections?direction=sideways&limit=1&min_synapses=1")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn search_endpoint_returns_source_backed_neurons() {
        let response = router(graph())
            .oneshot(
                Request::builder()
                    .uri("/api/v1/datasets/synthetic/fixture-1/neurons?primary_type=source")
                    .header("host", "127.0.0.1:5173")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn local_boundary_rejects_non_local_host_and_origin() {
        let invalid_host = router(graph())
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/datasets/synthetic/fixture-1/neurons/100")
                    .header("host", "evil.example")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(invalid_host.status(), StatusCode::BAD_REQUEST);

        let invalid_origin = router(graph())
            .oneshot(
                Request::builder()
                    .uri("/api/v1/datasets/synthetic/fixture-1/neurons/100")
                    .header("host", "127.0.0.1:5173")
                    .header("origin", "https://evil.example")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(invalid_origin.status(), StatusCode::FORBIDDEN);
    }
}
