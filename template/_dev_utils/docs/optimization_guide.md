# Flow Optimization Guide

## Principles

### 1. Timeout Hierarchy
- Navigation steps: 20s (openPage, waitForNavigation to new URL)
- Element interaction: 10s (click, type, select, check)
- Quick actions: 5s (pressKey, Tab)
- Element waiting: 15s (waitForElement)

### 2. Selector Priority
Use this order when building selectors:

| Priority | Selector Type | Example |
|----------|---------------|---------|
| 1 | ID | `#txtUsername` |
| 2 | CSS with ID | `input[name='txtUsername']` |
| 3 | Text match | `text=ESTATE PARIT GUNUNG 1B` |
| 4 | Role | `[role="button"]` |
| 5 | Tag | `input` |

### 3. Always Use Fallbacks
Every step that uses a selector should have `selectorFallback`:

```json
{
  "selector": "#preferred",
  "selectorFallback": {
    "css": "fallback-css",
    "text": "text fallback",
    "role": "role fallback"
  }
}
```

### 4. Variable Substitution
Use variables for credentials and dynamic values:

```json
{
  "value": "{{username}}",
  "valueMode": "variable",
  "variableRef": "username"
}
```

### 5. Wildcard URL Patterns
For pages that may have varying base URLs:

```json
{
  "value": "**/frmSystemUserSetlocation.aspx"
}
```

## Common Patterns

### Login Flow
1. openPage → waitForElement (username) → click → type (variable) → Tab
2. type (password, variable) → Tab → pressKey Enter
3. waitForNavigation

### Radio/Checkbox Selection
Use `check` type, not `click`, for radio buttons:

```json
{
  "type": "check",
  "selector": "input[value='AB1']"
}
```

### Data Entry Point Detection
The autocomplete input marks where manual data entry begins:

```json
{
  "type": "waitForElement",
  "selector": "input.ui-autocomplete-input"
}
```

## Retry Behavior

The engine automatically retries flaky operations with exponential backoff:
- Max attempts: 3
- Base delay: 200ms
- Max delay: 5000ms
- Multiplier: 2x

## Screenshot on Failure

When a step fails, a screenshot is automatically captured in `./screenshots/` with:
- Filename: `failure_{stepId}_{timestamp}.png`
- Full page capture

## Verification Checklist

- [ ] Template loads without validation errors
- [ ] Browser launches in headfull mode
- [ ] Login completes without timeout
- [ ] Location selection works
- [ ] Navigation to list page succeeds
- [ ] New button click leads to autocomplete input
- [ ] Screenshots appear in ./screenshots on failure
- [ ] Full flow completes under 10 seconds