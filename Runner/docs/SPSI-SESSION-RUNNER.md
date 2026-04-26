# SPSI Session-Based Runner - Documentation

## Overview

The `SpsiSessionRunner` is a Playwright-based browser automation runner that reuses authenticated browser sessions for faster execution. It stores session state in the filesystem for persistence across multiple runs.

## Usage

```bash
node dist/runner/session-based-runner.js --headless --session=shared-session
```

### Command Line Options

| Flag | Description | Default |
|------|-------------|---------|
| `--headless` | Run browser in headless mode | false |
| `--id=<name>` | Set instance ID | `spsi-session-<timestamp>` |
| `--session=<name>` | Set session ID (filename) | `shared-session` |
| `--no-reuse` | Disable session reuse | false |

## Session Reuse Optimization

### Performance Comparison

| Mode | Duration | Improvement |
|------|----------|-------------|
| Fresh Login | ~26,000ms | baseline |
| Session Reuse | ~1,500ms | **~17x faster** |

### How It Works

1. **Session Storage**: After successful login, session state (cookies, localStorage) is saved to `Runner/spsi_input/sessions/<session-id>.json`

2. **Session Validation**: On next run, the saved session is validated by:
   - Checking session age (max 4 hours)
   - Creating a test context with the saved storage state
   - Navigating to the list page to verify authentication
   - Checking for the `#MainContent_btnNew` element

3. **Session Reuse**: If valid, the saved session is reused - skipping login and location selection steps

### Key Implementation Details

```typescript
// PASS as object, NOT file path - this is critical for cookie loading
const newContext = await this.browser!.newContext({
  storageState: sessionData.storageState,  // Object, not string path
  viewport: { width: 1280, height: 720 }
});
```

### Session File Structure

```json
{
  "sessionId": "shared-session",
  "savedAt": "2026-04-25T04:00:43.403Z",
  "storageState": {
    "cookies": [
      {
        "name": "ASP.NET_SessionId",
        "value": "3yfp5znjckrwv3b...",
        "domain": "plantwarep3",
        "path": "/",
        "expires": -1,
        "httpOnly": true,
        "secure": false,
        "sameSite": "Lax"
      },
      {
        "name": "CK_USERCOLOR",
        "value": "1",
        "domain": "plantwarep3",
        "path": "/",
        "expires": 1779681245.397136,
        "httpOnly": false,
        "secure": false,
        "sameSite": "Lax"
      }
    ],
    "origins": []
  }
}
```

## Session Directory

```
D:\Gawean Rebinmas\Browser_Auto_key_in new\
└── Runner\
    └── spsi_input\
        └── sessions\
            ├── shared-session.json  (shared across runs)
            ├── session-1777051740505.json
            └── session-1777052212629.json
```

Path configured in runner:
```typescript
sessionDir: path.resolve(process.cwd(), "../../../Runner/spsi_input/sessions")
```

## Session Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    Session Reuse Flow                         │
├─────────────────────────────────────────────────────────────┤
│  1. Run with --session=shared-session                        │
│  2. Check if shared-session.json exists                      │
│  3. Validate: check age < 4h, cookies exist                  │
│  4. Create test context with storageState object             │
│  5. Navigate to list page                                    │
│  6. If login redirect → full login, save new session         │
│  7. If #MainContent_btnNew found → reuse session              │
│  8. Run Click New + Verify Data Entry                        │
└─────────────────────────────────────────────────────────────┘
```

## Known Issues & Fixes

### Issue 1: Cookies Not Loading When Using File Path

**Problem**: When passing `storageState: sessionPath` (file path string), cookies were not loaded into the context.

**Debug Output** (Before Fix):
```
[Session] Context has 0 cookies:
[Session] URL after load: http://plantwarep3:8001/frmLogin.aspx
```

**Solution**: Pass `sessionData.storageState` (the object) directly instead of the file path.

### Issue 2: Wrong Session Directory Path

**Problem**: Session was being saved to `template/apps/Runner/spsi_input/sessions/` instead of `Runner/spsi_input/sessions/`

**Solution**: Corrected the relative path from `../Runner/` to `../../../Runner/spsi_input/sessions`

### Issue 3: Session Timeout Too Short

**Problem**: Sessions older than 30 minutes were rejected.

**Solution**: Extended timeout to 240 minutes (4 hours) to match ASP.NET session behavior.

## Configuration

```typescript
const CONFIG = {
  baseUrl: "http://plantwarep3:8001",
  entryUrl: "http://plantwarep3:8001/",
  username: "adm075",
  password: "adm075",
  division: "P1B",
  divisionLabel: "ESTATE PARIT GUNUNG 1B",
  listPage: "/en/PR/trx/frmPrTrxADLists.aspx",
  sessionDir: path.resolve(process.cwd(), "../../../Runner/spsi_input/sessions"),
  sharedSessionId: "shared-session"
};
```

## Testing Results

### Test 1: Fresh Login (no session file)
```
Session Reused: No
Total Duration: 25964ms
```

### Test 2-5: Session Reuse
```
Run 2: Session Reused: Yes (1361ms)
Run 3: Session Reused: Yes (1286ms)
Run 4: Session Reused: Yes (1542ms)
Run 5: Session Reused: Yes (1594ms)
```

## Files

| File | Description |
|------|-------------|
| `template/apps/local-agent/src/runner/session-based-runner.ts` | Main source (working version) |
| `Runner/session-based-runner.stable.ts` | Stable backup copy |
| `Runner/spsi_input/sessions/shared-session.json` | Shared session storage |

## Dependencies

- Playwright 1.59.1+
- Node.js
- TypeScript 5.9.3+

## Build & Run

```bash
# Build
cd template/apps/local-agent
npm run build

# Run with session reuse
node dist/runner/session-based-runner.js --headless --session=shared-session
```

---

**Created**: 2026-04-25
**Status**: STABLE
**Version**: 1.0.0