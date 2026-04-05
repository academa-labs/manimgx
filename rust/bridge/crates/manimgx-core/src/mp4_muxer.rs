//! MP4 muxer for single-track H.264 video.
//!
//! Pure Rust, zero external dependencies. Accepts Annex B H.264 NAL units,
//! converts to AVCC format, writes ISO 14496-12 compliant MP4.
//!
//! Three muxing strategies:
//! - **Ram** — buffer all mdat in memory, write faststart MP4 at finish
//! - **Disk** — stream mdat to temp file, assemble faststart MP4 at finish
//! - **Fmp4** — fragmented MP4, stream directly to output file

use std::fs::File;
use std::io::{self, BufWriter, Write};

// ── Public types ──────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum MuxerStrategy {
    Ram,
    Disk,
    Fmp4,
}

// ── Internal storage ──────────────────────────────────────────────

enum MdatStorage {
    Ram(Vec<u8>),
    Disk {
        writer: BufWriter<File>,
        temp_path: String,
        data_size: u64,
    },
    Fmp4 {
        writer: BufWriter<File>,
        sequence_number: u32,
        fragment_samples: Vec<SampleInfo>,
        fragment_mdat: Vec<u8>,
        base_decode_time: i64,
        flushed_init: bool,
    },
}

// ── Mp4Muxer ─────────────────────────────────────────────────────

pub struct Mp4Muxer {
    path: String,
    width: u32,
    height: u32,
    timescale: u32,

    sps: Vec<u8>,
    pps: Vec<u8>,

    samples: Vec<SampleInfo>,   // Ram/Disk only
    has_b_frames: bool,

    avcc_buf: Vec<u8>,
    storage: MdatStorage,
}

struct SampleInfo {
    size: u32,
    is_keyframe: bool,
    dts: i64,
    cts_offset: i32,
}

impl Mp4Muxer {
    pub fn new(
        path: &str,
        width: u32,
        height: u32,
        fps: f64,
        strategy: MuxerStrategy,
    ) -> io::Result<Self> {
        let storage = match strategy {
            MuxerStrategy::Ram => MdatStorage::Ram(Vec::with_capacity(4 * 1024 * 1024)),
            MuxerStrategy::Disk => {
                let temp_path = format!("{}.tmp", path);
                let file = File::create(&temp_path)?;
                MdatStorage::Disk {
                    writer: BufWriter::with_capacity(256 * 1024, file),
                    temp_path,
                    data_size: 0,
                }
            }
            MuxerStrategy::Fmp4 => {
                let file = File::create(path)?;
                MdatStorage::Fmp4 {
                    writer: BufWriter::with_capacity(256 * 1024, file),
                    sequence_number: 1,
                    fragment_samples: Vec::new(),
                    fragment_mdat: Vec::with_capacity(1024 * 1024),
                    base_decode_time: 0,
                    flushed_init: false,
                }
            }
        };

        Ok(Self {
            path: path.to_string(),
            width,
            height,
            timescale: fps.round() as u32,
            sps: Vec::new(),
            pps: Vec::new(),
            samples: Vec::new(),
            has_b_frames: false,
            avcc_buf: Vec::with_capacity(128 * 1024),
            storage,
        })
    }

    /// Write a video frame from pre-split NAL units (no start codes).
    pub fn write_video_nals(
        &mut self,
        pts_secs: f64,
        dts_secs: f64,
        nals: &[&[u8]],
        is_keyframe: bool,
    ) -> io::Result<()> {
        let ts = self.timescale as f64;
        let pts_ticks = (pts_secs * ts).round() as i64;
        let dts_ticks = (dts_secs * ts).round() as i64;
        let cts_offset = (pts_ticks - dts_ticks) as i32;

        if cts_offset != 0 {
            self.has_b_frames = true;
        }

        // Build AVCC data into avcc_buf, filtering SPS/PPS/SEI/AUD/filler
        self.avcc_buf.clear();
        for nal in nals {
            if nal.is_empty() {
                continue;
            }
            let nal_type = nal[0] & 0x1F;
            match nal_type {
                7 => {
                    if self.sps.is_empty() {
                        self.sps = nal.to_vec();
                    }
                    continue;
                }
                8 => {
                    if self.pps.is_empty() {
                        self.pps = nal.to_vec();
                    }
                    continue;
                }
                6 | 9 | 12 => continue,
                _ => {}
            }
            self.avcc_buf
                .extend_from_slice(&(nal.len() as u32).to_be_bytes());
            self.avcc_buf.extend_from_slice(nal);
        }

        if self.avcc_buf.is_empty() {
            return Ok(());
        }

        let sample = SampleInfo {
            size: self.avcc_buf.len() as u32,
            is_keyframe,
            dts: dts_ticks,
            cts_offset,
        };

        let mut avcc_data = std::mem::take(&mut self.avcc_buf);
        self.append_sample_data(&avcc_data, sample)?;
        avcc_data.clear();
        self.avcc_buf = avcc_data;

        Ok(())
    }

    /// Dispatch sample data to the active storage backend.
    fn append_sample_data(&mut self, data: &[u8], sample: SampleInfo) -> io::Result<()> {
        match &mut self.storage {
            MdatStorage::Ram(vec) => {
                vec.extend_from_slice(data);
                self.samples.push(sample);
            }
            MdatStorage::Disk {
                writer, data_size, ..
            } => {
                writer.write_all(data)?;
                *data_size += data.len() as u64;
                self.samples.push(sample);
            }
            MdatStorage::Fmp4 {
                writer,
                sequence_number,
                fragment_samples,
                fragment_mdat,
                base_decode_time,
                flushed_init,
            } => {
                // Write init segment on first sample with SPS/PPS available
                if !*flushed_init && !self.sps.is_empty() && !self.pps.is_empty() {
                    let ftyp = build_fmp4_ftyp();
                    let init_moov = build_fmp4_init_moov(
                        self.width,
                        self.height,
                        self.timescale,
                        &self.sps,
                        &self.pps,
                    );
                    writer.write_all(&ftyp)?;
                    writer.write_all(&init_moov)?;
                    *flushed_init = true;
                }

                // Flush previous fragment on keyframe boundary
                if sample.is_keyframe && !fragment_samples.is_empty() {
                    flush_fragment(
                        writer,
                        sequence_number,
                        fragment_samples,
                        fragment_mdat,
                        *base_decode_time,
                    )?;
                    // Advance base_decode_time to the DTS of this new keyframe
                    *base_decode_time = sample.dts;
                }

                // Set initial base_decode_time from first sample
                if fragment_samples.is_empty() && *base_decode_time == 0 {
                    *base_decode_time = sample.dts;
                }

                fragment_mdat.extend_from_slice(data);
                fragment_samples.push(sample);
            }
        }
        Ok(())
    }

    /// Finalize the MP4 file.
    pub fn finish(mut self) -> io::Result<()> {
        assert!(!self.sps.is_empty(), "No SPS found in H.264 stream");
        assert!(!self.pps.is_empty(), "No PPS found in H.264 stream");

        // Move storage out to avoid borrow conflicts with self.build_moov()
        let storage = std::mem::replace(
            &mut self.storage,
            MdatStorage::Ram(Vec::new()),
        );

        match storage {
            MdatStorage::Ram(mdat_body) => {
                let ftyp = build_ftyp();
                let ftyp_size = ftyp.len() as u64;
                let data_size = mdat_body.len() as u64;
                let mdat_hdr_size = mdat_header_size(data_size);
                let n_samples = self.samples.len();

                // Two-pass moov build with co64 auto-detection
                let moov_pass1 = self.build_moov(0, false);
                let stco_moov_size = moov_pass1.len() as u64;
                let base_stco = ftyp_size + stco_moov_size + mdat_hdr_size;

                let total_data: u64 = self.samples.iter().map(|s| s.size as u64).sum();
                let moov = if base_stco + total_data > u32::MAX as u64 {
                    let co64_moov_size = stco_moov_size + (4 * n_samples) as u64;
                    let base = ftyp_size + co64_moov_size + mdat_hdr_size;
                    let m = self.build_moov(base, true);
                    debug_assert_eq!(m.len() as u64, co64_moov_size);
                    m
                } else {
                    let m = self.build_moov(base_stco, false);
                    debug_assert_eq!(m.len() as u64, stco_moov_size);
                    m
                };

                let mdat_header = build_mdat_header(data_size);

                let file = File::create(&self.path)?;
                let mut writer = BufWriter::new(file);
                writer.write_all(&ftyp)?;
                writer.write_all(&moov)?;
                writer.write_all(&mdat_header)?;
                writer.write_all(&mdat_body)?;
                writer.flush()?;
            }
            MdatStorage::Disk {
                writer: mut disk_writer,
                temp_path,
                data_size,
            } => {
                disk_writer.flush()?;
                drop(disk_writer);

                let ftyp = build_ftyp();
                let ftyp_size = ftyp.len() as u64;
                let mdat_hdr_size = mdat_header_size(data_size);
                let n_samples = self.samples.len();

                // Two-pass moov build with co64 auto-detection
                let moov_pass1 = self.build_moov(0, false);
                let stco_moov_size = moov_pass1.len() as u64;
                let base_stco = ftyp_size + stco_moov_size + mdat_hdr_size;

                let total_data: u64 = self.samples.iter().map(|s| s.size as u64).sum();
                let moov = if base_stco + total_data > u32::MAX as u64 {
                    let co64_moov_size = stco_moov_size + (4 * n_samples) as u64;
                    let base = ftyp_size + co64_moov_size + mdat_hdr_size;
                    let m = self.build_moov(base, true);
                    debug_assert_eq!(m.len() as u64, co64_moov_size);
                    m
                } else {
                    let m = self.build_moov(base_stco, false);
                    debug_assert_eq!(m.len() as u64, stco_moov_size);
                    m
                };

                let mdat_header = build_mdat_header(data_size);

                // Write final file: ftyp + moov + mdat_header + copy temp data
                let file = File::create(&self.path)?;
                let mut out = BufWriter::with_capacity(256 * 1024, file);
                out.write_all(&ftyp)?;
                out.write_all(&moov)?;
                out.write_all(&mdat_header)?;

                let mut src = io::BufReader::with_capacity(256 * 1024, File::open(&temp_path)?);
                io::copy(&mut src, &mut out)?;
                out.flush()?;
                drop(src);

                let _ = std::fs::remove_file(&temp_path);
            }
            MdatStorage::Fmp4 {
                mut writer,
                mut sequence_number,
                mut fragment_samples,
                mut fragment_mdat,
                base_decode_time,
                ..
            } => {
                // Flush remaining fragment (last GOP)
                if !fragment_samples.is_empty() {
                    flush_fragment(
                        &mut writer,
                        &mut sequence_number,
                        &mut fragment_samples,
                        &mut fragment_mdat,
                        base_decode_time,
                    )?;
                }
                writer.flush()?;
            }
        }

        Ok(())
    }

    // ── moov construction ──────────────────────────────────────────────

    fn build_moov(&self, base_offset: u64, use_co64: bool) -> Vec<u8> {
        let duration = self.samples.len() as u32;
        let mvhd = self.build_mvhd(duration);
        let trak = self.build_trak(duration, base_offset, use_co64);
        mp4_box(b"moov", &[&mvhd, &trak])
    }

    fn build_mvhd(&self, duration: u32) -> Vec<u8> {
        let mut c = Vec::with_capacity(96);
        c.extend_from_slice(&0u32.to_be_bytes()); // creation_time
        c.extend_from_slice(&0u32.to_be_bytes()); // modification_time
        c.extend_from_slice(&self.timescale.to_be_bytes());
        c.extend_from_slice(&duration.to_be_bytes());
        c.extend_from_slice(&0x0001_0000u32.to_be_bytes()); // rate 1.0
        c.extend_from_slice(&0x0100u16.to_be_bytes()); // volume 1.0
        c.extend_from_slice(&[0u8; 10]); // reserved
        c.extend_from_slice(&IDENTITY_MATRIX);
        c.extend_from_slice(&[0u8; 24]); // pre_defined
        c.extend_from_slice(&2u32.to_be_bytes()); // next_track_ID
        full_box(b"mvhd", 0, 0, &c)
    }

    fn build_trak(&self, duration: u32, base_offset: u64, use_co64: bool) -> Vec<u8> {
        let tkhd = self.build_tkhd(duration);
        let mdia = self.build_mdia(duration, base_offset, use_co64);
        mp4_box(b"trak", &[&tkhd, &mdia])
    }

    fn build_tkhd(&self, duration: u32) -> Vec<u8> {
        let mut c = Vec::with_capacity(80);
        c.extend_from_slice(&0u32.to_be_bytes()); // creation_time
        c.extend_from_slice(&0u32.to_be_bytes()); // modification_time
        c.extend_from_slice(&1u32.to_be_bytes()); // track_ID
        c.extend_from_slice(&0u32.to_be_bytes()); // reserved
        c.extend_from_slice(&duration.to_be_bytes());
        c.extend_from_slice(&[0u8; 8]); // reserved
        c.extend_from_slice(&0u16.to_be_bytes()); // layer
        c.extend_from_slice(&0u16.to_be_bytes()); // alternate_group
        c.extend_from_slice(&0u16.to_be_bytes()); // volume (0 for video)
        c.extend_from_slice(&0u16.to_be_bytes()); // reserved
        c.extend_from_slice(&IDENTITY_MATRIX);
        c.extend_from_slice(&(self.width << 16).to_be_bytes()); // width 16.16
        c.extend_from_slice(&(self.height << 16).to_be_bytes()); // height 16.16
        full_box(b"tkhd", 0, 3, &c) // flags = track_enabled | track_in_movie
    }

    fn build_mdia(&self, duration: u32, base_offset: u64, use_co64: bool) -> Vec<u8> {
        let mdhd = self.build_mdhd(duration);
        let hdlr = build_hdlr();
        let minf = self.build_minf(base_offset, use_co64);
        mp4_box(b"mdia", &[&mdhd, &hdlr, &minf])
    }

    fn build_mdhd(&self, duration: u32) -> Vec<u8> {
        let mut c = Vec::with_capacity(20);
        c.extend_from_slice(&0u32.to_be_bytes()); // creation_time
        c.extend_from_slice(&0u32.to_be_bytes()); // modification_time
        c.extend_from_slice(&self.timescale.to_be_bytes());
        c.extend_from_slice(&duration.to_be_bytes());
        c.extend_from_slice(&0x55C4u16.to_be_bytes()); // language "und"
        c.extend_from_slice(&0u16.to_be_bytes()); // pre_defined
        full_box(b"mdhd", 0, 0, &c)
    }

    fn build_minf(&self, base_offset: u64, use_co64: bool) -> Vec<u8> {
        let vmhd = build_vmhd();
        let dinf = build_dinf();
        let stbl = self.build_stbl(base_offset, use_co64);
        mp4_box(b"minf", &[&vmhd, &dinf, &stbl])
    }

    fn build_stbl(&self, base_offset: u64, use_co64: bool) -> Vec<u8> {
        let stsd = self.build_stsd();
        let stts = self.build_stts();
        let stss = self.build_stss();
        let stsz = self.build_stsz();
        let stsc = build_stsc();
        let chunk_offsets = self.build_chunk_offsets(base_offset, use_co64);

        let mut children: Vec<&[u8]> = vec![&stsd, &stts, &stss, &stsz, &stsc, &chunk_offsets];

        let ctts;
        if self.has_b_frames {
            ctts = self.build_ctts();
            children.push(&ctts);
        }

        mp4_box(b"stbl", &children)
    }

    fn build_stsd(&self) -> Vec<u8> {
        let avcc_box = self.build_avcc();
        let avc1 = self.build_avc1(&avcc_box);
        let mut c = Vec::with_capacity(4 + avc1.len());
        c.extend_from_slice(&1u32.to_be_bytes()); // entry_count
        c.extend_from_slice(&avc1);
        full_box(b"stsd", 0, 0, &c)
    }

    fn build_avc1(&self, avcc_box: &[u8]) -> Vec<u8> {
        let mut c = Vec::with_capacity(78 + avcc_box.len());
        c.extend_from_slice(&[0u8; 6]); // reserved
        c.extend_from_slice(&1u16.to_be_bytes()); // data_reference_index
        c.extend_from_slice(&[0u8; 2]); // pre_defined
        c.extend_from_slice(&[0u8; 2]); // reserved
        c.extend_from_slice(&[0u8; 12]); // pre_defined
        c.extend_from_slice(&(self.width as u16).to_be_bytes());
        c.extend_from_slice(&(self.height as u16).to_be_bytes());
        c.extend_from_slice(&0x0048_0000u32.to_be_bytes()); // horiz 72 dpi
        c.extend_from_slice(&0x0048_0000u32.to_be_bytes()); // vert 72 dpi
        c.extend_from_slice(&0u32.to_be_bytes()); // reserved
        c.extend_from_slice(&1u16.to_be_bytes()); // frame_count
        c.extend_from_slice(&[0u8; 32]); // compressorname
        c.extend_from_slice(&0x0018u16.to_be_bytes()); // depth
        c.extend_from_slice(&0xFFFFu16.to_be_bytes()); // pre_defined = -1
        c.extend_from_slice(avcc_box);
        mp4_box(b"avc1", &[&c])
    }

    fn build_avcc(&self) -> Vec<u8> {
        let sps = &self.sps;
        let pps = &self.pps;
        let mut c = Vec::with_capacity(11 + sps.len() + pps.len());
        c.push(1); // configurationVersion
        c.push(sps[1]); // AVCProfileIndication
        c.push(sps[2]); // profile_compatibility
        c.push(sps[3]); // AVCLevelIndication
        c.push(0xFF); // lengthSizeMinusOne = 3
        c.push(0xE1); // numOfSPS = 1
        c.extend_from_slice(&(sps.len() as u16).to_be_bytes());
        c.extend_from_slice(sps);
        c.push(1); // numOfPPS
        c.extend_from_slice(&(pps.len() as u16).to_be_bytes());
        c.extend_from_slice(pps);
        mp4_box(b"avcC", &[&c])
    }

    fn build_stts(&self) -> Vec<u8> {
        let mut entries: Vec<(u32, u32)> = Vec::new();
        for i in 0..self.samples.len() {
            let delta = if i + 1 < self.samples.len() {
                (self.samples[i + 1].dts - self.samples[i].dts) as u32
            } else if let Some(last) = entries.last() {
                last.1
            } else {
                1
            };
            if let Some(last) = entries.last_mut() {
                if last.1 == delta {
                    last.0 += 1;
                    continue;
                }
            }
            entries.push((1, delta));
        }
        let mut c = Vec::with_capacity(4 + entries.len() * 8);
        c.extend_from_slice(&(entries.len() as u32).to_be_bytes());
        for &(count, delta) in &entries {
            c.extend_from_slice(&count.to_be_bytes());
            c.extend_from_slice(&delta.to_be_bytes());
        }
        full_box(b"stts", 0, 0, &c)
    }

    fn build_stss(&self) -> Vec<u8> {
        let keyframes: Vec<u32> = self
            .samples
            .iter()
            .enumerate()
            .filter(|(_, s)| s.is_keyframe)
            .map(|(i, _)| (i + 1) as u32) // 1-based
            .collect();
        let mut c = Vec::with_capacity(4 + keyframes.len() * 4);
        c.extend_from_slice(&(keyframes.len() as u32).to_be_bytes());
        for &k in &keyframes {
            c.extend_from_slice(&k.to_be_bytes());
        }
        full_box(b"stss", 0, 0, &c)
    }

    fn build_stsz(&self) -> Vec<u8> {
        let n = self.samples.len() as u32;
        let mut c = Vec::with_capacity(8 + self.samples.len() * 4);
        c.extend_from_slice(&0u32.to_be_bytes()); // sample_size = 0 (variable)
        c.extend_from_slice(&n.to_be_bytes());
        for s in &self.samples {
            c.extend_from_slice(&s.size.to_be_bytes());
        }
        full_box(b"stsz", 0, 0, &c)
    }

    fn build_chunk_offsets(&self, base_offset: u64, use_co64: bool) -> Vec<u8> {
        if use_co64 {
            self.build_co64(base_offset)
        } else {
            self.build_stco(base_offset)
        }
    }

    fn build_stco(&self, base_offset: u64) -> Vec<u8> {
        let n = self.samples.len() as u32;
        let mut c = Vec::with_capacity(4 + self.samples.len() * 4);
        c.extend_from_slice(&n.to_be_bytes());
        let mut offset = base_offset;
        for s in &self.samples {
            debug_assert!(
                offset <= u32::MAX as u64,
                "Chunk offset {} exceeds u32 — should have used co64",
                offset,
            );
            c.extend_from_slice(&(offset as u32).to_be_bytes());
            offset += s.size as u64;
        }
        full_box(b"stco", 0, 0, &c)
    }

    fn build_co64(&self, base_offset: u64) -> Vec<u8> {
        let n = self.samples.len() as u32;
        let mut c = Vec::with_capacity(4 + self.samples.len() * 8);
        c.extend_from_slice(&n.to_be_bytes());
        let mut offset = base_offset;
        for s in &self.samples {
            c.extend_from_slice(&offset.to_be_bytes());
            offset += s.size as u64;
        }
        full_box(b"co64", 0, 0, &c)
    }

    fn build_ctts(&self) -> Vec<u8> {
        let mut entries: Vec<(u32, i32)> = Vec::new();
        for s in &self.samples {
            if let Some(last) = entries.last_mut() {
                if last.1 == s.cts_offset {
                    last.0 += 1;
                    continue;
                }
            }
            entries.push((1, s.cts_offset));
        }
        let mut c = Vec::with_capacity(4 + entries.len() * 8);
        c.extend_from_slice(&(entries.len() as u32).to_be_bytes());
        for &(count, offset) in &entries {
            c.extend_from_slice(&count.to_be_bytes());
            c.extend_from_slice(&offset.to_be_bytes());
        }
        full_box(b"ctts", 1, 0, &c) // version 1 for signed offsets
    }
}

// ── Standalone box builders (regular MP4) ─────────────────────────

fn build_ftyp() -> Vec<u8> {
    let mut c = Vec::with_capacity(24);
    c.extend_from_slice(b"isom"); // major_brand
    c.extend_from_slice(&512u32.to_be_bytes()); // minor_version
    c.extend_from_slice(b"isom");
    c.extend_from_slice(b"iso2");
    c.extend_from_slice(b"avc1");
    c.extend_from_slice(b"mp41");
    mp4_box(b"ftyp", &[&c])
}

fn build_hdlr() -> Vec<u8> {
    let mut c = Vec::with_capacity(33);
    c.extend_from_slice(&0u32.to_be_bytes()); // pre_defined
    c.extend_from_slice(b"vide"); // handler_type
    c.extend_from_slice(&[0u8; 12]); // reserved
    c.extend_from_slice(b"VideoHandler\0"); // name (null-terminated)
    full_box(b"hdlr", 0, 0, &c)
}

fn build_vmhd() -> Vec<u8> {
    let mut c = Vec::with_capacity(8);
    c.extend_from_slice(&0u16.to_be_bytes()); // graphicsmode
    c.extend_from_slice(&[0u8; 6]); // opcolor
    full_box(b"vmhd", 0, 1, &c) // flags = 1 per spec
}

fn build_dinf() -> Vec<u8> {
    let url = full_box(b"url ", 0, 1, &[]); // self-contained
    let mut dref_c = Vec::with_capacity(4 + url.len());
    dref_c.extend_from_slice(&1u32.to_be_bytes()); // entry_count
    dref_c.extend_from_slice(&url);
    let dref = full_box(b"dref", 0, 0, &dref_c);
    mp4_box(b"dinf", &[&dref])
}

fn build_stsc() -> Vec<u8> {
    let mut c = Vec::with_capacity(16);
    c.extend_from_slice(&1u32.to_be_bytes()); // entry_count
    c.extend_from_slice(&1u32.to_be_bytes()); // first_chunk
    c.extend_from_slice(&1u32.to_be_bytes()); // samples_per_chunk
    c.extend_from_slice(&1u32.to_be_bytes()); // sample_description_index
    full_box(b"stsc", 0, 0, &c)
}

fn build_mdat_header(data_size: u64) -> Vec<u8> {
    let total = 8 + data_size;
    if total <= u32::MAX as u64 {
        let mut h = Vec::with_capacity(8);
        h.extend_from_slice(&(total as u32).to_be_bytes());
        h.extend_from_slice(b"mdat");
        h
    } else {
        let mut h = Vec::with_capacity(16);
        h.extend_from_slice(&1u32.to_be_bytes()); // extended size marker
        h.extend_from_slice(b"mdat");
        h.extend_from_slice(&(16 + data_size).to_be_bytes());
        h
    }
}

fn mdat_header_size(data_size: u64) -> u64 {
    if 8 + data_size > u32::MAX as u64 {
        16
    } else {
        8
    }
}

// ── Fragmented MP4 box builders ───────────────────────────────────

fn build_fmp4_ftyp() -> Vec<u8> {
    let mut c = Vec::with_capacity(24);
    c.extend_from_slice(b"isom"); // major_brand
    c.extend_from_slice(&512u32.to_be_bytes()); // minor_version
    c.extend_from_slice(b"isom");
    c.extend_from_slice(b"iso6");
    c.extend_from_slice(b"msdh");
    c.extend_from_slice(b"msix");
    mp4_box(b"ftyp", &[&c])
}

fn build_fmp4_init_moov(
    width: u32,
    height: u32,
    timescale: u32,
    sps: &[u8],
    pps: &[u8],
) -> Vec<u8> {
    let mvhd = {
        let mut c = Vec::with_capacity(96);
        c.extend_from_slice(&0u32.to_be_bytes()); // creation_time
        c.extend_from_slice(&0u32.to_be_bytes()); // modification_time
        c.extend_from_slice(&timescale.to_be_bytes());
        c.extend_from_slice(&0u32.to_be_bytes()); // duration = 0 (fragmented)
        c.extend_from_slice(&0x0001_0000u32.to_be_bytes()); // rate 1.0
        c.extend_from_slice(&0x0100u16.to_be_bytes()); // volume 1.0
        c.extend_from_slice(&[0u8; 10]); // reserved
        c.extend_from_slice(&IDENTITY_MATRIX);
        c.extend_from_slice(&[0u8; 24]); // pre_defined
        c.extend_from_slice(&2u32.to_be_bytes()); // next_track_ID
        full_box(b"mvhd", 0, 0, &c)
    };

    let tkhd = {
        let mut c = Vec::with_capacity(80);
        c.extend_from_slice(&0u32.to_be_bytes()); // creation_time
        c.extend_from_slice(&0u32.to_be_bytes()); // modification_time
        c.extend_from_slice(&1u32.to_be_bytes()); // track_ID
        c.extend_from_slice(&0u32.to_be_bytes()); // reserved
        c.extend_from_slice(&0u32.to_be_bytes()); // duration = 0
        c.extend_from_slice(&[0u8; 8]); // reserved
        c.extend_from_slice(&0u16.to_be_bytes()); // layer
        c.extend_from_slice(&0u16.to_be_bytes()); // alternate_group
        c.extend_from_slice(&0u16.to_be_bytes()); // volume
        c.extend_from_slice(&0u16.to_be_bytes()); // reserved
        c.extend_from_slice(&IDENTITY_MATRIX);
        c.extend_from_slice(&(width << 16).to_be_bytes());
        c.extend_from_slice(&(height << 16).to_be_bytes());
        full_box(b"tkhd", 0, 3, &c)
    };

    let mdhd = {
        let mut c = Vec::with_capacity(20);
        c.extend_from_slice(&0u32.to_be_bytes()); // creation_time
        c.extend_from_slice(&0u32.to_be_bytes()); // modification_time
        c.extend_from_slice(&timescale.to_be_bytes());
        c.extend_from_slice(&0u32.to_be_bytes()); // duration = 0
        c.extend_from_slice(&0x55C4u16.to_be_bytes()); // language "und"
        c.extend_from_slice(&0u16.to_be_bytes());
        full_box(b"mdhd", 0, 0, &c)
    };

    let hdlr = build_hdlr();

    // avcC box
    let avcc = {
        let mut c = Vec::with_capacity(11 + sps.len() + pps.len());
        c.push(1);
        c.push(sps[1]);
        c.push(sps[2]);
        c.push(sps[3]);
        c.push(0xFF);
        c.push(0xE1);
        c.extend_from_slice(&(sps.len() as u16).to_be_bytes());
        c.extend_from_slice(sps);
        c.push(1);
        c.extend_from_slice(&(pps.len() as u16).to_be_bytes());
        c.extend_from_slice(pps);
        mp4_box(b"avcC", &[&c])
    };

    // avc1 sample entry
    let avc1 = {
        let mut c = Vec::with_capacity(78 + avcc.len());
        c.extend_from_slice(&[0u8; 6]);
        c.extend_from_slice(&1u16.to_be_bytes());
        c.extend_from_slice(&[0u8; 2]);
        c.extend_from_slice(&[0u8; 2]);
        c.extend_from_slice(&[0u8; 12]);
        c.extend_from_slice(&(width as u16).to_be_bytes());
        c.extend_from_slice(&(height as u16).to_be_bytes());
        c.extend_from_slice(&0x0048_0000u32.to_be_bytes());
        c.extend_from_slice(&0x0048_0000u32.to_be_bytes());
        c.extend_from_slice(&0u32.to_be_bytes());
        c.extend_from_slice(&1u16.to_be_bytes());
        c.extend_from_slice(&[0u8; 32]);
        c.extend_from_slice(&0x0018u16.to_be_bytes());
        c.extend_from_slice(&0xFFFFu16.to_be_bytes());
        c.extend_from_slice(&avcc);
        mp4_box(b"avc1", &[&c])
    };

    let stsd = {
        let mut c = Vec::with_capacity(4 + avc1.len());
        c.extend_from_slice(&1u32.to_be_bytes());
        c.extend_from_slice(&avc1);
        full_box(b"stsd", 0, 0, &c)
    };

    // Empty sample tables (required by spec for fmp4 init segment)
    let stts = full_box(b"stts", 0, 0, &0u32.to_be_bytes());
    let stsz = {
        let mut c = Vec::with_capacity(8);
        c.extend_from_slice(&0u32.to_be_bytes()); // sample_size
        c.extend_from_slice(&0u32.to_be_bytes()); // sample_count
        full_box(b"stsz", 0, 0, &c)
    };
    let stsc = full_box(b"stsc", 0, 0, &0u32.to_be_bytes());
    let stco = full_box(b"stco", 0, 0, &0u32.to_be_bytes());

    let stbl = mp4_box(b"stbl", &[&stsd, &stts, &stsz, &stsc, &stco]);

    let vmhd = build_vmhd();
    let dinf = build_dinf();
    let minf = mp4_box(b"minf", &[&vmhd, &dinf, &stbl]);
    let mdia = mp4_box(b"mdia", &[&mdhd, &hdlr, &minf]);
    let trak = mp4_box(b"trak", &[&tkhd, &mdia]);

    // mvex with trex
    let trex = {
        let mut c = Vec::with_capacity(20);
        c.extend_from_slice(&1u32.to_be_bytes()); // track_ID
        c.extend_from_slice(&1u32.to_be_bytes()); // default_sample_description_index
        c.extend_from_slice(&0u32.to_be_bytes()); // default_sample_duration
        c.extend_from_slice(&0u32.to_be_bytes()); // default_sample_size
        c.extend_from_slice(&0u32.to_be_bytes()); // default_sample_flags
        full_box(b"trex", 0, 0, &c)
    };
    let mvex = mp4_box(b"mvex", &[&trex]);

    mp4_box(b"moov", &[&mvhd, &trak, &mvex])
}

/// Flush a fragment (moof + mdat pair) to the writer.
fn flush_fragment(
    writer: &mut BufWriter<File>,
    sequence_number: &mut u32,
    fragment_samples: &mut Vec<SampleInfo>,
    fragment_mdat: &mut Vec<u8>,
    base_decode_time: i64,
) -> io::Result<()> {
    if fragment_samples.is_empty() {
        return Ok(());
    }

    // Build moof with placeholder data_offset, measure size, rebuild with correct offset
    let moof_size = compute_moof_size(fragment_samples.len());
    let mdat_hdr = 8u32; // fragment mdat is always small enough for 4-byte size
    let data_offset = (moof_size + mdat_hdr) as i32;

    let moof = build_moof(
        *sequence_number,
        base_decode_time,
        fragment_samples,
        data_offset,
    );
    debug_assert_eq!(moof.len(), moof_size as usize);

    // mdat box
    let mdat_total = 8 + fragment_mdat.len();
    let mut mdat = Vec::with_capacity(mdat_total);
    mdat.extend_from_slice(&(mdat_total as u32).to_be_bytes());
    mdat.extend_from_slice(b"mdat");
    mdat.extend_from_slice(fragment_mdat);

    writer.write_all(&moof)?;
    writer.write_all(&mdat)?;

    *sequence_number += 1;
    fragment_samples.clear();
    fragment_mdat.clear();

    Ok(())
}

/// Compute moof box size deterministically from sample count.
/// moof = 8 (box hdr) + mfhd(16) + traf(8 + tfhd(16) + tfdt(20) + trun(12 + 16*n))
fn compute_moof_size(n_samples: usize) -> u32 {
    let mfhd = 16u32; // full_box(12) + seq_num(4)
    let tfhd = 16u32; // full_box(12) + track_id(4)
    let tfdt = 20u32; // full_box(12) + base_decode_time(8) [version 1]
    // trun: full_box(12) + sample_count(4) + data_offset(4) + per-sample(16) * n
    let trun = 12 + 4 + 4 + (16 * n_samples as u32);
    let traf = 8 + tfhd + tfdt + trun;
    8 + mfhd + traf
}

fn build_moof(
    seq_num: u32,
    base_decode_time: i64,
    samples: &[SampleInfo],
    data_offset: i32,
) -> Vec<u8> {
    let mfhd = build_mfhd(seq_num);
    let traf = build_traf(base_decode_time, samples, data_offset);
    mp4_box(b"moof", &[&mfhd, &traf])
}

fn build_mfhd(seq_num: u32) -> Vec<u8> {
    full_box(b"mfhd", 0, 0, &seq_num.to_be_bytes())
}

fn build_traf(
    base_decode_time: i64,
    samples: &[SampleInfo],
    data_offset: i32,
) -> Vec<u8> {
    let tfhd = build_tfhd();
    let tfdt = build_tfdt(base_decode_time);
    let trun = build_trun(samples, data_offset);
    mp4_box(b"traf", &[&tfhd, &tfdt, &trun])
}

fn build_tfhd() -> Vec<u8> {
    // flags = 0x020000 (default-base-is-moof)
    let mut c = Vec::with_capacity(4);
    c.extend_from_slice(&1u32.to_be_bytes()); // track_ID
    full_box(b"tfhd", 0, 0x020000, &c)
}

fn build_tfdt(base_decode_time: i64) -> Vec<u8> {
    // version 1: 64-bit decode time
    full_box(b"tfdt", 1, 0, &(base_decode_time as u64).to_be_bytes())
}

fn build_trun(samples: &[SampleInfo], data_offset: i32) -> Vec<u8> {
    // flags: data-offset-present(0x1) | sample-duration-present(0x100)
    //      | sample-size-present(0x200) | sample-flags-present(0x400)
    //      | sample-composition-time-offsets-present(0x800)
    let flags: u32 = 0x1 | 0x100 | 0x200 | 0x400 | 0x800;

    let n = samples.len();
    let mut c = Vec::with_capacity(4 + 4 + n * 16);
    c.extend_from_slice(&(n as u32).to_be_bytes());   // sample_count
    c.extend_from_slice(&data_offset.to_be_bytes());   // data_offset

    for i in 0..n {
        // sample_duration: delta to next sample's DTS
        let duration = if i + 1 < n {
            (samples[i + 1].dts - samples[i].dts) as u32
        } else if i > 0 {
            (samples[i].dts - samples[i - 1].dts) as u32
        } else {
            1
        };
        c.extend_from_slice(&duration.to_be_bytes());

        // sample_size
        c.extend_from_slice(&samples[i].size.to_be_bytes());

        // sample_flags: bit 16 set = non-sync (non-keyframe), bit 25 = depends_on_other
        let sample_flags: u32 = if samples[i].is_keyframe {
            0x02000000 // sample_depends_on = 2 (does not depend on others)
        } else {
            0x01010000 // sample_depends_on = 1 (depends) | sample_is_non_sync = 1
        };
        c.extend_from_slice(&sample_flags.to_be_bytes());

        // sample_composition_time_offset (signed, version 1 trun would be needed
        // but we use version 0 with unsigned — works for non-negative offsets,
        // use version 1 for signed)
        c.extend_from_slice(&samples[i].cts_offset.to_be_bytes());
    }

    // version 1 for signed composition time offsets
    full_box(b"trun", 1, flags, &c)
}

// ── Identity matrix (3x3, 16.16 / 2.30 fixed-point) ───────────────

const IDENTITY_MATRIX: [u8; 36] = {
    let mut m = [0u8; 36];
    // a = 1.0 (16.16) at bytes 0..4
    m[0] = 0x00;
    m[1] = 0x01;
    m[2] = 0x00;
    m[3] = 0x00;
    // d = 1.0 (16.16) at bytes 16..20
    m[16] = 0x00;
    m[17] = 0x01;
    m[18] = 0x00;
    m[19] = 0x00;
    // w = 1.0 (2.30) at bytes 32..36
    m[32] = 0x40;
    m[33] = 0x00;
    m[34] = 0x00;
    m[35] = 0x00;
    m
};

// ── Box construction helpers ───────────────────────────────────────

fn mp4_box(box_type: &[u8; 4], parts: &[&[u8]]) -> Vec<u8> {
    let payload_len: usize = parts.iter().map(|p| p.len()).sum();
    let total = 8 + payload_len;
    let mut buf = Vec::with_capacity(total);
    buf.extend_from_slice(&(total as u32).to_be_bytes());
    buf.extend_from_slice(box_type);
    for part in parts {
        buf.extend_from_slice(part);
    }
    buf
}

fn full_box(box_type: &[u8; 4], version: u8, flags: u32, content: &[u8]) -> Vec<u8> {
    let total = 12 + content.len();
    let mut buf = Vec::with_capacity(total);
    buf.extend_from_slice(&(total as u32).to_be_bytes());
    buf.extend_from_slice(box_type);
    buf.push(version);
    let flag_bytes = flags.to_be_bytes();
    buf.extend_from_slice(&flag_bytes[1..4]);
    buf.extend_from_slice(content);
    buf
}

