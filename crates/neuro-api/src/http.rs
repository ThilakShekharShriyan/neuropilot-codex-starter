//! Minimal loopback HTTP transport for the typed graph contract.
//!
//! Credentials and acquisition are deliberately absent from this module. The
//! caller supplies an already validated, local `GraphService`.

use std::sync::Arc;

use axum::{
    Json, Router,
    extract::{Path, Query, State},
    http::StatusCode,
    response::IntoResponse,
    routing::get,
};
use serde::{Deserialize, Serialize};

use crate::{Direction, GraphService, Query as GraphQuery, QueryError};

#[derive(Clone)]
pub struct AppState {
    pub graph: Arc<GraphService>,
}

#[derive(Debug, Deserialize)]
pub struct ConnectionParams {
    pub direction: String,
    pub limit: usize,
    pub cursor: Option<String>,
    pub min_synapses: u64,
    #[serde(default)]
    pub aggregate: bool,
}

#[derive(Debug, Serialize)]
struct NeuronResponse {
    dataset: crate::DatasetRef,
    schema_version: u32,
    provenance_ref: String,
    neuron: crate::Neuron,
}

#[derive(Debug, Serialize)]
struct ErrorResponse {
    code: &'static str,
    message: &'static str,
}

pub fn router(graph: Arc<GraphService>) -> Router {
    Router::new()
        .route(
            "/api/v1/datasets/{dataset}/{snapshot}/neurons/{root_id}",
            get(get_neuron),
        )
        .route(
            "/api/v1/datasets/{dataset}/{snapshot}/neurons/{root_id}/connections",
            get(get_connections),
        )
        .with_state(AppState { graph })
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

fn error(
    status: StatusCode,
    code: &'static str,
    message: &'static str,
) -> axum::response::Response {
    (status, Json(ErrorResponse { code, message })).into_response()
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
}
