//! MANIMGX_SOURCES, a folder of archives: a build into an empty one downloads each archive into
//! it, and a build from a full one reads them there, with nothing to download.

use std::process::Command;

#[test]
fn an_empty_folder_gathers_the_archives_and_a_full_one_builds_offline() {
    let work = std::env::temp_dir().join(format!("fetch-folder-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&work);
    // an archive of a small tree, at a file URL
    let served = work.join("served");
    std::fs::create_dir_all(served.join("tree/sub")).unwrap();
    std::fs::write(served.join("tree/a.txt"), "a").unwrap();
    std::fs::write(served.join("tree/sub/b.txt"), "b").unwrap();
    let tar = Command::new("tar").current_dir(&served).args(["-czf", "tree.tar.gz", "tree"]).status().unwrap();
    assert!(tar.success());
    let hash = fetch::files_hash(&served.join("tree"));
    let path = served.join("tree.tar.gz").display().to_string().replace('\\', "/");
    let url = format!("file:///{}", path.trim_start_matches('/'));
    let sources = work.join("sources");

    // SAFETY: the only test in its binary, so no other thread reads the environment
    unsafe {
        std::env::set_var("OUT_DIR", work.join("first"));
        std::env::set_var("MANIMGX_SOURCES", &sources);
    }
    let tree = fetch::tree(&url, &hash);
    assert_eq!(std::fs::read_to_string(tree.join("sub/b.txt")).unwrap(), "b");
    let gathered: Vec<_> = std::fs::read_dir(&sources).unwrap().map(|entry| entry.unwrap().file_name()).collect();
    assert_eq!(gathered, ["tree.tar.gz"], "the folder holds the archive, whole, and nothing else");

    // the archive no longer at its URL: another build reads it from the folder
    std::fs::remove_file(served.join("tree.tar.gz")).unwrap();
    // SAFETY: as above
    unsafe { std::env::set_var("OUT_DIR", work.join("second")) }
    let tree = fetch::tree(&url, &hash);
    assert_eq!(std::fs::read_to_string(tree.join("a.txt")).unwrap(), "a");
    std::fs::remove_dir_all(&work).unwrap();
}
