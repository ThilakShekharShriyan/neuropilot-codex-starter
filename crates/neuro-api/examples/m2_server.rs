use std::{env, path::PathBuf, sync::Arc, time::Duration};

use neuro_api::{
    GraphService, ServiceLimits, http::router_with_simulation, simulation::SimulationGateway,
};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let directory = env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("data/normalized/fafb_v783"));
    let simulation_url =
        env::var("NEUROPILOT_SIM_URL").unwrap_or_else(|_| "http://127.0.0.1:8790".to_string());
    let port = env::args()
        .nth(2)
        .map(|value| value.parse::<u16>())
        .transpose()?
        .unwrap_or(8787);
    let graph = GraphService::from_normalized_dir(
        directory,
        ServiceLimits {
            page_limit_max: 100,
            graph_cap: 500,
        },
    )?;
    let gateway = SimulationGateway::new(&simulation_url, Duration::from_secs(2))?;
    let address = std::net::SocketAddr::from(([127, 0, 0, 1], port));
    let listener = tokio::net::TcpListener::bind(address).await?;
    println!("M2 gateway listening on http://127.0.0.1:{port}");
    axum::serve(
        listener,
        router_with_simulation(Arc::new(graph), Some(Arc::new(gateway))),
    )
    .await?;
    Ok(())
}
