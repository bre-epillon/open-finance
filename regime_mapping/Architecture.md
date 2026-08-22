Project philosophy

Inherited verbatim from open-finance. The same rules apply here.

- boring code
- explicit code
- feature-first
- no magic

Rules

No file >200 lines.
No custom hook unless used twice.
No Context until three components need it.
No optimization before profiling.
No abstractions "for future use."
State lives as close as possible to where it is used.

Two additions specific to this project

The maths lives in core/ and takes pandas objects in and out. It never talks
to a database. That is what makes it unit-testable, and untested quantitative
code produces plausible wrong numbers rather than errors -- see BACKLOG.md in
open-finance for three worked examples of exactly that.

api/, worker/ and mcp/ all import core/. None of them reimplements a
calculation. open-finance had two copies of its backfill logic that drifted to
different staleness thresholds before anyone noticed; one copy, three callers.

Where the 200-line cap applies

App code: core/, api/, worker/, mcp_server/, frontend/src/. All of it is under
the cap as built.

Not app code, and over it on purpose: tests/ and scripts/. A test file is read
top to bottom as a spec for one module, and splitting one to hit a line count
makes it harder to read, not easier. Same for a diagnostic script that has to
be runnable as a single file on a machine that may not have the package
installed. frontend/src/App.css is one line over and is left alone; it is the
token sheet, and there is no second file it wants to be.
