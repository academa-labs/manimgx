//! Link the complete decoder into an executable, so a missing native symbol
//! fails at build time rather than when Python loads its shared library.

#[test]
fn pcm_wave_is_decoded_without_external_libraries() {
    let mut wav = Vec::from(&b"RIFF\x2c\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80\xbb\x00\x00\x00\x77\x01\x00\x02\x00\x10\x00data\x08\x00\x00\x00"[..]);
    for sample in [0_i16, 16384, -16384, 0] {
        wav.extend(sample.to_le_bytes());
    }
    let (samples, rate, channels) = ffmpeg::decode(&wav).unwrap();
    assert_eq!(rate, 48000);
    assert_eq!(channels, 1);
    assert_eq!(samples, [0.0, 0.5, -0.5, 0.0]);
}
