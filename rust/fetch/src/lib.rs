//! Others' sources for a build script: the engine's crates hold only manimgx's code, and fetch
//! what they build from others (x264, NASM, FFmpeg, libopus, mitex's Typst package) at build time,
//! each pinned by the hash of its files.

use std::path::{Path, PathBuf};
use std::process::Command;

use sha2::{Digest, Sha256};

/// The tree of files in the archive at `url` (its one top folder, if it has one), unpacked into
/// the build script's OUT_DIR, in a folder named by `hash`: the SHA-256 of its files, each one's
/// path, length and bytes, by path. It names the files, not the archive, which hosts regenerate:
/// any archive of the same files passes, and a tree once checked is found again by its name.
///
/// The archive is kept in the folder MANIMGX_SOURCES names (an absolute path), if it names one:
/// read from there, and downloaded there first unless it is there. So a folder that holds the
/// archives builds offline, and a build into an empty one gathers what it is built from, as a
/// release does for its complete source. A build script fetches the same archives on every
/// target (what it compiles of them may differ), so one build gathers what every build reads.
pub fn tree(url: &str, hash: &str) -> PathBuf {
    println!("cargo:rerun-if-env-changed=MANIMGX_SOURCES");
    let out = PathBuf::from(std::env::var_os("OUT_DIR").expect("a build script's OUT_DIR"));
    let tree = out.join(hash);
    if tree.exists() {
        return tree;
    }
    let folder = std::env::var_os("MANIMGX_SOURCES").map_or(out.clone(), PathBuf::from);
    let archive = folder.join(url.rsplit('/').next().unwrap());
    if !archive.exists() {
        // under another name until it is whole, so a build sharing the folder never reads half
        let part = archive.with_extension(format!("{}.part", std::process::id()));
        std::fs::create_dir_all(&folder).unwrap();
        run(Command::new("curl").args(["-fsSL", "--retry", "3", "-o"]).arg(&part).arg(url));
        std::fs::rename(&part, &archive).unwrap();
    }
    let unpacked = out.join(format!("{hash}.unpacked"));
    let _ = std::fs::remove_dir_all(&unpacked);
    std::fs::create_dir_all(&unpacked).unwrap();
    // the archive named from its own folder: GNU tar reads `C:` in a path as a remote host
    run(Command::new("tar").current_dir(&folder).arg("-xf").arg(archive.file_name().unwrap()).arg("-C").arg(&unpacked));
    let entries: Vec<_> = std::fs::read_dir(&unpacked).unwrap().map(|entry| entry.unwrap().path()).collect();
    let root = match &entries[..] {
        [folder] if folder.is_dir() => folder.clone(),
        _ => unpacked.clone(),
    };
    let found = files_hash(&root);
    assert!(found == hash, "{url}: its files hash to {found}, not {hash}");
    std::fs::rename(&root, &tree).unwrap();
    let _ = std::fs::remove_dir_all(&unpacked);
    tree
}

/// The SHA-256 of a tree's files: each one's path (`/` between its parts), length and bytes, by
/// path.
pub fn files_hash(root: &Path) -> String {
    let mut files = Vec::new();
    let mut folders = vec![PathBuf::new()];
    while let Some(folder) = folders.pop() {
        for entry in std::fs::read_dir(root.join(&folder)).unwrap() {
            let path = folder.join(entry.unwrap().file_name());
            if root.join(&path).is_dir() { folders.push(path) } else { files.push(path) }
        }
    }
    let key = |path: &PathBuf| path.iter().map(|part| part.to_string_lossy()).collect::<Vec<_>>().join("/");
    files.sort_by_cached_key(key);
    let mut sha = Sha256::new();
    for path in &files {
        let bytes = std::fs::read(root.join(path)).unwrap();
        sha.update(key(path).as_bytes());
        sha.update([0]);
        sha.update((bytes.len() as u64).to_le_bytes());
        sha.update(&bytes);
    }
    sha.finalize().iter().map(|byte| format!("{byte:02x}")).collect()
}

fn run(command: &mut Command) {
    let status = command.status().unwrap_or_else(|e| panic!("{command:?}: {e}"));
    assert!(status.success(), "{command:?} failed");
}
