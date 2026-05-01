# Monthly Allowance DOM Patterns

Reference snapshots:

- `Snapshot_DOM/Blok_based_monthly_allowance/monhtly_allowance_bock_based.html`
- `Snapshot_DOM/Vehicle_based_monthly_allowance/monhtly_allowance_bock_based.html`

These snapshots are for PlantwareP3 `Human Resource > Payroll > Monthly Allowance and Deduction Details`.
They document how the same monthly allowance form changes after selecting an AD Code.

## Common Form Controls

The common top-level controls are the same for block-based and vehicle-based allowance rows:

| Purpose | Selector | Notes |
| --- | --- | --- |
| Employee | `#MainContent_ddlEmployee` | Hidden `<select>` with a generated adjacent `input.ui-autocomplete-input`. |
| Charge To | `#MainContent_ddlChargeTo` | Visible location `<select>`. Selecting it can post back. |
| AD Code / Task Code | `#MainContent_ddlTaskCode` | Hidden `<select>` with a generated adjacent autocomplete input. Selecting it posts back and determines the dimensional fields. |
| Multi-dimension container | `#MainContent_MultiDimAcc_tbAccount` | Inspect this after AD Code selection, not before. |
| Amount | `#MainContent_txtAmount` | Common amount input. |
| Add | `#MainContent_btnAdd` | Adds the current detail row. |

For hidden combobox selects, the actual typed field is the adjacent generated input, for example:

```css
#MainContent_ddlEmployee + input.ui-autocomplete-input
#MainContent_ddlTaskCode + input.ui-autocomplete-input
#MainContent_MultiDimAcc_ddlSubBlk + input.ui-autocomplete-input
```

Do not detect mode by searching the whole document for text like `Vehicle` or `SubBlock`; those words also appear in the left navigation. Only inspect controls under `#MainContent_MultiDimAcc_tbAccount`.

## Block-Based Pattern

Block-based rows are identified by the presence of the Sub Block control after AD Code postback.

Strong indicators:

- `#MainContent_MultiDimAcc_trSubBlkCode`
- `#MainContent_MultiDimAcc_ddlSubBlk`
- `#MainContent_MultiDimAcc_reqValSubBlk`

Observed block-based dimensional controls:

| Purpose | Label in snapshot | Selector | Input method |
| --- | --- | --- | --- |
| Block / division code | `Division Code` | `#MainContent_MultiDimAcc_ddlBlock` | Hidden select + adjacent autocomplete input. |
| Sub block / field no | `Field No Code` | `#MainContent_MultiDimAcc_ddlSubBlk` | Hidden select + adjacent autocomplete input. |
| Expense code | `Expense Code` | `#MainContent_MultiDimAcc_ddlExpCode` | Hidden select + adjacent autocomplete input. |

Observed selected AD Code in the block snapshot:

- `#MainContent_ddlTaskCode` selected value: `AL3PM2201AB1`
- Text: `(AL) TUNJANGAN PREMI ((PM) HARVESTING LABOUR - HARVESTING)`

Observed selected expense code:

- `#MainContent_MultiDimAcc_ddlExpCode` selected value: `L`
- Text: `L (LABOUR)`

Recommended input order for block-based rows:

1. Select employee.
2. Select `Charge To`.
3. Select AD Code / Task Code.
4. Wait for `#MainContent_MultiDimAcc_ddlSubBlk` or `#MainContent_MultiDimAcc_trSubBlkCode`.
5. Select block / division code.
6. Select sub block / field no code.
7. Select expense code.
8. Fill amount.
9. Click Add.

## Vehicle-Based Pattern

Vehicle-based rows are identified by the presence of the Vehicle controls after AD Code postback.

Strong indicators:

- `#MainContent_MultiDimAcc_trVehCode`
- `#MainContent_MultiDimAcc_ddlVehCode`
- `#MainContent_MultiDimAcc_trVehExpCode`
- `#MainContent_MultiDimAcc_ddlVehExpCode`

Observed vehicle-based dimensional controls:

| Purpose | Label in snapshot | Selector | Input method |
| --- | --- | --- | --- |
| Vehicle code | `Vehicle Code` | `#MainContent_MultiDimAcc_ddlVehCode` | Hidden select + adjacent autocomplete input. |
| Vehicle expense code | `Vehicle Expense Code` | `#MainContent_MultiDimAcc_ddlVehExpCode` | Hidden select + adjacent autocomplete input. |

Observed selected AD Code in the vehicle snapshot:

- `#MainContent_ddlTaskCode` selected value: `AL3PT2304AB1`
- Text: `(AL) TUNJANGAN PREMI ((PM) DRIVER - ANGKUT TBK)`

Observed vehicle code options include:

- `BE003 (V35 (EXCAVATOR HITACHI PC 200))`
- `BE004 (V36 (BECHOLOADER CASE 2))`
- `BE007 (V80 (EXCAVATOR HITACHI ZX200-5G))`

Observed vehicle expense code options include:

- `11 (DRIVER WAGES)`
- `12 (DRIVER OVERTIME)`
- `13 (ATTENDANT WAGES)`
- `21 (FUEL)`
- `31 (SERVICING)`
- `33 (REPAIR & MAINTENANCE)`
- `70 (VEHICLE MATERIAL)`

Recommended input order for vehicle-based rows:

1. Select employee.
2. Select `Charge To`.
3. Select AD Code / Task Code.
4. Wait for `#MainContent_MultiDimAcc_ddlVehCode` or `#MainContent_MultiDimAcc_trVehCode`.
5. Select vehicle code.
6. Select vehicle expense code.
7. Fill amount.
8. Click Add.

## Continuous Detail Input

Grouped premium data can contain multiple transaction detail rows for one employee, across one or more premium names/ADCodes. Treat the employee as the concurrent work unit:

```text
employee + estate/charge-to
```

Input rule for one employee group:

1. For the first premium row owned by the employee, select Employee and Charge To.
2. Select AD Code / Task Code for the current premium row.
3. Fill the block-based or vehicle-based detail controls.
4. Fill Amount and click Add.
5. For the next row with the same employee+estate key, do not click New and do not reselect Employee. Select/fill ADCode as needed, then fill the next dimensional detail, Amount, and Add.
6. When the employee+estate key changes, click New and select the new Employee/Charge To before entering that employee's premiums.

Within an employee, repeated rows with the same premium header still have this narrower header key:

```text
employee + estate/charge-to + adjustment_name + ADCode/TaskDesc
```

Detail rule for this narrower group:

1. Keep Employee and Charge To from the employee group.
2. Fill the block-based or vehicle-based detail controls.
3. Fill Amount and click Add.
4. Select ADCode again only if Plantware cleared or changed it after Add.

Tab assignment must preserve the employee group. If a run uses 5 concurrent tabs, divide the filtered employee list into 5 tab queues. A tab must input all premiums and all transaction details owned by its current employee before moving to the next employee assigned to that tab. Do not distribute one employee's premium rows across multiple browser tabs.

## Runner Implementation Notes

- Treat mode detection as a post-AD-Code step. The multi-dimensional rows are determined by the selected AD Code and ASP.NET postback.
- Never map autocomplete fields by global position such as `input.ui-autocomplete-input.nth(0)` or `.nth(1)`. Plantware generates adjacent autocomplete inputs for hidden `<select>` controls, and the order can change after postbacks or between block/vehicle layouts.
- Map each value to its owning hidden select, then type into that select's adjacent autocomplete input:

  | Value | Hidden select | Autocomplete input |
  | --- | --- | --- |
  | Employee code/name | `#MainContent_ddlEmployee` | `#MainContent_ddlEmployee + input.ui-autocomplete-input` |
  | AD Code / Task description | `#MainContent_ddlTaskCode` | `#MainContent_ddlTaskCode + input.ui-autocomplete-input` |
  | Block / division | `#MainContent_MultiDimAcc_ddlBlock` | `#MainContent_MultiDimAcc_ddlBlock + input.ui-autocomplete-input` |
  | Sub block / field no | `#MainContent_MultiDimAcc_ddlSubBlk` | `#MainContent_MultiDimAcc_ddlSubBlk + input.ui-autocomplete-input` |
  | Block expense | `#MainContent_MultiDimAcc_ddlExpCode` | `#MainContent_MultiDimAcc_ddlExpCode + input.ui-autocomplete-input` |
  | Vehicle code | `#MainContent_MultiDimAcc_ddlVehCode` | `#MainContent_MultiDimAcc_ddlVehCode + input.ui-autocomplete-input` |
  | Vehicle expense | `#MainContent_MultiDimAcc_ddlVehExpCode` | `#MainContent_MultiDimAcc_ddlVehExpCode + input.ui-autocomplete-input` |

- For repeated detail rows under the same employee group, do not click New. Reuse Employee and Charge To if they are still correct, then ensure ADCode is selected/filled for the current premium because Plantware can clear the ADCode field after Add. Fill only the dimensional detail and amount, while still preserving the same select-to-input mapping above.
- For premium detail continuation rows, skip Employee/Charge To re-entry but do not blindly skip ADCode. If ADCode is empty after Add, select it again using `#MainContent_ddlTaskCode + input.ui-autocomplete-input`, never a global autocomplete index.
- Prefer exact selectors for dimensional controls instead of relying on autocomplete index positions. The number and order of generated `input.ui-autocomplete-input` fields differs between block-based and vehicle-based forms.
- The previous generic pattern of using the last enabled `.CBOBox.ui-autocomplete-input` as an expense field is not enough for these monthly allowance forms. Block-based forms have block, sub block, and expense controls. Vehicle-based forms have vehicle and vehicle expense controls.
- If neither block nor vehicle indicators are present after AD Code selection, handle it as an unsupported or generic dimensional layout and emit a clear diagnostic event with the available `MainContent_MultiDimAcc_*` selectors.

## Grouped Premium Endpoint Mapping

For premium auto key-in, fetch manual adjustments with:

```text
view=grouped&adjustment_type=PREMI&metadata_only=true
```

Use `employee.premium_transactions[]` as the row source. Each transaction is one key-in detail row; do not key in the aggregate `premiums[].amount` or flat row total.

Endpoint field mapping used by the refactor:

| Endpoint field | Local field | Purpose |
| --- | --- | --- |
| `estate` / `estate_code` | `estate` and `division_code` | Plantware top-level Charge To, for example `AB1` or `P1B`. |
| transaction `division_code` | `divisioncode` | Block division code derived from gang, two characters separated by a space, for example `G 1` from `G1H` or `C 2` from `C2H`. |
| `detail_type: "blok"` with `subblok` | block-based monthly allowance | Fill `ddlBlock`, `ddlSubBlk`, then `ddlExpCode`. |
| `detail_type: "kendaraan"` with vehicle fields | vehicle-based monthly allowance | Fill `ddlVehCode`, then `ddlVehExpCode`. |
| `ad_code` / `ad_code_desc` | AD Code / task description | Prefer `ad_code_desc` / `task_desc` display text like `(AL) ...` for Plantware ADCode autocomplete. Keep raw `ad_code` / `task_code` only for trace. |

If `divisioncode` is missing, derive it from the first two non-space characters of `gang_code` with a space between them. For real premium detail rows, do not fallback to typing generic `premi` when `ad_code` is absent; fail clearly so the endpoint data can be corrected.

### Whole-Employee PREMI Fetching

When the goal is “all PREMI owned by one employee”, do not fetch all division data and filter locally. Send the employee and gang filters directly to the grouped endpoint:

```text
period_month=4&period_year=2026&division_code=AB1&gang_code=G1H&emp_code=G0597&adjustment_type=PREMI&metadata_only=true&view=grouped
```

This matters because endpoint enrichment can differ when scoped to the employee/gang. In the G0597/G1H April 2026 test, a division-wide fetch followed by local filtering produced `PREMI TBS` with invalid fallback ADCode `premi tbs`, but the direct employee/gang query returned the correct Plantware ADCode display text:

```text
(AL) TUNJANGAN PREMI ((PM) HARVESTING LABOUR - HARVESTING)
```

For G0597/G1H April 2026, the direct grouped query returned 8 detail transactions across all metadata-backed PREMI rows:

| Premium | Detail count |
| --- | ---: |
| `PREMI PRUNING` | 4 |
| `PREMI RAKING` | 3 |
| `PREMI TBS` | 1 |

The runner must preserve group order. Use `Add` repeatedly for detail rows in the same employee+premium+ADCode group; click `New` only when moving to a different group.

## Adjustment Name Options Endpoint

The desktop UI should populate manual adjustment names from:

```text
/payroll/manual-adjustment/adjustment-name-options/by-api-key
```

Use this endpoint instead of deriving manual names from free text or from the old `automation-options` endpoint. Query examples:

```text
adjustment_type=PREMI&division_code=AB1&limit=200
adjustment_type=POTONGAN_KOTOR,POTONGAN_BERSIH&division_code=AB1&limit=200
```

The UI uses `adjustment_names_by_type`/`by_type`/`data` from the response to fill the editable `Adjustment Name` dropdown. The same options are also used to enrich fetched manual records with `ad_code`, `task_code`, and `task_desc` before sending records to the runner.
