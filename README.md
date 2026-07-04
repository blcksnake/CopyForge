# CopyForge

CopyForge is a Python desktop app packaged as a portable Windows executable.

## Versioning Policy

- Use major versions only: `v1`, `v2`, `v3`.
- Do not create patch tags like `v1.0.1`.
- Bump the version only for major changes.

## Download Portable EXE

1. Open the repository Releases page.
2. Download the latest `CopyForge-*-portable-win64.zip` asset.
3. Extract the zip and run `CopyForge.exe`.

## Publish a New Portable EXE

This repo includes a GitHub Actions workflow that builds and publishes the portable EXE automatically when you push a version tag.

1. Commit and push your code changes.
2. Create a major version tag locally:

```powershell
git tag v1
git push origin v1
```

3. GitHub Actions builds the app and uploads `CopyForge-<tag>-portable-win64.zip` to the Release.

## Manual Build (Local)

```powershell
pip install -r requirements.txt
pip install pyinstaller
python build_exe.py
```

Output folder:

- `dist/CopyForge/`