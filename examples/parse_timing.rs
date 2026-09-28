//! Time the Rust half of the work (decoding + parsing into the arena) on
//! a file, with and without source position tracking.
//!
//!     cargo run --release --example parse_timing -- page.html
use std::time::Instant;

fn main() {
    let path = std::env::args().nth(1).expect("usage: parse_timing FILE");
    let text = std::fs::read_to_string(path).unwrap();
    for track in [false, true] {
        let mut best = f64::MAX;
        let mut nodes = 0;
        for _ in 0..20 {
            let start = Instant::now();
            nodes = _soup5ever::driver::parse_str(&text, track).nodes.len();
            best = best.min(start.elapsed().as_secs_f64());
        }
        println!(
            "positions={track:<5} {nodes} nodes  {:.2} ms  {:.0} MB/s",
            best * 1e3,
            text.len() as f64 / best / 1e6
        );
    }
}
