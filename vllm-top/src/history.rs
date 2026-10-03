//! Fixed-size history rings feeding the graphs and sparklines.

use crate::metrics::Derived;
use std::collections::VecDeque;

#[derive(Clone, Debug)]
pub struct Ring {
    buf: VecDeque<f64>,
    cap: usize,
}

impl Ring {
    pub fn new(cap: usize) -> Self {
        Self {
            buf: VecDeque::with_capacity(cap),
            cap,
        }
    }

    pub fn push(&mut self, value: f64) {
        if self.buf.len() == self.cap {
            self.buf.pop_front();
        }
        self.buf.push_back(value);
    }

    pub fn is_empty(&self) -> bool {
        self.buf.is_empty()
    }

    /// Most recent sample (0.0 when empty).
    pub fn last(&self) -> f64 {
        self.buf.back().copied().unwrap_or(0.0)
    }

    /// Newest sample on the right, oldest on the left.
    pub fn values(&self) -> Vec<f64> {
        self.buf.iter().copied().collect()
    }
}

#[derive(Clone, Debug)]
pub struct Histories {
    pub gen_tps: Ring,
    pub prompt_tps: Ring,
    pub req_per_s: Ring,
    pub kv: Ring,
    pub running: Ring,
    pub waiting: Ring,
    pub ttft_p99: Ring,
    pub queue_p99: Ring,
    pub e2e_p99: Ring,
    pub itl_p99: Ring,
}

impl Histories {
    pub fn new(cap: usize) -> Self {
        Self {
            gen_tps: Ring::new(cap),
            prompt_tps: Ring::new(cap),
            req_per_s: Ring::new(cap),
            kv: Ring::new(cap),
            running: Ring::new(cap),
            waiting: Ring::new(cap),
            ttft_p99: Ring::new(cap),
            queue_p99: Ring::new(cap),
            e2e_p99: Ring::new(cap),
            itl_p99: Ring::new(cap),
        }
    }

    pub fn push(&mut self, d: &Derived) {
        self.gen_tps.push(d.gen_tps);
        self.prompt_tps.push(d.prompt_tps);
        self.req_per_s.push(d.req_per_s);
        self.kv.push(d.kv);
        self.running.push(d.running);
        self.waiting.push(d.waiting);
        self.ttft_p99.push(d.ttft_p99);
        self.queue_p99.push(d.queue_p99);
        self.e2e_p99.push(d.e2e_p99);
        self.itl_p99.push(d.itl_p99);
    }
}
