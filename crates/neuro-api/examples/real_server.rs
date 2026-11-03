use std::{env, path::PathBuf, sync::Arc};

use neuro_api::{GraphService, ServiceLimits, http::serve_loopback};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let directory = env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("data/normalized/fafb_v783"));
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
    println!(
        "serving {} v{} on http://127.0.0.1:{port}",
        graph.dataset().id,
        graph.dataset().snapshot
    );
    serve_loopback(Arc::new(graph), port).await?;
    Ok(())
}
