//! Typed Rust gateway to the local Python FlyGym service.

use std::time::Duration;
use std::{error::Error, fmt};

use reqwest::{Client, StatusCode};
use serde::{Deserialize, Serialize};

pub const MAX_CONTROL_VALUES: usize = 256;

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct SimulationState {
    pub data_kind: String,
    pub time: f64,
    pub joint_angles: Vec<f64>,
    pub joint_velocities: Vec<f64>,
    pub body_positions: Vec<Vec<f64>>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct StepRequest {
    pub control: Option<Vec<f64>>,
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

    pub async fn reset(&self) -> Result<SimulationState, GatewayError> {
        self.request(
            self.client
                .post(self.url("/api/v1/simulation/reset"))
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
        response
            .json::<SimulationState>()
            .await
            .map_err(|_| GatewayError::InvalidResponse)
    }
}

fn map_transport_error(error: reqwest::Error) -> GatewayError {
    if error.is_timeout() {
        GatewayError::Timeout
    } else {
        GatewayError::Unavailable
    }
}
