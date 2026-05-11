//! Sound in: any common audio file decoded by FFmpeg (the `ffmpeg` crate: WAV, AIFF, CAF, MP3,
//! AAC (with SBR and PS), Opus, Vorbis, FLAC and ALAC, in their files and in MP4, MOV, WebM and
//! Matroska) to float samples, at most two channels, starting and ending where the file declares;
//! and resampled — band-limited, a Kaiser-windowed sinc — to the film's rate.

use std::f64::consts::PI;

/// A file's audio: interleaved float samples, its rate and its channel count (1 or 2).
pub fn decode(data: Vec<u8>) -> Result<(Vec<f32>, u32, usize), String> {
    ffmpeg::decode(&data).map_err(|e| format!("not an audio file manimgx reads: {e}"))
}

/// Zero crossings of the sinc on each side of a sample: the filter's reach, in input samples
/// (more for downsampling, whose cutoff is lower).
const ZEROS: usize = 16;
/// The kernel's table: points per zero crossing (linearly interpolated between).
const DENSITY: usize = 512;
/// Kaiser's β: about 80 dB of stopband.
const BETA: f64 = 8.0;

fn bessel_i0(x: f64) -> f64 {
    let (mut sum, mut term, mut k) = (1.0, 1.0, 1.0);
    while term > 1e-12 * sum {
        term *= (x / (2.0 * k)) * (x / (2.0 * k));
        sum += term;
        k += 1.0;
    }
    sum
}

/// The filter, `cutoff` × sinc(`cutoff` × d) Kaiser-windowed, tabulated over its argument u =
/// `cutoff` × d from 0 to ZEROS zero crossings, DENSITY points per crossing.
fn kernel(cutoff: f64) -> Vec<f32> {
    let n = ZEROS * DENSITY;
    (0..=n + 1)
        .map(|i| {
            let x = i as f64 / DENSITY as f64; // in the scaled sinc's zero crossings
            let sinc = if x == 0.0 { 1.0 } else { (PI * x).sin() / (PI * x) };
            let r = (x / ZEROS as f64).min(1.0);
            (cutoff * sinc * bessel_i0(BETA * (1.0 - r * r).sqrt()) / bessel_i0(BETA)) as f32
        })
        .collect()
}

/// `input` (interleaved, `channels` channels) at `from` samples a second, resampled to `to`:
/// each output sample the band-limited interpolation of the input at its instant.
pub fn resample(input: &[f32], channels: usize, from: f64, to: f64) -> Vec<f32> {
    let frames = input.len() / channels;
    if from == to || frames == 0 {
        return input.to_vec();
    }
    let step = from / to; // input samples per output sample
    let cutoff = 0.95 * (1.0 / step).min(1.0); // below the lower Nyquist
    let table = kernel(cutoff);
    let reach = (ZEROS as f64 / cutoff).ceil() as isize; // input samples each side
    let count = ((frames as f64) / step).round() as usize;
    let mut out = vec![0.0f32; count * channels];
    let mut weights = Vec::with_capacity(2 * reach as usize + 1);
    for n in 0..count {
        let x = n as f64 * step;
        let center = x.floor() as isize;
        let (first, last) = ((center - reach + 1).max(0), (center + reach).min(frames as isize - 1));
        weights.clear();
        for k in first..=last {
            // the kernel at the distance, in its own zero crossings
            let t = (x - k as f64).abs() * cutoff * DENSITY as f64;
            let i = t as usize;
            let w = if i + 1 < table.len() {
                let f = (t - i as f64) as f32;
                table[i] * (1.0 - f) + table[i + 1] * f
            } else {
                0.0
            };
            weights.push(w);
        }
        let o = &mut out[n * channels..(n + 1) * channels];
        for (w, k) in weights.iter().zip(first..=last) {
            let s = &input[k as usize * channels..(k as usize + 1) * channels];
            for c in 0..channels {
                o[c] += w * s[c];
            }
        }
    }
    out
}
