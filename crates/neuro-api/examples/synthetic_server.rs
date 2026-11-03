//! Local transport smoke server using the explicitly synthetic M1 fixture.
//! This is not a biological dataset and must not be presented as FAFB.

use std::sync::Arc;

use neuro_api::http::serve_loopback;
use neuro_api::{DatasetRef, Edge, GraphService, Neuron, ServiceLimits};

#[tokio::main(flavor = "current_thread")]
async fn main() -> std::io::Result<()> {
    let graph = GraphService::new(
        DatasetRef {
            id: "synthetic-m1-fixture".into(),
            snapshot: "fixture-1".into(),
        },
        1,
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(),
        "manifest-sha256:synthetic-fixture".into(),
        vec![
            Neuron {
                root_id: "100".into(),
                primary_type: Some("synthetic_source".into()),
            },
            Neuron {
                root_id: "200".into(),
                primary_type: Some("synthetic_target".into()),
            },
        ],
        vec![Edge {
            pre_root_id: "100".into(),
            post_root_id: "200".into(),
            neuropil: "synthetic".into(),
            synapse_count: 5,
            nt_type: None,
        }],
        ServiceLimits {
            page_limit_max: 50,
            graph_cap: 100,
        },
    )
    .expect("synthetic fixture graph is valid");
    println!("synthetic M1 server listening on http://127.0.0.1:8787");
    serve_loopback(Arc::new(graph), 8787).await
}
