//! Typed Rust gateway to the local Python FlyGym service.

use std::time::Duration;
use std::{error::Error, fmt};

use reqwest::{Client, StatusCode};
use serde::{Deserialize, Serialize};

pub const MAX_CONTROL_VALUES: usize = 256;
pub const CONTROL_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct SimulationState {
    pub data_kind: String,
    pub session_id: String,
    pub status: String,
    pub step_count: u64,
    pub step_latency_ms: Option<f64>,
    pub time: f64,
    pub joint_angles: Vec<f64>,
    pub joint_velocities: Vec<f64>,
    pub body_positions: Vec<Vec<f64>>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct SimulationMetrics {
    pub data_kind: String,
    pub session_id: String,
    pub status: String,
    pub request_count: u64,
    pub error_count: u64,
    pub reset_count: u64,
    pub step_count: u64,
    pub last_step_latency_ms: Option<f64>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct StepRequest {
    pub control: Option<Vec<f64>>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ControlSession {
    pub schema_version: u32,
    pub data_kind: String,
    pub control_session_id: String,
    pub simulator_session_id: String,
    pub status: String,
    pub simulator_status: String,
    pub control_authority: f64,
    pub watchdog_timeout_ms: u64,
    pub queue_capacity: usize,
    pub channels: Vec<String>,
    pub sequence: u64,
}

#[derive(Debug)]
pub enum GatewayError {
    InvalidBaseUrl,
    InvalidControl,
    Timeout,
    Unavailable,
    Remote(StatusCode),
    InvalidResponse,
}

impl fmt::Display for GatewayError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::InvalidBaseUrl => "simulation base URL is invalid",
            Self::InvalidControl => "simulation control is invalid",
            Self::Timeout => "simulation service timed out",
            Self::Unavailable => "simulation service is unavailable",
            Self::Remote(_) => "simulation service returned an error",
            Self::InvalidResponse => "simulation response is invalid",
        };
        formatter.write_str(message)
    }
}

impl Error for GatewayError {}

#[derive(Clone)]
pub struct SimulationGateway {
    base_url: String,
    client: Client,
}

impl SimulationGateway {
    pub fn new(base_url: &str, timeout: Duration) -> Result<Self, GatewayError> {
        let parsed = reqwest::Url::parse(base_url).map_err(|_| GatewayError::InvalidBaseUrl)?;
        if parsed.scheme() != "http" || parsed.host_str() != Some("127.0.0.1") {
            return Err(GatewayError::InvalidBaseUrl);
        }
        let client = Client::builder()
            .connect_timeout(timeout)
            .timeout(timeout)
            .build()
            .map_err(|_| GatewayError::InvalidBaseUrl)?;
        Ok(Self {
            base_url: base_url.trim_end_matches('/').to_string(),
            client,
        })
    }

    pub async fn state(&self) -> Result<SimulationState, GatewayError> {
        self.request(self.client.get(self.url("/api/v1/simulation/state")))
            .await
    }

    pub async fn metrics(&self) -> Result<SimulationMetrics, GatewayError> {
        let response = self
            .client
            .get(self.url("/api/v1/simulation/metrics"))
            .send()
            .await
            .map_err(map_transport_error)?;
        if !response.status().is_success() {
            return Err(GatewayError::Remote(response.status()));
        }
        let metrics = response
            .json::<SimulationMetrics>()
            .await
            .map_err(|_| GatewayError::InvalidResponse)?;
        if metrics.data_kind != "simulated-live"
            || metrics.session_id.is_empty()
            || !matches!(metrics.status.as_str(), "live" | "closed")
            || metrics
                .last_step_latency_ms
                .is_some_and(|value| !value.is_finite() || value < 0.0)
        {
            return Err(GatewayError::InvalidResponse);
        }
        Ok(metrics)
    }

    pub async fn reset(&self) -> Result<SimulationState, GatewayError> {
        self.request(
            self.client
                .post(self.url("/api/v1/simulation/reset"))
                .json(&serde_json::json!({})),
        )
        .await
    }

    pub async fn restart(&self) -> Result<SimulationState, GatewayError> {
        self.request(
            self.client
                .post(self.url("/api/v1/simulation/restart"))
                .json(&serde_json::json!({})),
        )
        .await
    }

    pub async fn step(&self, control: Option<Vec<f64>>) -> Result<SimulationState, GatewayError> {
        if let Some(values) = &control {
            if values.len() > MAX_CONTROL_VALUES || values.iter().any(|value| !value.is_finite()) {
                return Err(GatewayError::InvalidControl);
            }
        }
        self.request(
            self.client
                .post(self.url("/api/v1/simulation/step"))
                .json(&StepRequest { control }),
        )
        .await
    }

    pub async fn close(&self) -> Result<(), GatewayError> {
        let response = self
            .client
            .post(self.url("/api/v1/simulation/close"))
            .json(&serde_json::json!({}))
            .send()
            .await
            .map_err(map_transport_error)?;
        if response.status().is_success() {
            Ok(())
        } else {
            Err(GatewayError::Remote(response.status()))
        }
    }

    pub async fn control_session(&self) -> Result<ControlSession, GatewayError> {
        let response = self
            .client
            .post(self.url("/api/v1/control/session"))
            .json(&serde_json::json!({}))
            .send()
            .await
            .map_err(map_transport_error)?;
        self.decode_control_session(response).await
    }

    pub async fn control_status(&self) -> Result<ControlSession, GatewayError> {
        let response = self
            .client
            .get(self.url("/api/v1/control/status"))
            .send()
            .await
            .map_err(map_transport_error)?;
        self.decode_control_session(response).await
    }

    pub async fn control_reset(&self) -> Result<ControlSession, GatewayError> {
        let response = self
            .client
            .post(self.url("/api/v1/control/reset"))
            .json(&serde_json::json!({}))
            .send()
            .await
            .map_err(map_transport_error)?;
        self.decode_control_session(response).await
    }

    async fn decode_control_session(
        &self,
        response: reqwest::Response,
    ) -> Result<ControlSession, GatewayError> {
        if !response.status().is_success() {
            return Err(GatewayError::Remote(response.status()));
        }
        let value = response
            .json::<ControlSession>()
            .await
            .map_err(|_| GatewayError::InvalidResponse)?;
        validate_control_session(&value)?;
        Ok(value)
    }

    fn url(&self, path: &str) -> String {
        format!("{}{}", self.base_url, path)
    }

    async fn request(
        &self,
        request: reqwest::RequestBuilder,
    ) -> Result<SimulationState, GatewayError> {
        let response = request.send().await.map_err(map_transport_error)?;
        if !response.status().is_success() {
            return Err(GatewayError::Remote(response.status()));
        }
        let state = response
            .json::<SimulationState>()
            .await
            .map_err(|_| GatewayError::InvalidResponse)?;
        validate_state(&state)?;
        Ok(state)
    }
}

fn validate_state(state: &SimulationState) -> Result<(), GatewayError> {
    if state.data_kind != "simulated-live"
        || state.session_id.is_empty()
        || state.session_id.len() > 128
        || !matches!(state.status.as_str(), "live" | "closed")
        || state.step_count > 10_000_000
        || !state.time.is_finite()
        || state.time < 0.0
        || state
            .step_latency_ms
            .is_some_and(|value| !value.is_finite() || value < 0.0)
        || state.joint_angles.len() > 10_000
        || state.joint_velocities.len() > 10_000
        || state.body_positions.len() > 10_000
        || state
            .joint_angles
            .iter()
            .chain(state.joint_velocities.iter())
            .any(|value| !value.is_finite())
        || state
            .body_positions
            .iter()
            .any(|position| position.len() != 3 || position.iter().any(|value| !value.is_finite()))
    {
        return Err(GatewayError::InvalidResponse);
    }
    Ok(())
}

fn validate_control_session(value: &ControlSession) -> Result<(), GatewayError> {
    if value.schema_version != CONTROL_SCHEMA_VERSION
        || value.data_kind != "simulated-live"
        || value.control_session_id.is_empty()
        || value.simulator_session_id.is_empty()
        || !matches!(
            value.status.as_str(),
            "paused" | "active" | "stopped" | "disconnected"
        )
        || !matches!(value.simulator_status.as_str(), "live" | "closed")
        || !value.control_authority.is_finite()
        || !(0.0..=1.0).contains(&value.control_authority)
        || value.watchdog_timeout_ms == 0
        || value.queue_capacity == 0
        || value.channels != vec!["forward", "lateral", "turn"]
    {
        return Err(GatewayError::InvalidResponse);
    }
    Ok(())
}

fn map_transport_error(error: reqwest::Error) -> GatewayError {
    if error.is_timeout() {
        GatewayError::Timeout
    } else {
        GatewayError::Unavailable
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpListener;

    use super::{GatewayError, SimulationGateway};

    fn valid_body() -> &'static str {
        r#"{"data_kind":"simulated-live","session_id":"test-session","status":"live","step_count":1,"step_latency_ms":0.2,"time":0.1,"joint_angles":[0.0],"joint_velocities":[0.0],"body_positions":[[0.0,0.0,0.0]]}"#
    }

    fn control_body() -> &'static str {
        r#"{"schema_version":1,"data_kind":"simulated-live","control_session_id":"control-session","simulator_session_id":"simulator-session","status":"paused","simulator_status":"live","control_authority":0.25,"watchdog_timeout_ms":250,"queue_capacity":32,"channels":["forward","lateral","turn"],"sequence":0}"#
    }

    async fn mock_once(
        status: u16,
        body: &'static str,
        delay: Duration,
    ) -> (u16, tokio::task::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let task = tokio::spawn(async move {
            let Ok((mut stream, _)) = listener.accept().await else {
                return;
            };
            let mut request = [0_u8; 1024];
            let _ = stream.read(&mut request).await;
            if !delay.is_zero() {
                tokio::time::sleep(delay).await;
            }
            let reason = if status == 200 { "OK" } else { "Conflict" };
            let response = format!(
                "HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            let _ = stream.write_all(response.as_bytes()).await;
        });
        (port, task)
    }

    #[tokio::test]
    async fn timeout_is_mapped() {
        let (port, task) = mock_once(200, valid_body(), Duration::from_millis(100)).await;
        let gateway = SimulationGateway::new(
            &format!("http://127.0.0.1:{port}"),
            Duration::from_millis(10),
        )
        .unwrap();
        assert!(matches!(gateway.state().await, Err(GatewayError::Timeout)));
        let _ = task.await;
    }

    #[tokio::test]
    async fn connection_refusal_is_unavailable() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        drop(listener);
        let gateway = SimulationGateway::new(
            &format!("http://127.0.0.1:{port}"),
            Duration::from_millis(50),
        )
        .unwrap();
        assert!(matches!(
            gateway.state().await,
            Err(GatewayError::Unavailable)
        ));
    }

    #[tokio::test]
    async fn malformed_state_is_rejected() {
        let (port, task) = mock_once(200, "{}", Duration::ZERO).await;
        let gateway =
            SimulationGateway::new(&format!("http://127.0.0.1:{port}"), Duration::from_secs(1))
                .unwrap();
        assert!(matches!(
            gateway.state().await,
            Err(GatewayError::InvalidResponse)
        ));
        let _ = task.await;
    }

    #[tokio::test]
    async fn wrong_data_kind_is_rejected() {
        let body = r#"{"data_kind":"observed","session_id":"test-session","status":"live","step_count":1,"step_latency_ms":0.2,"time":0.1,"joint_angles":[0.0],"joint_velocities":[0.0],"body_positions":[[0.0,0.0,0.0]]}"#;
        let (port, task) = mock_once(200, body, Duration::ZERO).await;
        let gateway =
            SimulationGateway::new(&format!("http://127.0.0.1:{port}"), Duration::from_secs(1))
                .unwrap();
        assert!(matches!(
            gateway.state().await,
            Err(GatewayError::InvalidResponse)
        ));
        let _ = task.await;
    }

    #[tokio::test]
    async fn control_session_contract_is_validated() {
        let (port, task) = mock_once(200, control_body(), Duration::ZERO).await;
        let gateway =
            SimulationGateway::new(&format!("http://127.0.0.1:{port}"), Duration::from_secs(1))
                .unwrap();
        let session = gateway.control_session().await.unwrap();
        assert_eq!(session.control_session_id, "control-session");
        assert_eq!(session.simulator_session_id, "simulator-session");
        assert_eq!(session.status, "paused");
        let _ = task.await;
    }

    #[tokio::test]
    async fn malformed_control_session_is_rejected() {
        let (port, task) = mock_once(200, "{}", Duration::ZERO).await;
        let gateway =
            SimulationGateway::new(&format!("http://127.0.0.1:{port}"), Duration::from_secs(1))
                .unwrap();
        assert!(matches!(
            gateway.control_status().await,
            Err(GatewayError::InvalidResponse)
        ));
        let _ = task.await;
    }

    #[tokio::test]
    async fn remote_closed_state_is_mapped() {
        let (port, task) = mock_once(409, "{\"code\":\"simulation_closed\"}", Duration::ZERO).await;
        let gateway =
            SimulationGateway::new(&format!("http://127.0.0.1:{port}"), Duration::from_secs(1))
                .unwrap();
        assert!(
            matches!(gateway.state().await, Err(GatewayError::Remote(status)) if status == reqwest::StatusCode::CONFLICT)
        );
        let _ = task.await;
    }

    #[tokio::test]
    async fn invalid_control_is_rejected_before_network() {
        let gateway = SimulationGateway::new("http://127.0.0.1:1", Duration::from_secs(1)).unwrap();
        assert!(matches!(
            gateway.step(Some(vec![f64::NAN])).await,
            Err(GatewayError::InvalidControl)
        ));
    }

    #[tokio::test]
    async fn gateway_can_reconnect_after_service_restart() {
        let (port, first) = mock_once(200, valid_body(), Duration::ZERO).await;
        let gateway =
            SimulationGateway::new(&format!("http://127.0.0.1:{port}"), Duration::from_secs(1))
                .unwrap();
        assert!(gateway.state().await.is_ok());
        let _ = first.await;
        let listener = TcpListener::bind(format!("127.0.0.1:{port}"))
            .await
            .unwrap();
        let restarted = tokio::spawn(async move {
            let Ok((mut stream, _)) = listener.accept().await else {
                return;
            };
            let mut request = [0_u8; 1024];
            let _ = stream.read(&mut request).await;
            let body = valid_body();
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            let _ = stream.write_all(response.as_bytes()).await;
        });
        assert!(gateway.state().await.is_ok());
        let _ = restarted.await;
    }

    #[tokio::test]
    async fn restart_returns_a_valid_fresh_state() {
        let (port, task) = mock_once(200, valid_body(), Duration::ZERO).await;
        let gateway =
            SimulationGateway::new(&format!("http://127.0.0.1:{port}"), Duration::from_secs(1))
                .unwrap();
        assert_eq!(gateway.restart().await.unwrap().status, "live");
        let _ = task.await;
    }
}
