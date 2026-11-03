//! Loopback M4 control smoke server using a tiny synthetic graph fixture.
//! This avoids loading the large normalized connectome while exercising the
//! Rust gateway and Python simulator control path.

use std::{env, sync::Arc, time::Duration};

use neuro_api::{
    DatasetRef, Edge, GraphService, Neuron, ServiceLimits, http::router_with_simulation,
    simulation::SimulationGateway,
};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let simulation_url =
        env::var("NEUROPILOT_SIM_URL").unwrap_or_else(|_| "http://127.0.0.1:8790".into());
    let port = env::args()
        .nth(1)
        .map(|value| value.parse::<u16>())
        .transpose()?
        .unwrap_or(8789);
    let graph = GraphService::new(
        DatasetRef {
            id: "m4-synthetic-smoke".into(),
            snapshot: "fixture-1".into(),
        },
        1,
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(),
        "manifest-sha256:m4-synthetic".into(),
        vec![Neuron {
            root_id: "1".into(),
            primary_type: None,
        }],
        Vec::<Edge>::new(),
        ServiceLimits {
            page_limit_max: 10,
            graph_cap: 10,
        },
    )
    .map_err(|error| format!("synthetic smoke graph is invalid: {error:?}"))?;
    let gateway = SimulationGateway::new(&simulation_url, Duration::from_secs(2))?;
    let address = std::net::SocketAddr::from(([127, 0, 0, 1], port));
    let listener = tokio::net::TcpListener::bind(address).await?;
    println!("M4 smoke gateway listening on http://127.0.0.1:{port}");
    axum::serve(
        listener,
        router_with_simulation(Arc::new(graph), Some(Arc::new(gateway))),
    )
    .await?;
    Ok(())
}
