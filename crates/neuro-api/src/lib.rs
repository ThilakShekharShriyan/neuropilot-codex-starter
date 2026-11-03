//! Dependency-free M1 read-service contract.
//!
//! This crate deliberately implements the typed query and pagination layer
//! before adding an HTTP transport. It operates on normalized local records;
//! acquisition and credentials remain outside Rust.

use std::collections::{BTreeMap, HashMap, HashSet, hash_map::DefaultHasher};
use std::fs::File;
use std::hash::{Hash, Hasher};
use std::io::{BufRead, BufReader};
use std::path::Path;

use serde::{Deserialize, Serialize};

pub mod http;
pub mod simulation;

pub type RootId = String;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct DatasetRef {
    pub id: String,
    pub snapshot: String,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct ProductProvenance {
    pub name: String,
    pub filename: String,
    pub sha256: String,
    pub row_count: usize,
    pub source_product: String,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct SourceProvenance {
    pub source_manifest_sha256: String,
    pub license: String,
    pub citations: Vec<String>,
    pub products: Vec<ProductProvenance>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Neuron {
    pub root_id: RootId,
    pub primary_type: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Edge {
    pub pre_root_id: RootId,
    pub post_root_id: RootId,
    pub neuropil: String,
    pub synapse_count: u64,
    pub nt_type: Option<String>,
}

impl Edge {
    fn cmp(left: &Self, right: &Self) -> std::cmp::Ordering {
        left.pre_root_id
            .cmp(&right.pre_root_id)
            .then_with(|| left.post_root_id.cmp(&right.post_root_id))
            .then_with(|| left.neuropil.cmp(&right.neuropil))
            .then_with(|| left.synapse_count.cmp(&right.synapse_count))
            .then_with(|| left.nt_type.cmp(&right.nt_type))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Direction {
    Incoming,
    Outgoing,
    Both,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Query {
    pub root_id: RootId,
    pub direction: Direction,
    pub limit: usize,
    pub cursor: Option<String>,
    pub min_synapses: u64,
    pub aggregate: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ServiceLimits {
    pub page_limit_max: usize,
    pub graph_cap: usize,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ConnectionResponse {
    pub dataset: DatasetRef,
    pub schema_version: u32,
    pub provenance_ref: String,
    pub provenance: SourceProvenance,
    pub nodes: Vec<Neuron>,
    pub edges: Vec<Edge>,
    pub aggregation_rule: Option<String>,
    pub next_cursor: Option<String>,
    pub truncated: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum QueryError {
    UnknownNeuron,
    InvalidRootId,
    InvalidLimit,
    InvalidThreshold,
    InvalidConfiguration,
    InvalidArtifactHash,
    ArithmeticOverflow,
    CursorMalformed,
    CursorMismatch,
    CursorOutOfRange,
    GraphCapExceeded,
}

#[derive(Clone, Debug)]
pub struct GraphService {
    dataset: DatasetRef,
    schema_version: u32,
    artifact_hash: String,
    provenance_ref: String,
    source_provenance: SourceProvenance,
    neurons: BTreeMap<RootId, Neuron>,
    pair_totals: HashMap<(RootId, RootId), u64>,
    outgoing: HashMap<RootId, Vec<Edge>>,
    incoming: HashMap<RootId, Vec<Edge>>,
    page_limit_max: usize,
    graph_cap: usize,
}

impl GraphService {
    /// Load the deterministic JSONL artifact produced by the Python normalizer.
    /// The loader is intentionally read-only and accepts only the expected files.
    pub fn from_normalized_dir(
        directory: impl AsRef<Path>,
        limits: ServiceLimits,
    ) -> Result<Self, String> {
        #[derive(Deserialize)]
        struct Manifest {
            dataset: String,
            snapshot: String,
            artifact_hash: String,
            source_manifest_sha256: String,
            source_provenance: SourceProvenance,
        }
        #[derive(Deserialize)]
        struct NormalizedNeuron {
            root_id: String,
            primary_type: Option<String>,
        }
        #[derive(Deserialize)]
        struct NormalizedEdge {
            pre_root_id: String,
            post_root_id: String,
            neuropil: String,
            synapse_count: u64,
            nt_type: Option<String>,
        }

        let directory = directory.as_ref();
        let manifest: Manifest = serde_json::from_reader(
            File::open(directory.join("manifest.json")).map_err(|error| error.to_string())?,
        )
        .map_err(|error| error.to_string())?;
        let neurons = BufReader::new(
            File::open(directory.join("neurons.jsonl")).map_err(|error| error.to_string())?,
        )
        .lines()
        .map(|line| {
            let line = line.map_err(|error| error.to_string())?;
            let neuron: NormalizedNeuron =
                serde_json::from_str(&line).map_err(|error| error.to_string())?;
            Ok(Neuron {
                root_id: neuron.root_id,
                primary_type: neuron.primary_type,
            })
        })
        .collect::<Result<Vec<_>, String>>()?;
        let edges = BufReader::new(
            File::open(directory.join("edges.jsonl")).map_err(|error| error.to_string())?,
        )
        .lines()
        .map(|line| {
            let line = line.map_err(|error| error.to_string())?;
            let edge: NormalizedEdge =
                serde_json::from_str(&line).map_err(|error| error.to_string())?;
            Ok(Edge {
                pre_root_id: edge.pre_root_id,
                post_root_id: edge.post_root_id,
                neuropil: edge.neuropil,
                synapse_count: edge.synapse_count,
                nt_type: edge.nt_type,
            })
        })
        .collect::<Result<Vec<_>, String>>()?;
        let provenance_ref = format!("manifest-sha256:{}", manifest.artifact_hash);
        let mut service = Self::new(
            DatasetRef {
                id: manifest.dataset,
                snapshot: manifest.snapshot,
            },
            1,
            manifest.artifact_hash,
            provenance_ref,
            neurons,
            edges,
            limits,
        )
        .map_err(|error| format!("normalized artifact is invalid: {error:?}"))?;
        if manifest.source_manifest_sha256 != manifest.source_provenance.source_manifest_sha256 {
            return Err("normalized provenance hash is inconsistent".to_string());
        }
        service.source_provenance = manifest.source_provenance;
        service.source_provenance.source_manifest_sha256 = manifest.source_manifest_sha256;
        Ok(service)
    }

    pub fn neuron(&self, root_id: &str) -> Result<Neuron, QueryError> {
        if !is_ascii_root_id(root_id) {
            return Err(QueryError::InvalidRootId);
        }
        self.neurons
            .get(root_id)
            .cloned()
            .ok_or(QueryError::UnknownNeuron)
    }

    pub fn dataset(&self) -> &DatasetRef {
        &self.dataset
    }

    pub fn provenance_ref(&self) -> &str {
        &self.provenance_ref
    }

    pub fn source_provenance(&self) -> &SourceProvenance {
        &self.source_provenance
    }

    pub fn search_neurons(
        &self,
        root_id: Option<&str>,
        primary_type: Option<&str>,
        limit: usize,
    ) -> Result<Vec<Neuron>, QueryError> {
        if limit == 0 || limit > self.page_limit_max {
            return Err(QueryError::InvalidLimit);
        }
        if let Some(root_id) = root_id {
            if !is_ascii_root_id(root_id) {
                return Err(QueryError::InvalidRootId);
            }
        }
        let results = self
            .neurons
            .values()
            .filter(|neuron| root_id.is_none_or(|id| neuron.root_id == id))
            .filter(|neuron| {
                primary_type
                    .is_none_or(|requested| neuron.primary_type.as_deref() == Some(requested))
            })
            .take(limit)
            .cloned()
            .collect();
        Ok(results)
    }

    pub fn new(
        dataset: DatasetRef,
        schema_version: u32,
        artifact_hash: String,
        provenance_ref: String,
        neurons: Vec<Neuron>,
        mut edges: Vec<Edge>,
        limits: ServiceLimits,
    ) -> Result<Self, QueryError> {
        if limits.page_limit_max == 0 || limits.graph_cap == 0 {
            return Err(QueryError::InvalidConfiguration);
        }
        if artifact_hash.len() != 64
            || !artifact_hash.bytes().all(|byte| byte.is_ascii_hexdigit())
            || artifact_hash.contains('|')
        {
            return Err(QueryError::InvalidArtifactHash);
        }
        let mut neuron_map = BTreeMap::new();
        for neuron in neurons {
            if !is_ascii_root_id(&neuron.root_id) {
                return Err(QueryError::InvalidRootId);
            }
            if neuron_map.insert(neuron.root_id.clone(), neuron).is_some() {
                return Err(QueryError::InvalidRootId);
            }
        }
        if edges.iter().any(|edge| {
            !is_ascii_root_id(&edge.pre_root_id)
                || !is_ascii_root_id(&edge.post_root_id)
                || edge.synapse_count == 0
                || !neuron_map.contains_key(&edge.pre_root_id)
                || !neuron_map.contains_key(&edge.post_root_id)
        }) {
            return Err(QueryError::InvalidRootId);
        }
        edges.sort_by(Edge::cmp);
        let mut pair_totals = HashMap::new();
        let mut outgoing: HashMap<RootId, Vec<Edge>> = HashMap::new();
        let mut incoming: HashMap<RootId, Vec<Edge>> = HashMap::new();
        for edge in &edges {
            let pair = (edge.pre_root_id.clone(), edge.post_root_id.clone());
            let total = pair_totals.entry(pair).or_insert(0u64);
            *total = (*total)
                .checked_add(edge.synapse_count)
                .ok_or(QueryError::ArithmeticOverflow)?;
            outgoing
                .entry(edge.pre_root_id.clone())
                .or_default()
                .push(edge.clone());
            incoming
                .entry(edge.post_root_id.clone())
                .or_default()
                .push(edge.clone());
        }
        Ok(Self {
            dataset,
            schema_version,
            artifact_hash,
            provenance_ref,
            source_provenance: SourceProvenance::default(),
            neurons: neuron_map,
            pair_totals,
            outgoing,
            incoming,
            page_limit_max: limits.page_limit_max,
            graph_cap: limits.graph_cap,
        })
    }

    pub fn query_connections(&self, query: &Query) -> Result<ConnectionResponse, QueryError> {
        if !is_ascii_root_id(&query.root_id) {
            return Err(QueryError::InvalidRootId);
        }
        if !self.neurons.contains_key(&query.root_id) {
            return Err(QueryError::UnknownNeuron);
        }
        if query.limit == 0 || query.limit > self.page_limit_max {
            return Err(QueryError::InvalidLimit);
        }
        if query.min_synapses == 0 {
            return Err(QueryError::InvalidThreshold);
        }

        let candidates = self.filtered_edges(query)?;
        let visible_len = candidates.len().min(self.graph_cap);
        let offset = if let Some(cursor) = &query.cursor {
            self.decode_cursor(cursor, query, visible_len)?
        } else {
            0
        };
        if candidates.len() > self.graph_cap && offset >= self.graph_cap {
            return Err(QueryError::GraphCapExceeded);
        }
        if offset > visible_len {
            return Err(QueryError::CursorOutOfRange);
        }
        let end = (offset + query.limit).min(visible_len);
        let page = candidates[offset..end].to_vec();
        let mut node_ids: HashSet<RootId> = HashSet::from([query.root_id.clone()]);
        for edge in &page {
            node_ids.insert(edge.pre_root_id.clone());
            node_ids.insert(edge.post_root_id.clone());
        }
        let nodes = self
            .neurons
            .iter()
            .filter(|(root_id, _)| node_ids.contains(*root_id))
            .map(|(_, neuron)| neuron.clone())
            .collect();
        let next_cursor = (end < visible_len).then(|| self.encode_cursor(query, end));
        Ok(ConnectionResponse {
            dataset: self.dataset.clone(),
            schema_version: self.schema_version,
            provenance_ref: self.provenance_ref.clone(),
            provenance: self.source_provenance.clone(),
            nodes,
            edges: page,
            aggregation_rule: query
                .aggregate
                .then(|| "sum_synapse_count_by_endpoint_pair".to_string()),
            next_cursor,
            truncated: candidates.len() > self.graph_cap,
        })
    }

    fn filtered_edges(&self, query: &Query) -> Result<Vec<Edge>, QueryError> {
        let mut candidates = Vec::new();
        match query.direction {
            Direction::Incoming => candidates.extend(
                self.incoming
                    .get(&query.root_id)
                    .cloned()
                    .unwrap_or_default(),
            ),
            Direction::Outgoing => candidates.extend(
                self.outgoing
                    .get(&query.root_id)
                    .cloned()
                    .unwrap_or_default(),
            ),
            Direction::Both => {
                candidates.extend(
                    self.outgoing
                        .get(&query.root_id)
                        .cloned()
                        .unwrap_or_default(),
                );
                candidates.extend(
                    self.incoming
                        .get(&query.root_id)
                        .into_iter()
                        .flatten()
                        .filter(|edge| {
                            !(edge.pre_root_id == query.root_id
                                && edge.post_root_id == query.root_id)
                        })
                        .cloned(),
                );
            }
        }
        candidates.sort_by(Edge::cmp);
        let mut qualifying: Vec<Edge> = candidates
            .into_iter()
            .filter(|edge| {
                self.pair_totals[&(edge.pre_root_id.clone(), edge.post_root_id.clone())]
                    >= query.min_synapses
            })
            .collect();
        if query.aggregate {
            let mut aggregated: BTreeMap<(RootId, RootId), Edge> = BTreeMap::new();
            for edge in qualifying.drain(..) {
                let key = (edge.pre_root_id.clone(), edge.post_root_id.clone());
                if let Some(current) = aggregated.get_mut(&key) {
                    current.synapse_count = current
                        .synapse_count
                        .checked_add(edge.synapse_count)
                        .ok_or(QueryError::ArithmeticOverflow)?;
                } else {
                    aggregated.insert(
                        key,
                        Edge {
                            pre_root_id: edge.pre_root_id,
                            post_root_id: edge.post_root_id,
                            neuropil: "__aggregated__".to_string(),
                            synapse_count: edge.synapse_count,
                            nt_type: None,
                        },
                    );
                }
            }
            qualifying = aggregated.into_values().collect();
        }
        qualifying.sort_by(Edge::cmp);
        Ok(qualifying)
    }

    fn encode_cursor(&self, query: &Query, offset: usize) -> String {
        let payload = format!(
            "{}|{}|{}|{}|{}|{}|{}|{}|{}",
            self.artifact_hash,
            self.schema_version,
            query.root_id,
            direction_name(query.direction),
            query.min_synapses,
            query.aggregate,
            self.page_limit_max,
            self.graph_cap,
            offset
        );
        format!("{payload}|{:016x}", cursor_checksum(&payload))
    }

    fn decode_cursor(
        &self,
        cursor: &str,
        query: &Query,
        visible_len: usize,
    ) -> Result<usize, QueryError> {
        let parts: Vec<&str> = cursor.split('|').collect();
        if parts.len() != 10 {
            return Err(QueryError::CursorMalformed);
        }
        let payload = parts[..9].join("|");
        let expected_checksum = format!("{:016x}", cursor_checksum(&payload));
        if parts[9] != expected_checksum {
            return Err(QueryError::CursorMismatch);
        }
        if parts[0] != self.artifact_hash
            || parts[1] != self.schema_version.to_string()
            || parts[2] != query.root_id
            || parts[3] != direction_name(query.direction)
            || parts[4] != query.min_synapses.to_string()
            || parts[5] != query.aggregate.to_string()
            || parts[6] != self.page_limit_max.to_string()
            || parts[7] != self.graph_cap.to_string()
        {
            return Err(QueryError::CursorMismatch);
        }
        let offset = parts[8]
            .parse::<usize>()
            .map_err(|_| QueryError::CursorMalformed)?;
        if offset > visible_len {
            return Err(QueryError::CursorOutOfRange);
        }
        Ok(offset)
    }
}

fn cursor_checksum(payload: &str) -> u64 {
    let mut hasher = DefaultHasher::new();
    payload.hash(&mut hasher);
    hasher.finish()
}

fn is_ascii_root_id(value: &str) -> bool {
    !value.is_empty() && value.bytes().all(|byte| byte.is_ascii_digit())
}

fn direction_name(direction: Direction) -> &'static str {
    match direction {
        Direction::Incoming => "incoming",
        Direction::Outgoing => "outgoing",
        Direction::Both => "both",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn service(graph_cap: usize) -> GraphService {
        GraphService::new(
            DatasetRef {
                id: "synthetic".into(),
                snapshot: "fixture-1".into(),
            },
            1,
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(),
            "manifest-sha256:fixture".into(),
            vec![
                Neuron {
                    root_id: "100".into(),
                    primary_type: Some("source".into()),
                },
                Neuron {
                    root_id: "200".into(),
                    primary_type: Some("target".into()),
                },
                Neuron {
                    root_id: "300".into(),
                    primary_type: None,
                },
            ],
            vec![
                Edge {
                    pre_root_id: "100".into(),
                    post_root_id: "200".into(),
                    neuropil: "A".into(),
                    synapse_count: 2,
                    nt_type: Some("ACh".into()),
                },
                Edge {
                    pre_root_id: "100".into(),
                    post_root_id: "200".into(),
                    neuropil: "B".into(),
                    synapse_count: 3,
                    nt_type: Some("ACh".into()),
                },
                Edge {
                    pre_root_id: "200".into(),
                    post_root_id: "100".into(),
                    neuropil: "A".into(),
                    synapse_count: 5,
                    nt_type: Some("GABA".into()),
                },
            ],
            ServiceLimits {
                page_limit_max: 2,
                graph_cap,
            },
        )
        .expect("fixture graph is valid")
    }

    #[test]
    fn pair_threshold_preserves_rows_and_direction() {
        let response = service(10)
            .query_connections(&Query {
                root_id: "100".into(),
                direction: Direction::Outgoing,
                limit: 2,
                cursor: None,
                min_synapses: 5,
                aggregate: false,
            })
            .expect("query succeeds");
        assert_eq!(response.edges.len(), 2);
        assert!(response.edges.iter().all(|edge| edge.pre_root_id == "100"));
        assert!(response.nodes.iter().any(|node| node.root_id == "100"));
    }

    #[test]
    fn aggregation_sums_pair_and_keeps_orientation() {
        let response = service(10)
            .query_connections(&Query {
                root_id: "100".into(),
                direction: Direction::Both,
                limit: 2,
                cursor: None,
                min_synapses: 5,
                aggregate: true,
            })
            .expect("query succeeds");
        assert_eq!(response.edges.len(), 2);
        assert_eq!(response.edges[0].pre_root_id, "100");
        assert_eq!(response.edges[0].post_root_id, "200");
        assert_eq!(response.edges[0].synapse_count, 5);
        assert_eq!(
            response.aggregation_rule.as_deref(),
            Some("sum_synapse_count_by_endpoint_pair")
        );
    }

    #[test]
    fn cursor_is_bound_to_query_and_artifact() {
        let first = service(10)
            .query_connections(&Query {
                root_id: "100".into(),
                direction: Direction::Both,
                limit: 1,
                cursor: None,
                min_synapses: 5,
                aggregate: false,
            })
            .expect("query succeeds");
        let cursor = first.next_cursor.expect("second page exists");
        let second = service(10)
            .query_connections(&Query {
                root_id: "100".into(),
                direction: Direction::Both,
                limit: 1,
                cursor: Some(cursor.clone()),
                min_synapses: 5,
                aggregate: false,
            })
            .expect("cursor succeeds");
        assert_eq!(second.edges.len(), 1);
        let mismatch = service(10).query_connections(&Query {
            root_id: "100".into(),
            direction: Direction::Outgoing,
            limit: 1,
            cursor: Some(cursor.clone()),
            min_synapses: 5,
            aggregate: false,
        });
        assert_eq!(mismatch, Err(QueryError::CursorMismatch));

        let mut modified = service(10);
        let mut tampered_parts: Vec<String> = cursor.split('|').map(str::to_string).collect();
        tampered_parts[8] = "9".into();
        let tampered = tampered_parts.join("|");
        assert_eq!(
            modified.query_connections(&Query {
                root_id: "100".into(),
                direction: Direction::Both,
                limit: 1,
                cursor: Some(tampered),
                min_synapses: 5,
                aggregate: false,
            }),
            Err(QueryError::CursorMismatch)
        );
        modified.artifact_hash = "different-artifact".into();
        assert_eq!(
            modified.query_connections(&Query {
                root_id: "100".into(),
                direction: Direction::Both,
                limit: 1,
                cursor: Some(cursor.clone()),
                min_synapses: 5,
                aggregate: false,
            }),
            Err(QueryError::CursorMismatch)
        );

        let out_of_range = service(10).encode_cursor(
            &Query {
                root_id: "100".into(),
                direction: Direction::Both,
                limit: 1,
                cursor: None,
                min_synapses: 5,
                aggregate: false,
            },
            999,
        );
        assert_eq!(
            service(10).query_connections(&Query {
                root_id: "100".into(),
                direction: Direction::Both,
                limit: 1,
                cursor: Some(out_of_range),
                min_synapses: 5,
                aggregate: false,
            }),
            Err(QueryError::CursorOutOfRange)
        );
    }

    #[test]
    fn limits_caps_and_selected_node_are_explicit() {
        assert_eq!(
            service(10).query_connections(&Query {
                root_id: "100".into(),
                direction: Direction::Outgoing,
                limit: 3,
                cursor: None,
                min_synapses: 5,
                aggregate: false
            }),
            Err(QueryError::InvalidLimit)
        );
        let capped = service(1)
            .query_connections(&Query {
                root_id: "300".into(),
                direction: Direction::Both,
                limit: 1,
                cursor: None,
                min_synapses: 5,
                aggregate: false,
            })
            .expect("empty result succeeds");
        assert_eq!(capped.nodes.len(), 1);
        assert_eq!(capped.nodes[0].root_id, "300");
        assert!(capped.edges.is_empty());
        let capped_graph = service(1)
            .query_connections(&Query {
                root_id: "100".into(),
                direction: Direction::Outgoing,
                limit: 1,
                cursor: None,
                min_synapses: 5,
                aggregate: false,
            })
            .expect("bounded result succeeds");
        assert_eq!(capped_graph.edges.len(), 1);
        assert!(capped_graph.truncated);
    }

    #[test]
    fn graph_cap_supports_multiple_pages_then_stops() {
        let mut graph = service(2);
        graph.outgoing.get_mut("100").unwrap().push(Edge {
            pre_root_id: "100".into(),
            post_root_id: "200".into(),
            neuropil: "C".into(),
            synapse_count: 1,
            nt_type: Some("ACh".into()),
        });
        let first = graph
            .query_connections(&Query {
                root_id: "100".into(),
                direction: Direction::Outgoing,
                limit: 1,
                cursor: None,
                min_synapses: 5,
                aggregate: false,
            })
            .expect("first page succeeds");
        assert!(first.truncated);
        let second = graph
            .query_connections(&Query {
                root_id: "100".into(),
                direction: Direction::Outgoing,
                limit: 1,
                cursor: first.next_cursor,
                min_synapses: 5,
                aggregate: false,
            })
            .expect("second page succeeds");
        assert_eq!(second.edges.len(), 1);
        assert!(second.next_cursor.is_none());
        assert!(second.truncated);
    }

    #[test]
    fn invalid_artifact_hash_is_rejected() {
        let result = GraphService::new(
            DatasetRef {
                id: "synthetic".into(),
                snapshot: "fixture-1".into(),
            },
            1,
            "artifact123".into(),
            "manifest-sha256:fixture".into(),
            vec![Neuron {
                root_id: "100".into(),
                primary_type: None,
            }],
            Vec::new(),
            ServiceLimits {
                page_limit_max: 1,
                graph_cap: 1,
            },
        );
        assert!(matches!(result, Err(QueryError::InvalidArtifactHash)));
    }

    #[test]
    fn constructor_and_pair_totals_reject_overflow() {
        let result = GraphService::new(
            DatasetRef {
                id: "synthetic".into(),
                snapshot: "fixture-1".into(),
            },
            1,
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(),
            "manifest-sha256:fixture".into(),
            vec![
                Neuron {
                    root_id: "100".into(),
                    primary_type: None,
                },
                Neuron {
                    root_id: "200".into(),
                    primary_type: None,
                },
            ],
            vec![
                Edge {
                    pre_root_id: "100".into(),
                    post_root_id: "200".into(),
                    neuropil: "A".into(),
                    synapse_count: u64::MAX,
                    nt_type: None,
                },
                Edge {
                    pre_root_id: "100".into(),
                    post_root_id: "200".into(),
                    neuropil: "B".into(),
                    synapse_count: 1,
                    nt_type: None,
                },
            ],
            ServiceLimits {
                page_limit_max: 10,
                graph_cap: 10,
            },
        );
        assert!(matches!(result, Err(QueryError::ArithmeticOverflow)));
    }

    #[test]
    fn aggregation_checks_addition_and_sort_ties() {
        let mut graph = service(10);
        graph
            .outgoing
            .get_mut("100")
            .expect("outgoing fixture")
            .push(Edge {
                pre_root_id: "100".into(),
                post_root_id: "200".into(),
                neuropil: "A".into(),
                synapse_count: u64::MAX,
                nt_type: None,
            });
        let overflow = graph.query_connections(&Query {
            root_id: "100".into(),
            direction: Direction::Outgoing,
            limit: 2,
            cursor: None,
            min_synapses: 1,
            aggregate: true,
        });
        assert_eq!(overflow, Err(QueryError::ArithmeticOverflow));

        let mut duplicate = service(10);
        duplicate
            .outgoing
            .get_mut("100")
            .expect("outgoing fixture")
            .push(Edge {
                pre_root_id: "100".into(),
                post_root_id: "200".into(),
                neuropil: "A".into(),
                synapse_count: 1,
                nt_type: None,
            });
        let response = duplicate
            .query_connections(&Query {
                root_id: "100".into(),
                direction: Direction::Outgoing,
                limit: 2,
                cursor: None,
                min_synapses: 1,
                aggregate: false,
            })
            .expect("query succeeds");
        assert_eq!(response.edges[0].synapse_count, 1);
        assert_eq!(response.edges[1].synapse_count, 2);

        let mut identical = service(10);
        identical
            .outgoing
            .get_mut("100")
            .expect("outgoing fixture")
            .push(Edge {
                pre_root_id: "100".into(),
                post_root_id: "200".into(),
                neuropil: "A".into(),
                synapse_count: 2,
                nt_type: Some("ACh".into()),
            });
        let preserved = identical
            .query_connections(&Query {
                root_id: "100".into(),
                direction: Direction::Outgoing,
                limit: 2,
                cursor: None,
                min_synapses: 1,
                aggregate: false,
            })
            .expect("query preserves duplicate source rows");
        assert_eq!(preserved.edges.len(), 2);
        assert_eq!(
            preserved
                .edges
                .iter()
                .filter(|edge| edge.neuropil == "A" && edge.synapse_count == 2)
                .count(),
            2
        );
    }

    #[test]
    fn incoming_orientation_and_empty_result_are_stable() {
        let incoming = service(10)
            .query_connections(&Query {
                root_id: "100".into(),
                direction: Direction::Incoming,
                limit: 2,
                cursor: None,
                min_synapses: 5,
                aggregate: false,
            })
            .expect("query succeeds");
        assert!(incoming.edges.iter().all(|edge| edge.post_root_id == "100"));
        let empty = service(10)
            .query_connections(&Query {
                root_id: "300".into(),
                direction: Direction::Both,
                limit: 1,
                cursor: None,
                min_synapses: 5,
                aggregate: false,
            })
            .expect("query succeeds");
        assert!(empty.edges.is_empty());
        assert_eq!(
            empty.nodes,
            vec![Neuron {
                root_id: "300".into(),
                primary_type: None
            }]
        );
    }
}
