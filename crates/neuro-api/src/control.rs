//! Validated, bounded M4 control input contract.

use std::collections::VecDeque;

use serde::{Deserialize, Serialize};

use crate::simulation::CONTROL_SCHEMA_VERSION;

pub const CONTROL_AUTHORITY: f64 = 0.25;
pub const CONTROL_QUEUE_CAPACITY: usize = 32;

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ChannelControl {
    pub forward: f64,
    pub lateral: f64,
    pub turn: f64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ControlInput {
    pub schema_version: u32,
    pub control_session_id: String,
    pub sequence: u64,
    pub issued_at_ms: u64,
    pub control: ChannelControl,
    pub source: String,
    pub mode: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ControlAck {
    pub schema_version: u32,
    pub accepted: bool,
    pub coalesced: bool,
    pub dropped_events: u64,
    pub queue_depth: usize,
    pub forwarded: bool,
    pub sequence: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ControlError {
    InvalidSchema,
    InvalidControl,
    InvalidSource,
    StaleSession,
    StaleSequence,
    ControlPaused,
    QueueFull,
}

#[derive(Clone, Debug)]
struct QueuedControl {
    sequence: u64,
    values: Vec<f64>,
    mode: String,
}

#[derive(Debug)]
pub struct ControlQueue {
    capacity: usize,
    pending: VecDeque<QueuedControl>,
    last_sequence: u64,
    dropped_events: u64,
    coalesced_events: u64,
}

impl Default for ControlQueue {
    fn default() -> Self {
        Self::new(CONTROL_QUEUE_CAPACITY)
    }
}

impl ControlQueue {
    pub fn new(capacity: usize) -> Self {
        Self {
            capacity,
            pending: VecDeque::new(),
            last_sequence: 0,
            dropped_events: 0,
            coalesced_events: 0,
        }
    }

    pub fn enqueue(
        &mut self,
        input: &ControlInput,
        current_session_id: &str,
        session_status: &str,
        actuator_count: usize,
    ) -> Result<ControlAck, ControlError> {
        if input.schema_version != CONTROL_SCHEMA_VERSION {
            return Err(ControlError::InvalidSchema);
        }
        if input.control_session_id != current_session_id {
            return Err(ControlError::StaleSession);
        }
        if session_status != "active" {
            return Err(ControlError::ControlPaused);
        }
        if input.sequence == 0 || input.sequence <= self.last_sequence {
            return Err(ControlError::StaleSequence);
        }
        if !matches!(input.source.as_str(), "keyboard" | "gamepad") {
            return Err(ControlError::InvalidSource);
        }
        let channels = [
            input.control.forward,
            input.control.lateral,
            input.control.turn,
        ];
        if !channels
            .iter()
            .all(|value| value.is_finite() && (-1.0..=1.0).contains(value))
            || !matches!(input.mode.as_str(), "active" | "neutral")
            || actuator_count == 0
            || self.capacity == 0
        {
            return Err(ControlError::InvalidControl);
        }
        let values = if input.mode == "neutral" {
            vec![0.0; actuator_count]
        } else {
            (0..actuator_count)
                .map(|index| {
                    (channels[index % channels.len()] * CONTROL_AUTHORITY)
                        .clamp(-CONTROL_AUTHORITY, CONTROL_AUTHORITY)
                })
                .collect()
        };
        self.last_sequence = input.sequence;
        let coalesced = self.pending.pop_back().is_some();
        if coalesced {
            self.coalesced_events += 1;
        }
        if self.pending.len() >= self.capacity {
            self.pending.pop_front();
            self.dropped_events += 1;
        }
        self.pending.push_back(QueuedControl {
            sequence: input.sequence,
            values,
            mode: input.mode.clone(),
        });
        Ok(ControlAck {
            schema_version: CONTROL_SCHEMA_VERSION,
            accepted: true,
            coalesced,
            dropped_events: self.dropped_events,
            queue_depth: self.pending.len(),
            forwarded: false,
            sequence: input.sequence,
        })
    }

    pub fn pop_latest(&mut self) -> Option<(u64, Vec<f64>, String)> {
        self.pending
            .pop_back()
            .map(|item| (item.sequence, item.values, item.mode))
    }

    pub fn reset(&mut self) {
        self.pending.clear();
        self.last_sequence = 0;
        self.dropped_events = 0;
        self.coalesced_events = 0;
    }

    pub fn last_sequence(&self) -> u64 {
        self.last_sequence
    }

    pub fn coalesced_events(&self) -> u64 {
        self.coalesced_events
    }
}

#[cfg(test)]
mod tests {
    use super::{ChannelControl, ControlError, ControlInput, ControlQueue};

    fn input(sequence: u64) -> ControlInput {
        ControlInput {
            schema_version: 1,
            control_session_id: "control".into(),
            sequence,
            issued_at_ms: 1,
            control: ChannelControl {
                forward: 1.0,
                lateral: -0.5,
                turn: 0.25,
            },
            source: "keyboard".into(),
            mode: "active".into(),
        }
    }

    #[test]
    fn maps_channels_to_bounded_actuator_values() {
        let mut queue = ControlQueue::default();
        let ack = queue.enqueue(&input(1), "control", "active", 5).unwrap();
        assert!(!ack.forwarded);
        assert_eq!(
            queue.pop_latest().unwrap().1,
            vec![0.25, -0.125, 0.0625, 0.25, -0.125]
        );
    }

    #[test]
    fn latest_value_wins_and_stale_sequences_are_rejected() {
        let mut queue = ControlQueue::default();
        queue.enqueue(&input(1), "control", "active", 2).unwrap();
        let second = queue.enqueue(&input(2), "control", "active", 2).unwrap();
        assert!(second.coalesced);
        assert_eq!(queue.coalesced_events(), 1);
        let latest = queue.pop_latest().unwrap();
        assert_eq!(latest.0, 2);
        assert_eq!(latest.2, "active");
        assert!(matches!(
            queue.enqueue(&input(2), "control", "active", 2),
            Err(ControlError::StaleSequence)
        ));
    }

    #[test]
    fn rejects_invalid_session_input_and_paused_state() {
        let mut queue = ControlQueue::default();
        assert!(matches!(
            queue.enqueue(&input(1), "other", "active", 2),
            Err(ControlError::StaleSession)
        ));
        assert!(matches!(
            queue.enqueue(&input(1), "control", "paused", 2),
            Err(ControlError::ControlPaused)
        ));
    }
}
