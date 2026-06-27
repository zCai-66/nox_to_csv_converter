# NOX to CSV

A simple converter for Metrohm NOVA `.nox` files to CSV.

Unofficial tool. Not affiliated with Metrohm. Some NOVA files may not contain
extractable numeric tables.

## Quick Start

### Windows

Download `nox-to-csv.exe` from Releases and open it. Choose one `.nox` file or
a folder, then click Convert. Folders are scanned recursively.

## Output

CSV files are written next to their source `.nox` files. `sample.nox` becomes
`sample.csv`.

For existing CSV files, choose `Keep both`, `Replace`, or `Skip`. `Keep both`
creates names such as `sample_2.csv` and `sample_3.csv`.

Typical CSV columns include time, current, potential, and external signal fields
such as `Time (s)`, `WE(1).Current (A)`, and `External(1).External 1 (V)`.

## Limits

- This is a best-effort converter; some NOVA files may not contain extractable
  numeric tables.
- Do not share sensitive `.nox`, `.csv`, or report files in public issues.

## Development

```powershell
python -m compileall -q src tests scripts
python -m unittest discover -s tests
python scripts\build_exe.py
```

The Windows app is built at `nox-to-csv.exe`.
