//! Execute the linked native decoder, including libopus. An rlib alone can hide unresolved C
//! symbols until Python imports the engine; these tests require a working executable first.

#[test]
fn opus_silence() {
    // A 20 ms mono Opus packet (f8 ff fe), in three Ogg pages: OpusHead (no pre-skip),
    // OpusTags (empty), and the packet (final granule 960). No encoder or external tool needed.
    let (samples, rate, channels) = ffmpeg::decode(include_bytes!("silence.opus")).unwrap();
    assert_eq!((samples.len(), rate, channels), (960, 48_000, 1));
    assert!(
        samples
            .iter()
            .all(|sample| sample.is_finite() && sample.abs() < 1e-6)
    );
}

#[test]
fn rejects_invalid_audio() {
    for bytes in [b"".as_slice(), b"not an audio file"] {
        assert!(ffmpeg::decode(bytes).is_err());
    }
}
