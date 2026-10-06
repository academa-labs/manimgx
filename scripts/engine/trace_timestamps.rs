//! Disposable GPU timestamp instrumentation, injected only by trace_startup.py.
use std::sync::{Mutex, OnceLock};

const COUNT: u32 = 8192;
struct State { active: bool, frame: u64, spans: Vec<(&'static str, u32, u32)> }
struct Trace { queries: wgpu::QuerySet, resolved: wgpu::Buffer, readback: wgpu::Buffer, period: f64, state: Mutex<State> }
static TRACE: OnceLock<Trace> = OnceLock::new();

pub fn init(device: &wgpu::Device, queue: &wgpu::Queue) {
    let buffer = |usage| device.create_buffer(&wgpu::BufferDescriptor { label: Some("diagnostic timestamps"), size: COUNT as u64 * 8, usage, mapped_at_creation: false });
    assert!(TRACE.set(Trace {
        queries: device.create_query_set(&wgpu::QuerySetDescriptor { label: Some("diagnostic timestamps"), ty: wgpu::QueryType::Timestamp, count: COUNT }),
        resolved: buffer(wgpu::BufferUsages::QUERY_RESOLVE | wgpu::BufferUsages::COPY_SRC),
        readback: buffer(wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ),
        period: queue.get_timestamp_period() as f64,
        state: Mutex::new(State { active: false, frame: 0, spans: Vec::new() }),
    }).is_ok());
}

pub fn begin() {
    let mut state = TRACE.get().unwrap().state.lock().unwrap();
    assert!(!state.active, "previous timestamp frame was not collected");
    state.active = true;
    state.frame += 1;
    state.spans.clear();
    state.spans.push(("frame", 0, 1));
}

fn span(label: &'static str) -> Option<(&'static Trace, u32, u32)> {
    let trace = TRACE.get()?;
    let mut state = trace.state.lock().unwrap();
    if !state.active { return None; }
    let first = state.spans.len() as u32 * 2;
    assert!(first + 1 < COUNT, "diagnostic timestamp capacity exceeded");
    state.spans.push((label, first, first + 1));
    Some((trace, first, first + 1))
}

pub fn render(label: &'static str) -> Option<wgpu::RenderPassTimestampWrites<'static>> {
    span(label).map(|(trace, first, last)| wgpu::RenderPassTimestampWrites { query_set: &trace.queries, beginning_of_pass_write_index: Some(first), end_of_pass_write_index: Some(last) })
}

pub fn compute(label: &'static str) -> Option<wgpu::ComputePassTimestampWrites<'static>> {
    span(label).map(|(trace, first, last)| wgpu::ComputePassTimestampWrites { query_set: &trace.queries, beginning_of_pass_write_index: Some(first), end_of_pass_write_index: Some(last) })
}

pub fn dispatch_begin(pass: &mut wgpu::ComputePass, label: &'static str) -> Option<u32> {
    span(label).map(|(trace, first, last)| { pass.write_timestamp(&trace.queries, first); last })
}

pub fn dispatch_end(pass: &mut wgpu::ComputePass, last: Option<u32>) {
    if let Some(last) = last { pass.write_timestamp(&TRACE.get().unwrap().queries, last); }
}

pub fn start(encoder: &mut wgpu::CommandEncoder) {
    if let Some(trace) = TRACE.get().filter(|trace| trace.state.lock().unwrap().active) { encoder.write_timestamp(&trace.queries, 0); }
}

pub fn resolve(encoder: &mut wgpu::CommandEncoder) {
    let trace = TRACE.get().unwrap();
    let count = trace.state.lock().unwrap().spans.len() as u32 * 2;
    encoder.write_timestamp(&trace.queries, 1);
    encoder.resolve_query_set(&trace.queries, 0..count, &trace.resolved, 0);
    encoder.copy_buffer_to_buffer(&trace.resolved, 0, &trace.readback, 0, count as u64 * 8);
}

pub fn map() {
    let trace = TRACE.get().unwrap();
    let count = trace.state.lock().unwrap().spans.len() as u32 * 2;
    trace.readback.slice(..count as u64 * 8).map_async(wgpu::MapMode::Read, |result| result.expect("timestamp readback failed"));
}

pub fn collect() -> Result<(), String> {
    let trace = TRACE.get().unwrap();
    let mut state = trace.state.lock().unwrap();
    let count = state.spans.len() * 2;
    let data = trace.readback.slice(..count as u64 * 8).get_mapped_range().map_err(|e| e.to_string())?;
    let stamps: Vec<u64> = data.chunks_exact(8).map(|b| u64::from_le_bytes(b.try_into().unwrap())).collect();
    for &(label, first, last) in &state.spans {
        assert!(stamps[last as usize] >= stamps[first as usize], "nonmonotone GPU timestamps");
        let seconds = (stamps[last as usize] - stamps[first as usize]) as f64 * trace.period * 1e-9;
        eprintln!("gpu-pass\t{}\t{}\t{}\t{}\t{}\t{}\t{seconds:.9}", std::process::id(), state.frame, label, trace.period, stamps[first as usize], stamps[last as usize]);
    }
    drop(data);
    trace.readback.unmap();
    state.active = false;
    Ok(())
}
