# Planning Notes

- User wants `remarks` to be basis for `sync` and `match`; sample `sync:MISS | match:MISMATCH` must be treated as missing/different.
- Main failure likely not database absence; row already exists in `extend_db_ptrj.dbo.payroll_manual_adjustments` but UI filter does not always select it.
- Current local config has `premi_tiket` but lacks `PUPUK` / `TABUR PUPUK`; external premium definitions include `PREMI ANGKUT PUPUK`.
- External backend parser confirms pipe-delimited format and explicit `sync:`/`match:` tokens.
- Do not input all premium rows; only input rows whose explicit remarks status says missing/different.
