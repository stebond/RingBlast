# How to publish a new RingBlast release

Maintainer notes (private reminder). The program checks GitHub for the latest *release*; a release is
created automatically when a tag `vX.Y.Z` is pushed. Do the steps in this order.

## 1. Prepare the code
1. Finish the changes and run the tests: `python -m pytest -q` (all must pass).
2. Choose the new number `X.Y.Z` (bug fix: 0.1.3 -> 0.1.4; new feature: 0.1.3 -> 0.2.0).
3. Edit **both** files, with the same number and without the `v`:
   - `src/ringblast/about.py`: `VERSION = "X.Y.Z"`
   - `pyproject.toml`: `version = "X.Y.Z"`
4. If the database tables changed, say so in the commit message (it becomes the release notes).

## 2. Commit and push (GitHub Desktop)
1. Changes tab: tick the files, write a summary such as `Release X.Y.Z: <what changed>`, **Commit to main**.
2. **Push origin**.

## 3. Create and push the tag
1. History tab: right-click the commit just made (the top one) -> **Create Tag...**
2. Name: `vX.Y.Z` (lowercase `v` + the same number as in the code). Confirm.
3. **Push origin** again: it sends the tag.

The tag must sit on the commit that contains the new version number. If the number in the code is older
than the tag, the program will keep offering an update to itself.

## 4. Check the build
1. github.com/stebond/RingBlast -> **Actions** -> *Build portable Windows program* (about 3 minutes).
2. Green: the release `vX.Y.Z` appears under **Releases** with `RingBlast-portable-....zip` attached.
3. Red: open the run, read the failing step, fix, and repeat from step 1 with a new number
   (or delete the tag on GitHub and on the computer, and create it again on the fixed commit).
4. Optional: edit the release text on GitHub (what is new). Users see its first lines in the update window.

## 5. Test the result
1. Download the zip from the release, unzip it in a new folder, start `RingBlast.exe`
   (Windows SmartScreen: *More info -> Run anyway*).
2. Help -> **Check for updates...** must say that this is the latest version.
3. An older copy of the program must offer the new version at start-up (at most once a day) or from the menu.

## Notes
- Users who skipped a version are still told about a newer one; the manual check ignores the skip.
- The automatic check can be disabled in the Settings tab, or with the variable `RINGBLAST_NO_UPDATE_CHECK=1`.
- The workflow needs `permissions: contents: write` (already set in `.github/workflows/build-portable.yml`).
- Never move or re-use a published tag for different code: delete the release and the tag first, or use a new number.
- To build the same zip by hand on Windows: `launcher\\build_exe.bat`.
- Not done yet (possible future work): code signing of the exe (removes the SmartScreen warning) and an
  online update of the database tables (CSV) without a new program release.

## Platforms

The workflow builds three portable packages on every `vX.Y.Z` tag and attaches them to the release:
`RingBlast-portable-<version>-windows.zip`, `-linux.tar.gz` and `-macos.tar.gz` (Apple Silicon).
The macOS app is not signed: on first start use right-click > Open (or `xattr -cr RingBlast.app`).
