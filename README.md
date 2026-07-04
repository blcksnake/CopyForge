# CopyForge

CopyForge is a Windows desktop file transfer tool for copying large file sets with verification, retries, and clear transfer visibility.

It is designed for reliable copy jobs to local disks, external drives, and network paths.

## What CopyForge does

- Copies files and folders with a modern queue-based interface
- Runs concurrent transfers with 1 to 8 workers
- Verifies file integrity with hash checks
- Supports BLAKE3, SHA256, SHA512, SHA1, and MD5
- Handles long Windows paths and UNC network paths
- Provides pause, resume, skip, and stop controls
- Retries failed files automatically
- Exports transfer reports to HTML or CSV

## Main workflow

1. Add a source (files or folder)
2. Choose destination folder
3. Adjust options in the Options tab
4. Let CopyForge run the queue
5. Review results and export a report if needed

## Transfer options

- Include sub-folders
- Verify files after transfer
- Overwrite mode:
	- overwrite_all
	- overwrite_newer
	- skip_existing
- Hash algorithm
- Max retries per file
- Buffer size in MB
- Parallel worker count

## Run from source

Requirements:

- Windows
- Python 3.10 or newer

Install and run:

```powershell
pip install -r requirements.txt
python main.py
```

## Build portable EXE locally

```powershell
pip install -r requirements.txt
pip install pyinstaller
python build_exe.py
```

Portable output:

- dist/CopyForge/CopyForge.exe

## Download portable EXE

1. Open the repository Releases page
2. Download the latest CopyForge-vX-portable-win64.zip asset
3. Extract and run CopyForge.exe

## Release process

This repository uses GitHub Actions to build and publish the portable EXE from tags.

Create a release tag:

```powershell
git tag v1
git push origin v1
```

The workflow builds on Windows and publishes:

- CopyForge-v1-portable-win64.zip

## Versioning policy

- Use major tags only: v1, v2, v3
- Increase the major tag only for major changes
- Do not use patch tags such as v1.0.1