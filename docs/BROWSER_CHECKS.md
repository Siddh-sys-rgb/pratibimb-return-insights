# Working browser verification

The application was exercised locally on macOS with Python 3.12, through the actual browser UI and fictional demo data. These screenshots show the working product, not generated mockups.

- Corrected return 4 from a wrong-item cluster to the size cluster, preserving the model suggestion and audit reason.
- Saved a monthly comparison with two explicit 30-comment denominators.
- Uploaded the authored eight-row CSV and fitted all 98 comments; pending count returned to zero.

All six apps were checked at a 390×844 viewport; this app's document width was 390px with no horizontal overflow. The temporary viewport was reset after the check. The fresh final app load reported no JavaScript errors. Desktop and mobile captures can show different points in the walkthrough.

Automated regression suite: **50 passing tests**. The README describes test scope and measured coverage. These checks do not establish production scale or complete security coverage.

A later review verified that an explicit correction remains identified even when the model agrees with it after refitting. A new CSV row imported into the migrated workspace was tagged `user-import`; older unmatched legacy records stayed `legacy-unclassified`. Fitting then included all 99 comments. The regression suite independently tests agreement followed by divergence across two fits, and migrated CSV/JSON imports.
