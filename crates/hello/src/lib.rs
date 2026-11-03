pub fn health() -> &'static str {
    "ok"
}

#[cfg(test)]
mod tests {
    use super::health;

    #[test]
    fn health_is_deterministic() {
        assert_eq!(health(), "ok");
    }
}
