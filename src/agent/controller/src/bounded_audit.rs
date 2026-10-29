//! Cooperative, bounded JSONL rotation. Never replace the permanent lock inode.
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::os::fd::AsRawFd;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::{Path, PathBuf};

pub(crate) struct BoundedAudit {
    path: PathBuf,
    lock_path: PathBuf,
    lock: File,
    limit: u64,
}

fn invalid(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

fn suffixed(path: &Path, suffix: &str) -> PathBuf {
    let mut name = path.as_os_str().to_owned();
    name.push(suffix);
    name.into()
}

fn private_file(path: &Path) -> io::Result<File> {
    let file = OpenOptions::new()
        .create(true)
        .append(true)
        .read(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    check_metadata(&file.metadata()?)?;
    Ok(file)
}

fn check_metadata(meta: &fs::Metadata) -> io::Result<()> {
    if !meta.is_file()
        || meta.nlink() != 1
        || meta.uid() != unsafe { libc::geteuid() }
        || meta.mode() & 0o077 != 0
    {
        return Err(invalid(
            "audit requires an owned private regular single-link file",
        ));
    }
    Ok(())
}

struct Unlock<'a>(&'a File);
impl Drop for Unlock<'_> {
    fn drop(&mut self) {
        unsafe {
            libc::flock(self.0.as_raw_fd(), libc::LOCK_UN);
        }
    }
}

impl BoundedAudit {
    pub(crate) fn open(path: &Path) -> io::Result<Self> {
        Self::with_limit(path, 8 * 1024 * 1024)
    }

    fn with_limit(path: &Path, limit: u64) -> io::Result<Self> {
        let name = path
            .file_name()
            .ok_or_else(|| invalid("audit filename missing"))?;
        let parent = path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."));
        let path = parent.canonicalize()?.join(name);
        let lock_path = suffixed(&path, ".lock");
        let result = Self {
            lock: private_file(&lock_path)?,
            lock_path,
            path,
            limit,
        };
        let file = private_file(&result.path)?;
        if file.metadata()?.len() > limit {
            return Err(invalid(
                "legacy audit exceeds limit; preserve it offline before migration",
            ));
        }
        Ok(result)
    }

    fn backup(&self, n: usize) -> PathBuf {
        suffixed(&self.path, &format!(".{n}"))
    }

    pub(crate) fn append(&mut self, frame: &[u8]) -> io::Result<()> {
        if frame.len() as u64 > self.limit {
            return Err(invalid("audit frame exceeds rotation capacity"));
        }
        if unsafe { libc::flock(self.lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
            return Err(io::Error::last_os_error());
        }
        let _unlock = Unlock(&self.lock);
        let held = self.lock.metadata()?;
        let current = fs::symlink_metadata(&self.lock_path)?;
        check_metadata(&current)?;
        if (held.dev(), held.ino()) != (current.dev(), current.ino()) {
            return Err(invalid("audit lock inode changed"));
        }
        // Validate every managed name before any rename/removal.
        for path in std::iter::once(self.path.clone()).chain((1..=3).map(|n| self.backup(n))) {
            match fs::symlink_metadata(path) {
                Ok(meta) => {
                    check_metadata(&meta)?;
                    if meta.len() > self.limit {
                        return Err(invalid("audit segment exceeds limit"));
                    }
                }
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(error) => return Err(error),
            }
        }
        let mut file = private_file(&self.path)?;
        if file.metadata()?.len() + frame.len() as u64 > self.limit {
            if self.backup(3).exists() {
                fs::remove_file(self.backup(3))?;
            }
            for n in (1..=2).rev() {
                if self.backup(n).exists() {
                    fs::rename(self.backup(n), self.backup(n + 1))?;
                }
            }
            fs::rename(&self.path, self.backup(1))?;
            file = private_file(&self.path)?;
        }
        file.write_all(frame)?;
        file.flush()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::symlink;
    use std::sync::atomic::{AtomicUsize, Ordering};
    static SERIAL: AtomicUsize = AtomicUsize::new(0);
    struct Directory(PathBuf);
    impl Directory {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "o1a-audit-{}-{}",
                std::process::id(),
                SERIAL.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir(&path).unwrap();
            Self(path)
        }
    }
    impl Drop for Directory {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }

    #[test]
    fn rotation_retains_complete_ordered_lines_across_reopened_writers() {
        let dir = Directory::new();
        let path = dir.0.join("audit.jsonl");
        let mut one = BoundedAudit::with_limit(&path, 128).unwrap();
        let mut two = BoundedAudit::with_limit(&path, 128).unwrap();
        for i in 0..100 {
            let frame = format!("{{\"id\":{i},\"value\":\"abcdefgh\"}}\n");
            if i % 2 == 0 {
                one.append(frame.as_bytes()).unwrap();
            } else {
                two.append(frame.as_bytes()).unwrap();
            }
        }
        let mut ids = Vec::new();
        for p in (1..=3)
            .rev()
            .map(|n| one.backup(n))
            .chain(std::iter::once(path))
        {
            let bytes = fs::read(&p).unwrap();
            assert!(bytes.len() <= 128);
            for line in String::from_utf8(bytes).unwrap().lines() {
                ids.push(
                    serde_json::from_str::<serde_json::Value>(line).unwrap()["id"]
                        .as_u64()
                        .unwrap(),
                );
            }
        }
        assert_eq!(*ids.last().unwrap(), 99);
        assert!(ids.windows(2).all(|x| x[1] == x[0] + 1));
        assert_eq!(fs::read_dir(&dir.0).unwrap().count(), 5);
    }

    #[test]
    fn lock_contention_and_replacement_fail_closed() {
        let dir = Directory::new();
        let path = dir.0.join("audit");
        let mut one = BoundedAudit::open(&path).unwrap();
        let two = BoundedAudit::open(&path).unwrap();
        assert_eq!(
            unsafe { libc::flock(two.lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) },
            0
        );
        assert_eq!(
            one.append(b"{}\n").unwrap_err().kind(),
            io::ErrorKind::WouldBlock
        );
        unsafe {
            libc::flock(two.lock.as_raw_fd(), libc::LOCK_UN);
        }
        fs::remove_file(&one.lock_path).unwrap();
        let _replacement = private_file(&one.lock_path).unwrap();
        assert!(one.append(b"{}\n").is_err());
        assert!(fs::read(path).unwrap().is_empty());
    }

    #[test]
    fn links_oversized_legacy_and_bad_backup_are_preserved_on_failure() {
        let dir = Directory::new();
        let target = dir.0.join("user-result");
        fs::write(&target, b"preserve").unwrap();
        let path = dir.0.join("audit");
        symlink(&target, &path).unwrap();
        assert!(BoundedAudit::open(&path).is_err());
        fs::remove_file(&path).unwrap();
        fs::hard_link(&target, &path).unwrap();
        assert!(BoundedAudit::open(&path).is_err());
        fs::remove_file(&path).unwrap();
        let mut audit = BoundedAudit::with_limit(&path, 128).unwrap();
        symlink(&target, audit.backup(3)).unwrap();
        assert!(audit.append(b"{}\n").is_err());
        assert_eq!(fs::read(&target).unwrap(), b"preserve");
        fs::remove_file(audit.backup(3)).unwrap();
        assert!(audit.append(&[b'x'; 129]).is_err());
        fs::write(&path, [b'x'; 129]).unwrap();
        assert!(BoundedAudit::with_limit(&path, 128).is_err());
        assert_eq!(fs::metadata(path).unwrap().len(), 129);
    }
}
